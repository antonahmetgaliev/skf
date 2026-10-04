"""Access and refresh tokens: exchange, rotation, reuse and sign-out."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import RefreshToken
from app.services import tokens

TOKENS_URL = "/api/v1/auth/tokens"
REVOCATIONS_URL = "/api/v1/auth/token-revocations"
ME_URL = "/api/v1/me"


async def _login(db: AsyncSession, user) -> str:
    refresh_token = tokens.start_login(db, user.id)
    await db.commit()
    return refresh_token


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_exchange_returns_working_access_token(client: AsyncClient, db: AsyncSession, test_user):
    resp = await client.post(TOKENS_URL, json={"refreshToken": await _login(db, test_user)})

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["expiresIn"] == 15 * 60
    me = await client.get(ME_URL, headers=_bearer(body["accessToken"]))
    assert me.json()["id"] == str(test_user.id)


async def test_refresh_token_is_stored_hashed(db: AsyncSession, test_user):
    refresh_token = await _login(db, test_user)
    row = (await db.execute(select(RefreshToken))).scalar_one()
    assert row.token_hash != refresh_token and len(row.token_hash) == 64


async def test_each_refresh_hands_out_the_next_token(client: AsyncClient, db: AsyncSession, test_user):
    first = await _login(db, test_user)
    second = (await client.post(TOKENS_URL, json={"refreshToken": first})).json()["refreshToken"]
    assert second != first
    resp = await client.post(TOKENS_URL, json={"refreshToken": second})
    assert resp.status_code == 200


async def test_two_tabs_spending_one_token_both_succeed(client: AsyncClient, db: AsyncSession, test_user):
    first = await _login(db, test_user)
    assert (await client.post(TOKENS_URL, json={"refreshToken": first})).status_code == 200
    assert (await client.post(TOKENS_URL, json={"refreshToken": first})).status_code == 200


async def test_replaying_a_replaced_token_ends_the_login(client: AsyncClient, db: AsyncSession, test_user):
    first = await _login(db, test_user)
    second = (await client.post(TOKENS_URL, json={"refreshToken": first})).json()["refreshToken"]
    long_ago = datetime.now(UTC) - tokens.REUSE_GRACE - timedelta(seconds=1)
    await db.execute(update(RefreshToken).where(RefreshToken.used_at.is_not(None)).values(used_at=long_ago))
    await db.commit()

    resp = await client.post(TOKENS_URL, json={"refreshToken": first})
    assert resp.status_code == 401
    assert resp.json()["code"] == "invalid_token"
    # The thief and the owner are both out.
    assert (await client.post(TOKENS_URL, json={"refreshToken": second})).status_code == 401


async def test_expired_refresh_token_is_refused_and_purged(client: AsyncClient, db: AsyncSession, test_user):
    stale = await _login(db, test_user)
    await db.execute(update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    await db.commit()
    assert (await client.post(TOKENS_URL, json={"refreshToken": stale})).status_code == 401

    fresh = await _login(db, test_user)
    assert (await client.post(TOKENS_URL, json={"refreshToken": fresh})).status_code == 200
    db.expire_all()
    rows = (await db.execute(select(RefreshToken))).scalars().all()
    assert len(rows) == 2  # the spent one and its replacement; the expired one is gone


async def test_unknown_refresh_token_is_401(client: AsyncClient, seed_roles):
    resp = await client.post(TOKENS_URL, json={"refreshToken": "nope"})
    assert resp.status_code == 401


async def test_revocation_ends_only_that_login(client: AsyncClient, db: AsyncSession, test_user):
    phone = await _login(db, test_user)
    laptop = await _login(db, test_user)

    resp = await client.post(REVOCATIONS_URL, json={"refreshToken": phone})
    assert resp.status_code == 204
    assert (await client.post(TOKENS_URL, json={"refreshToken": phone})).status_code == 401
    assert (await client.post(TOKENS_URL, json={"refreshToken": laptop})).status_code == 200


async def test_revocation_of_unknown_token_is_204(client: AsyncClient, seed_roles):
    resp = await client.post(REVOCATIONS_URL, json={"refreshToken": "nope"})
    assert resp.status_code == 204


async def test_bad_access_token_is_401_even_where_anonymous_is_allowed(client: AsyncClient, test_user):
    """Otherwise an expired token would silently get the public view."""
    from app.config import settings

    expired = jwt.encode(
        {
            "sub": str(test_user.id),
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=tokens.ALGORITHM,
    )
    forged = jwt.encode(
        {"sub": str(test_user.id), "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1)},
        "another-secret-of-sufficient-length!",
        algorithm=tokens.ALGORITHM,
    )
    unknown_user, _ = tokens.issue_access_token(uuid.uuid4())

    for token in (expired, forged, unknown_user, "garbage"):
        resp = await client.get("/api/v1/languages", headers=_bearer(token))
        assert resp.status_code == 401, token
        assert resp.json()["code"] == "invalid_token"
    assert (await client.get("/api/v1/languages")).status_code == 200


async def test_blocked_user_token_is_refused(client: AsyncClient, db: AsyncSession, test_user):
    refresh_token = await _login(db, test_user)
    access_token, _ = tokens.issue_access_token(test_user.id)
    test_user.blocked = True
    await db.merge(test_user)
    await db.commit()

    assert (await client.get(ME_URL, headers=_bearer(access_token))).status_code == 401
    assert (await client.post(TOKENS_URL, json={"refreshToken": refresh_token})).status_code == 401


async def test_sign_in_is_unavailable_without_a_secret(
    client: AsyncClient, db: AsyncSession, test_user, monkeypatch
):
    from app.config import settings

    refresh_token = await _login(db, test_user)
    monkeypatch.setattr(settings, "jwt_secret", "")
    resp = await client.post(TOKENS_URL, json={"refreshToken": refresh_token})
    assert resp.status_code == 503

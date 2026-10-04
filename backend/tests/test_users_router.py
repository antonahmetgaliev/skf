"""Tests for /api/v1/users (admin user management)."""

from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

USERS_URL = "/api/v1/users"


@pytest_asyncio.fixture
async def admin_client(engine, db: AsyncSession, seed_roles):
    """AsyncClient authenticated as an admin."""
    import app.database as db_module
    from app.auth import get_current_user, get_current_user_optional
    from app.database import get_db
    from app.main import app
    from app.models.user import User
    from tests.conftest import _factory

    admin = User(id=uuid.uuid4(), discord_id="admin", username="aaa-admin", display_name="Admin", role_id=2)
    db.add(admin)
    await db.commit()
    admin = (
        await db.execute(select(User).options(joinedload(User.role)).where(User.id == admin.id))
    ).scalar_one()

    factory = _factory(engine)
    original = db_module.async_session
    db_module.async_session = factory

    async def _override_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_current_user_optional] = lambda: admin
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.admin = admin  # type: ignore[attr-defined]
        yield ac
    for dep in (get_db, get_current_user, get_current_user_optional):
        app.dependency_overrides.pop(dep, None)
    db_module.async_session = original


async def _add_users(db: AsyncSession, n: int, prefix: str = "d") -> list:
    from app.models.user import User

    users = [
        User(
            id=uuid.uuid4(),
            discord_id=f"{prefix}{i}",
            username=f"user{i:02d}" if prefix == "d" else f"user{prefix}{i:02d}",
            display_name=f"U{i}",
            role_id=1,
        )
        for i in range(n)
    ]
    db.add_all(users)
    await db.commit()
    return users


async def _add_community(db: AsyncSession, name: str = "SKF"):
    from app.models.community import Community

    community = Community(name=name)
    db.add(community)
    await db.commit()
    return community


async def test_list_users_is_paginated(admin_client: AsyncClient, db: AsyncSession):
    await _add_users(db, 5)  # + the admin = 6 users

    resp = await admin_client.get(USERS_URL, params={"limit": 2, "offset": 2})
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "6"
    assert 'rel="next"' in resp.headers["Link"] and 'rel="prev"' in resp.headers["Link"]
    assert [u["username"] for u in resp.json()] == ["user01", "user02"]


async def test_list_users_includes_driver_and_communities(admin_client: AsyncClient, db: AsyncSession):
    from app.models.bwp import Driver
    from app.models.community_manager import CommunityManager

    (user,) = await _add_users(db, 1)
    community = await _add_community(db)
    db.add_all(
        [
            Driver(name="Linked", user_id=user.id),
            CommunityManager(user_id=user.id, community_id=community.id),
        ]
    )
    await db.commit()

    resp = await admin_client.get(USERS_URL, params={"limit": 1000})
    row = next(u for u in resp.json() if u["id"] == str(user.id))
    assert row["driverId"] is not None
    assert row["managedCommunityIds"] == [str(community.id)]


async def test_users_requires_admin(auth_client: AsyncClient):
    resp = await auth_client.get(USERS_URL)
    assert resp.status_code == 403


async def test_update_user_role_and_block(admin_client: AsyncClient, db: AsyncSession):
    (user,) = await _add_users(db, 1)
    resp = await admin_client.patch(f"{USERS_URL}/{user.id}", json={"role": "admin"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"

    (other,) = await _add_users(db, 1, prefix="x")
    resp = await admin_client.patch(f"{USERS_URL}/{other.id}", json={"blocked": True})
    assert resp.status_code == 200
    assert resp.json()["blocked"] is True


async def test_admin_cannot_block_an_admin(admin_client: AsyncClient, db: AsyncSession):
    """Neither an existing admin nor one promoted in the same request."""
    (user,) = await _add_users(db, 1)
    resp = await admin_client.patch(f"{USERS_URL}/{user.id}", json={"role": "admin", "blocked": True})
    assert resp.status_code == 403

    resp = await admin_client.patch(f"{USERS_URL}/{admin_client.admin.id}", json={"blocked": True})
    assert resp.status_code == 403


async def test_admin_cannot_touch_a_super_admin(admin_client: AsyncClient, db: AsyncSession):
    from tests.roles import make_user

    boss = await make_user(db, "super_admin")
    community = await _add_community(db)

    assert (await admin_client.patch(f"{USERS_URL}/{boss.id}", json={"role": "driver"})).status_code == 403
    assert (await admin_client.delete(f"{USERS_URL}/{boss.id}/tokens")).status_code == 403
    resp = await admin_client.put(
        f"{USERS_URL}/{boss.id}/managed-communities", json={"communityIds": [str(community.id)]}
    )
    assert resp.status_code == 403
    (user,) = await _add_users(db, 1)
    resp = await admin_client.patch(f"{USERS_URL}/{user.id}", json={"role": "super_admin"})
    assert resp.status_code == 403


async def test_super_admin_cannot_be_blocked_while_being_promoted(
    admin_client: AsyncClient, db: AsyncSession
):
    from tests.roles import act_as, make_user

    boss = await make_user(db, "super_admin")
    (user,) = await _add_users(db, 1)
    act_as(boss)
    resp = await admin_client.patch(f"{USERS_URL}/{user.id}", json={"role": "super_admin", "blocked": True})
    assert resp.status_code == 403


async def test_update_user_unknown_role_is_422(admin_client: AsyncClient, db: AsyncSession):
    (user,) = await _add_users(db, 1)
    resp = await admin_client.patch(f"{USERS_URL}/{user.id}", json={"role": "wizard"})
    assert resp.status_code == 422


async def test_update_unknown_user_is_404(admin_client: AsyncClient):
    resp = await admin_client.patch(f"{USERS_URL}/{uuid.uuid4()}", json={"blocked": True})
    assert resp.status_code == 404


async def _login(db: AsyncSession, user) -> tuple[str, str]:
    """A refresh token and an access token of a fresh login."""
    from app.services import tokens

    refresh_token = tokens.start_login(db, user.id)
    await db.commit()
    access_token, _ = tokens.issue_access_token(user.id)
    return refresh_token, access_token


async def _token_is_accepted(client: AsyncClient, access_token: str) -> bool:
    """Whether the real token check lets *access_token* through."""
    from tests.roles import act_as

    act_as(None)
    resp = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {access_token}"})
    return resp.status_code == 200


async def test_revoke_tokens_ends_every_login_at_once(admin_client: AsyncClient, db: AsyncSession):
    from app.models.user import RefreshToken

    (user,) = await _add_users(db, 1)
    refresh_token, access_token = await _login(db, user)

    resp = await admin_client.delete(f"{USERS_URL}/{user.id}/tokens")
    assert resp.status_code == 204
    assert (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))).all() == []
    resp = await admin_client.post("/api/v1/auth/tokens", json={"refreshToken": refresh_token})
    assert resp.status_code == 401
    assert not await _token_is_accepted(admin_client, access_token)


async def test_block_ends_every_login(admin_client: AsyncClient, db: AsyncSession):
    (user,) = await _add_users(db, 1)
    refresh_token, access_token = await _login(db, user)

    resp = await admin_client.patch(f"{USERS_URL}/{user.id}", json={"blocked": True})
    assert resp.status_code == 200
    # Unblocking does not bring the old login back.
    resp = await admin_client.patch(f"{USERS_URL}/{user.id}", json={"blocked": False})
    assert resp.status_code == 200
    resp = await admin_client.post("/api/v1/auth/tokens", json={"refreshToken": refresh_token})
    assert resp.status_code == 401
    assert not await _token_is_accepted(admin_client, access_token)


async def test_managed_communities_roundtrip(admin_client: AsyncClient, db: AsyncSession):
    (user,) = await _add_users(db, 1)
    community = await _add_community(db)
    url = f"{USERS_URL}/{user.id}/managed-communities"

    resp = await admin_client.put(url, json={"communityIds": [str(community.id), str(community.id)]})
    assert resp.status_code == 200
    assert resp.json() == {"communityIds": [str(community.id)]}

    resp = await admin_client.get(url)
    assert resp.json() == {"communityIds": [str(community.id)]}

    resp = await admin_client.put(url, json={"communityIds": []})
    assert resp.json() == {"communityIds": []}


async def test_managed_communities_unknown_id_is_rejected(admin_client: AsyncClient, db: AsyncSession):
    (user,) = await _add_users(db, 1)
    community = await _add_community(db)
    resp = await admin_client.put(
        f"{USERS_URL}/{user.id}/managed-communities",
        json={"communityIds": [str(community.id), str(uuid.uuid4())]},
    )
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")

    resp = await admin_client.get(f"{USERS_URL}/{user.id}/managed-communities")
    assert resp.json() == {"communityIds": []}


async def test_managed_communities_invalid_uuid_is_422(admin_client: AsyncClient, db: AsyncSession):
    (user,) = await _add_users(db, 1)
    resp = await admin_client.put(
        f"{USERS_URL}/{user.id}/managed-communities", json={"communityIds": ["not-a-uuid"]}
    )
    assert resp.status_code == 422


async def test_managed_communities_unknown_user_is_404(admin_client: AsyncClient):
    resp = await admin_client.put(
        f"{USERS_URL}/{uuid.uuid4()}/managed-communities", json={"communityIds": []}
    )
    assert resp.status_code == 404

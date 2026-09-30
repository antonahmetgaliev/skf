"""Tests for /api/v1/me, the session endpoint and the legacy OAuth callback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ME_URL = "/api/v1/me"


def _now():
    return datetime.now(UTC)


async def test_me_returns_null_driver_id_when_not_linked(auth_client: AsyncClient):
    """When the user has no linked driver, driverId is null in the response."""
    resp = await auth_client.get(ME_URL)
    assert resp.status_code == 200
    assert resp.json()["driverId"] is None


async def test_me_returns_driver_id_when_linked(auth_client: AsyncClient, db: AsyncSession, test_user):
    """When the user has a linked driver, driverId matches driver.id."""
    from app.models.bwp import Driver

    driver = Driver(name="Linked Driver", user_id=test_user.id, created_at=_now())
    db.add(driver)
    await db.commit()

    resp = await auth_client.get(ME_URL)
    assert resp.status_code == 200
    assert resp.json()["driverId"] == str(driver.id)


async def test_me_returns_correct_user_fields(auth_client: AsyncClient, test_user):
    """Standard user fields are correctly serialised in the /me response."""
    resp = await auth_client.get(ME_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == test_user.username
    assert data["displayName"] == test_user.display_name
    assert data["role"] == "driver"
    assert data["blocked"] is False
    assert data["managedCommunityIds"] == []


async def test_me_returns_401_problem_when_unauthenticated(client: AsyncClient):
    resp = await client.get(ME_URL)
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["detail"] == "Not authenticated."


async def test_me_with_session_cookie(client: AsyncClient, db: AsyncSession, test_user):
    """A real session cookie (no dependency override) authenticates /me."""
    from app.auth import SESSION_COOKIE
    from app.models.user import Session

    session = Session(user_id=test_user.id, expires_at=_now() + timedelta(days=1))
    db.add(session)
    await db.commit()

    client.cookies.set(SESSION_COOKIE, str(session.id))
    resp = await client.get(ME_URL)
    assert resp.status_code == 200
    assert resp.json()["id"] == str(test_user.id)


async def test_discord_sync_without_bot_token_is_503_without_env_names(auth_client: AsyncClient, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "discord_guild_id", "")
    monkeypatch.setattr(settings, "discord_bot_token", "")
    resp = await auth_client.post(f"{ME_URL}/discord-syncs")
    assert resp.status_code == 503
    assert "DISCORD_" not in resp.json()["detail"]


async def test_logout_deletes_session_and_clears_cookie(client: AsyncClient, db: AsyncSession, test_user):
    from app.auth import SESSION_COOKIE
    from app.models.user import Session

    session = Session(user_id=test_user.id, expires_at=_now() + timedelta(days=1))
    db.add(session)
    await db.commit()
    session_id = session.id

    client.cookies.set(SESSION_COOKIE, str(session_id))
    resp = await client.delete("/api/v1/auth/session")
    assert resp.status_code == 204
    set_cookie = resp.headers.get("set-cookie", "")
    assert f"{SESSION_COOKIE}=" in set_cookie
    assert "Max-Age=0" in set_cookie or "expires=" in set_cookie.lower()

    db.expire_all()
    assert (await db.execute(select(Session).where(Session.id == session_id))).first() is None


async def test_logout_without_cookie_is_204(client: AsyncClient):
    resp = await client.delete("/api/v1/auth/session")
    assert resp.status_code == 204


async def test_authorization_url_sets_state_cookie(client: AsyncClient):
    resp = await client.get("/api/v1/auth/discord/authorization-url")
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://discord.com/api/oauth2/authorize?")
    assert "oauth_state=" in resp.headers.get("set-cookie", "")


async def test_callback_keeps_legacy_path_and_rejects_bad_state(client: AsyncClient):
    client.cookies.set("oauth_state", "expected")
    resp = await client.get("/api/auth/discord/callback", params={"code": "abc", "state": "wrong"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid OAuth state. Please retry the login."


async def test_callback_not_served_under_v1(client: AsyncClient):
    resp = await client.get("/api/v1/auth/discord/callback", params={"code": "abc"})
    assert resp.status_code == 404


async def test_callback_logs_in_and_redirects_to_frontend(
    client: AsyncClient, db: AsyncSession, seed_roles, monkeypatch
):
    """Full callback with Discord mocked: user upserted, cookie set, redirect to FRONTEND_URL."""
    import httpx

    from app.api.v1 import auth as auth_router
    from app.config import settings
    from app.services import auth as auth_service

    monkeypatch.setattr(settings, "frontend_url", "https://skf.example")
    monkeypatch.setattr(settings, "discord_guild_id", "")

    async def noop(*_args):
        return None

    monkeypatch.setattr(auth_router, "link_driver_for_user", noop)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(200, json={"id": "999", "username": "newbie", "global_name": "New Bie"})

    real_client = httpx.AsyncClient

    def mocked_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(auth_service.httpx, "AsyncClient", mocked_client)

    client.cookies.set("oauth_state", "s")
    resp = await client.get("/api/auth/discord/callback", params={"code": "abc", "state": "s"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://skf.example"
    cookies = resp.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("session_id="))
    assert "Secure" in session_cookie

    from app.models.user import User

    user = (await db.execute(select(User).where(User.discord_id == "999"))).scalar_one()
    assert user.guild_nickname == "New Bie"


async def test_callback_incomplete_discord_response_is_502(client: AsyncClient, monkeypatch):
    import httpx

    from app.services import auth as auth_service

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token_type": "Bearer"})

    real_client = httpx.AsyncClient

    def mocked_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(auth_service.httpx, "AsyncClient", mocked_client)

    client.cookies.set("oauth_state", "s")
    resp = await client.get("/api/auth/discord/callback", params={"code": "abc", "state": "s"})
    assert resp.status_code == 502

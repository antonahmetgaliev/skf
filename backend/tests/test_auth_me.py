"""Tests for /api/v1/me and the legacy OAuth callback."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

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
    from tests.roles import link_driver

    driver = Driver(name="Linked Driver", created_at=_now())
    db.add(driver)
    await db.commit()
    await link_driver(db, test_user, driver)

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


async def test_me_with_access_token(client: AsyncClient, test_user):
    """A real access token (no dependency override) authenticates /me."""
    from app.services import tokens

    token, _ = tokens.issue_access_token(test_user.id)
    resp = await client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["id"] == str(test_user.id)


async def test_discord_sync_without_bot_token_is_503_without_env_names(auth_client: AsyncClient, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "discord_guild_id", "")
    monkeypatch.setattr(settings, "discord_bot_token", "")
    resp = await auth_client.post(f"{ME_URL}/discord-syncs")
    assert resp.status_code == 503
    assert "DISCORD_" not in resp.json()["detail"]


def _fragment(resp) -> dict[str, str]:
    """The callback's outcome, from the fragment of its redirect."""
    assert resp.status_code == 302
    location = urlsplit(resp.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}".endswith("/auth/callback")
    return {key: values[0] for key, values in parse_qs(location.fragment).items()}


async def test_authorization_url_sets_state_cookie(client: AsyncClient):
    resp = await client.get("/api/v1/auth/discord/authorization-url")
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://discord.com/api/oauth2/authorize?")
    assert "oauth_state=" in resp.headers.get("set-cookie", "")


async def test_callback_keeps_legacy_path_and_rejects_bad_state(client: AsyncClient):
    client.cookies.set("oauth_state", "expected")
    resp = await client.get("/api/auth/discord/callback", params={"code": "abc", "state": "wrong"})
    assert _fragment(resp) == {"error": "invalid_state"}


async def test_callback_declined_on_discord_redirects_with_error(client: AsyncClient):
    resp = await client.get("/api/auth/discord/callback", params={"error": "access_denied", "state": "s"})
    assert _fragment(resp) == {"error": "access_denied"}


async def test_callback_not_served_under_v1(client: AsyncClient):
    resp = await client.get("/api/v1/auth/discord/callback", params={"code": "abc"})
    assert resp.status_code == 404


async def test_callback_logs_in_and_redirects_to_frontend(
    client: AsyncClient, db: AsyncSession, seed_roles, monkeypatch
):
    """Full callback with Discord mocked: user upserted, redirect carries a usable refresh token."""
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
    assert resp.headers["location"].startswith("https://skf.example/auth/callback#")
    assert "session_id=" not in resp.headers.get("set-cookie", "")

    from app.models.user import User

    user = (await db.execute(select(User).where(User.discord_id == "999"))).scalar_one()
    assert user.guild_nickname == "New Bie"

    resp = await client.post("/api/v1/auth/tokens", json={"refreshToken": _fragment(resp)["token"]})
    assert resp.status_code == 200
    me = await client.get(ME_URL, headers={"Authorization": f"Bearer {resp.json()['accessToken']}"})
    assert me.json()["id"] == str(user.id)


async def test_callback_for_blocked_user_redirects_with_error(
    client: AsyncClient, db: AsyncSession, test_user, monkeypatch
):
    import httpx

    from app.config import settings
    from app.models.user import RefreshToken
    from app.services import auth as auth_service

    monkeypatch.setattr(settings, "discord_guild_id", "")
    test_user.blocked = True
    await db.merge(test_user)
    await db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(200, json={"id": test_user.discord_id, "username": "tester"})

    real_client = httpx.AsyncClient

    def mocked_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(auth_service.httpx, "AsyncClient", mocked_client)

    client.cookies.set("oauth_state", "s")
    resp = await client.get("/api/auth/discord/callback", params={"code": "abc", "state": "s"})
    assert _fragment(resp) == {"error": "blocked"}
    assert (await db.execute(select(RefreshToken))).first() is None


async def test_callback_incomplete_discord_response_redirects_with_error(client: AsyncClient, monkeypatch):
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
    assert _fragment(resp) == {"error": "upstream_error"}

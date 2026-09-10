"""Tests for the calendar's community join-request endpoint."""
from __future__ import annotations

import uuid

import pytest

from app.config import settings

WEBHOOK = "https://discord.com/api/webhooks/123/abc"
PAYLOAD = {
    "name": "Night Racers",
    "discordUrl": "https://discord.gg/abc123",
    "description": "We run weekly ACC endurance races on Sunday evenings.",
}


@pytest.fixture(autouse=True)
def clear_rate_limit():
    """The cooldown store is a module-level global shared across tests."""
    from app.routers.calendar import _last_request_at

    _last_request_at.clear()
    yield
    _last_request_at.clear()


# ── Router ───────────────────────────────────────────────────────────────────

async def test_requires_login(client):
    resp = await client.post("/api/calendar/community-requests", json=PAYLOAD)
    assert resp.status_code == 401


async def test_sends_request_and_returns_202(auth_client, monkeypatch, test_user):
    sent = {}

    async def _fake_send(*, name, description, discord_url, user):
        sent.update(
            name=name, description=description, discord_url=discord_url, user=user
        )

    monkeypatch.setattr("app.routers.calendar.send_community_request", _fake_send)

    resp = await auth_client.post("/api/calendar/community-requests", json=PAYLOAD)

    assert resp.status_code == 202
    assert sent["name"] == "Night Racers"
    assert sent["discord_url"] == "https://discord.gg/abc123"
    # The requester is taken from the session, never from the payload.
    assert sent["user"].id == test_user.id


async def test_strips_whitespace_and_blanks_empty_discord_url(auth_client, monkeypatch):
    sent = {}

    async def _fake_send(*, name, description, discord_url, user):
        sent.update(name=name, description=description, discord_url=discord_url)

    monkeypatch.setattr("app.routers.calendar.send_community_request", _fake_send)

    resp = await auth_client.post(
        "/api/calendar/community-requests",
        json={**PAYLOAD, "name": "  Night Racers  ", "discordUrl": "   "},
    )

    assert resp.status_code == 202
    assert sent["name"] == "Night Racers"
    assert sent["discord_url"] is None


async def test_second_request_is_rate_limited(auth_client, monkeypatch):
    async def _fake_send(**_kwargs):
        return None

    monkeypatch.setattr("app.routers.calendar.send_community_request", _fake_send)

    first = await auth_client.post("/api/calendar/community-requests", json=PAYLOAD)
    second = await auth_client.post("/api/calendar/community-requests", json=PAYLOAD)

    assert first.status_code == 202
    assert second.status_code == 429


async def test_503_when_webhook_not_configured(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "discord_community_request_webhook_url", "")

    resp = await auth_client.post("/api/calendar/community-requests", json=PAYLOAD)

    assert resp.status_code == 503


async def test_502_when_discord_rejects(auth_client, monkeypatch):
    from app.services.discord import DiscordSendFailed

    async def _fake_send(**_kwargs):
        raise DiscordSendFailed

    monkeypatch.setattr("app.routers.calendar.send_community_request", _fake_send)

    resp = await auth_client.post("/api/calendar/community-requests", json=PAYLOAD)

    assert resp.status_code == 502


async def test_a_failed_send_does_not_consume_the_cooldown(auth_client, monkeypatch):
    """A user whose request failed must be able to retry immediately."""
    from app.services.discord import DiscordSendFailed

    async def _failing(**_kwargs):
        raise DiscordSendFailed

    monkeypatch.setattr("app.routers.calendar.send_community_request", _failing)
    assert (
        await auth_client.post("/api/calendar/community-requests", json=PAYLOAD)
    ).status_code == 502

    async def _ok(**_kwargs):
        return None

    monkeypatch.setattr("app.routers.calendar.send_community_request", _ok)
    assert (
        await auth_client.post("/api/calendar/community-requests", json=PAYLOAD)
    ).status_code == 202


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "x"},                     # too short
        {"description": "too short"},      # under 10 chars
        {"name": ""},
    ],
)
async def test_validation_rejects_bad_input(auth_client, monkeypatch, bad):
    async def _fake_send(**_kwargs):
        raise AssertionError("should not be called")

    monkeypatch.setattr("app.routers.calendar.send_community_request", _fake_send)

    resp = await auth_client.post(
        "/api/calendar/community-requests", json={**PAYLOAD, **bad}
    )

    assert resp.status_code == 422


# ── Service ──────────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


def _fake_client_factory(captured: dict, status_code: int = 204):
    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse(status_code)

    return _FakeClient


def _user():
    from app.models.user import User

    return User(
        id=uuid.uuid4(),
        discord_id="111222333",
        username="tester",
        display_name="Test Driver",
        guild_nickname="Nick",
        role_id=1,
    )


async def test_service_suppresses_mentions_and_posts_embed(monkeypatch):
    from app.services import discord as discord_service

    captured: dict = {}
    monkeypatch.setattr(settings, "discord_community_request_webhook_url", WEBHOOK)
    monkeypatch.setattr(
        discord_service.httpx, "AsyncClient", _fake_client_factory(captured)
    )

    await discord_service.send_community_request(
        name="@everyone Racers",
        description="A description that is long enough.",
        discord_url=None,
        user=_user(),
    )

    assert captured["url"] == WEBHOOK
    body = captured["json"]
    # User-supplied text must never be able to ping.
    assert body["allowed_mentions"] == {"parse": []}
    assert captured["timeout"] is not None

    embed = body["embeds"][0]
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["Community"] == "@everyone Racers"
    assert fields["Discord"] == "—"
    assert fields["Discord ID"] == "111222333"
    assert "tester" in fields["Requested by"] and "Nick" in fields["Requested by"]
    assert embed["description"] == "A description that is long enough."


async def test_service_raises_when_unconfigured(monkeypatch):
    from app.services import discord as discord_service

    monkeypatch.setattr(settings, "discord_community_request_webhook_url", "")

    with pytest.raises(discord_service.DiscordNotConfigured):
        await discord_service.send_community_request(
            name="Night Racers",
            description="A description that is long enough.",
            discord_url=None,
            user=_user(),
        )


async def test_service_raises_on_non_204_status(monkeypatch):
    from app.services import discord as discord_service

    captured: dict = {}
    monkeypatch.setattr(settings, "discord_community_request_webhook_url", WEBHOOK)
    monkeypatch.setattr(
        discord_service.httpx,
        "AsyncClient",
        _fake_client_factory(captured, status_code=404),
    )

    with pytest.raises(discord_service.DiscordSendFailed):
        await discord_service.send_community_request(
            name="Night Racers",
            description="A description that is long enough.",
            discord_url=None,
            user=_user(),
        )

"""Discord OAuth2 login and Discord nickname sync."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import BadGateway, BadRequest, Forbidden, ServiceUnavailable
from app.models.user import ROLE_DRIVER, ROLE_SUPER_ADMIN, Role, User
from app.services import tokens

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api"
DISCORD_AUTH_URL = f"{DISCORD_API}/oauth2/authorize"
DISCORD_TOKEN_URL = f"{DISCORD_API}/oauth2/token"
DISCORD_USER_URL = f"{DISCORD_API}/users/@me"

HTTP_TIMEOUT = httpx.Timeout(10.0)


def authorization_url(state: str) -> str:
    """The Discord OAuth2 authorization URL for a flow guarded by *state*."""
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_redirect_uri,
        "response_type": "code",
        "scope": "identify guilds.members.read",
        "state": state,
    }
    return f"{DISCORD_AUTH_URL}?{urlencode(params)}"


def frontend_is_secure() -> bool:
    """The OAuth state cookie is ``Secure`` exactly when the frontend is served over https."""
    return urlparse(settings.frontend_url).scheme == "https"


# ── Discord API ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DiscordProfile:
    id: str
    username: str
    display_name: str
    avatar_hash: str | None


@dataclass(frozen=True)
class MemberLookup:
    """Outcome of a guild-member lookup.

    ``status`` is Discord's HTTP status, or ``None`` when the call itself
    failed. Only a 200 carries a nickname worth storing.
    """

    status: int | None
    nickname: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200


def _json(resp: httpx.Response, what: str) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        logger.error("Discord %s returned a non-object body", what)
        raise BadGateway(f"Discord returned an invalid {what} response.")
    return data


async def _exchange_code(client: httpx.AsyncClient, code: str) -> str:
    resp = await client.post(
        DISCORD_TOKEN_URL,
        data={
            "client_id": settings.discord_client_id,
            "client_secret": settings.discord_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.discord_redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code != 200:
        logger.error("Discord token exchange failed (status %s): %s", resp.status_code, resp.text)
        raise BadGateway("Discord token exchange failed.")
    access_token = _json(resp, "token").get("access_token")
    if not access_token:
        raise BadGateway("Discord token response is missing the access token.")
    return access_token


async def _fetch_profile(client: httpx.AsyncClient, access_token: str) -> DiscordProfile:
    resp = await client.get(DISCORD_USER_URL, headers={"Authorization": f"Bearer {access_token}"})
    if resp.status_code != 200:
        logger.error("Discord user fetch failed (status %s): %s", resp.status_code, resp.text)
        raise BadGateway("Failed to fetch Discord user info.")
    data = _json(resp, "user")
    discord_id = data.get("id")
    if not discord_id:
        raise BadGateway("Discord user response is missing the user id.")
    username = data.get("username") or ""
    return DiscordProfile(
        id=str(discord_id),
        username=username,
        display_name=data.get("global_name") or username,
        avatar_hash=data.get("avatar"),
    )


async def lookup_guild_member(url: str, authorization: str) -> MemberLookup:
    """Fetch a guild member and derive its nickname.

    Priority: server nick → member's global name → ``None``. Network errors
    and non-200 answers come back as a lookup without a nickname so callers
    can decide whether to keep the stored value.
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": authorization})
    except httpx.HTTPError as exc:
        logger.warning("Guild member fetch failed: %s", type(exc).__name__)
        return MemberLookup(status=None)
    if resp.status_code != 200:
        logger.warning("Guild member fetch failed (status %s)", resp.status_code)
        return MemberLookup(status=resp.status_code)
    try:
        data = resp.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return MemberLookup(status=None)
    member_user = data.get("user")
    global_name = member_user.get("global_name") if isinstance(member_user, dict) else None
    return MemberLookup(status=200, nickname=data.get("nick") or global_name or None)


# ── Login ───────────────────────────────────────────────────────────────────


async def _upsert_user(db: AsyncSession, profile: DiscordProfile, member: MemberLookup | None) -> User:
    user = (await db.execute(select(User).where(User.discord_id == profile.id))).scalar_one_or_none()

    fetched_nickname = member.nickname if member else None
    if user is None:
        # Bootstrap the configured super-admin on their first login.
        role_name = ROLE_DRIVER
        if settings.super_admin_discord_id and profile.id == settings.super_admin_discord_id:
            role_name = ROLE_SUPER_ADMIN
        role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one()
        user = User(
            discord_id=profile.id,
            username=profile.username,
            display_name=profile.display_name,
            guild_nickname=fetched_nickname or profile.display_name or None,
            avatar_hash=profile.avatar_hash,
            role_id=role.id,
        )
        db.add(user)
    else:
        user.username = profile.username
        user.display_name = profile.display_name
        user.avatar_hash = profile.avatar_hash
        # A failed fetch keeps the stored value — never downgrade it.
        if member is not None and member.ok:
            user.guild_nickname = fetched_nickname or profile.display_name or None
        elif not user.guild_nickname:
            user.guild_nickname = profile.display_name or None

    user.last_login_at = datetime.now(UTC)
    await db.flush()
    return user


async def login_with_discord(db: AsyncSession, code: str) -> tuple[User, str]:
    """Complete the OAuth flow: exchange *code*, upsert the user, start a login.

    Returns the user and the login's first refresh token.
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            access_token = await _exchange_code(client, code)
            profile = await _fetch_profile(client, access_token)
    except httpx.HTTPError as exc:
        logger.error("Discord OAuth call failed: %s", type(exc).__name__)
        raise BadGateway("Discord is not reachable. Please retry the login.") from exc

    # guilds.members.read lets the user's own token read their server member.
    member: MemberLookup | None = None
    if settings.discord_guild_id:
        member = await lookup_guild_member(
            f"{DISCORD_API}/users/@me/guilds/{settings.discord_guild_id}/member",
            f"Bearer {access_token}",
        )

    user = await _upsert_user(db, profile, member)
    if user.blocked:
        await db.rollback()
        raise Forbidden("Your account has been blocked.", code="blocked")

    refresh_token = tokens.start_login(db, user.id)
    await db.commit()
    return user, refresh_token


def check_state(state: str, expected: str | None) -> None:
    """CSRF check: the callback's state must match the cookie set at flow start."""
    if not expected or not state or not secrets.compare_digest(state, expected):
        raise BadRequest("Invalid OAuth state. Please retry the login.", code="invalid_state")


# ── Nickname sync ───────────────────────────────────────────────────────────


async def sync_discord_nickname(db: AsyncSession, user: User) -> None:
    """Re-fetch *user*'s server nickname with the bot token.

    Never downgrades the stored value on a transient failure.
    """
    if not settings.discord_guild_id or not settings.discord_bot_token:
        raise ServiceUnavailable(
            "Discord nickname sync is not available. Log out and log back in to refresh your nickname."
        )

    member = await lookup_guild_member(
        f"{DISCORD_API}/guilds/{settings.discord_guild_id}/members/{user.discord_id}",
        f"Bot {settings.discord_bot_token}",
    )
    if member.ok:
        user.guild_nickname = member.nickname or user.display_name or None
        await db.commit()
    elif member.status == 404:
        # Not a member of the server (anymore) — fall back to the global name.
        user.guild_nickname = user.display_name or None
        await db.commit()

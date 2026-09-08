"""Discord OAuth2 authentication endpoints."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import SESSION_COOKIE, get_current_user, get_current_user_optional, get_managed_community_ids
from app.config import settings
from app.database import get_db
from app.models.bwp import Driver
from app.models.user import Role, Session, User, ROLE_DRIVER, ROLE_SUPER_ADMIN, ROLE_COMMUNITY_MANAGER
from app.schemas.auth import AuthUrlOut, UserOut
from app.services.drivers import link_driver_for_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"

OAUTH_STATE_COOKIE = "oauth_state"


async def build_user_out(user: User, db: AsyncSession) -> UserOut:
    """Single source of truth for serialising a user — every auth endpoint
    must return the same shape (driver link and managed communities
    included), otherwise the frontend's cached user silently loses fields."""
    result = await db.execute(select(Driver.id).where(Driver.user_id == user.id))
    driver_id = result.scalars().first()

    managed_ids: list[str] = []
    if user.role.name == ROLE_COMMUNITY_MANAGER:
        managed_ids = [str(cid) for cid in await get_managed_community_ids(user, db)]

    return UserOut(
        id=user.id,
        discord_id=user.discord_id,
        username=user.username,
        display_name=user.display_name,
        discord_nickname=user.guild_nickname,
        avatar_url=user.avatar_url,
        role=user.role.name,
        blocked=user.blocked,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        driver_id=driver_id,
        managed_community_ids=managed_ids,
    )


@router.get("/discord", response_model=AuthUrlOut)
async def discord_login_url(response: Response):
    """Return the Discord OAuth2 authorization URL (with CSRF state)."""
    state = secrets.token_urlsafe(32)
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_redirect_uri,
        "response_type": "code",
        "scope": "identify guilds.members.read",
        "state": state,
    }
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        httponly=True,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return AuthUrlOut(url=f"{DISCORD_AUTH_URL}?{urlencode(params)}")


@router.get("/discord/callback")
async def discord_callback(
    code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    state: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth2 callback from Discord."""
    # 0. CSRF check: state must match the cookie set when the flow started.
    expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not expected_state or not state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state. Please retry the login.",
        )

    # 1. Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
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
        if token_resp.status_code != 200:
            logger.error("Discord token exchange failed: %s", token_resp.text)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Discord token exchange failed.",
            )
        token_data = token_resp.json()
        access_token = token_data["access_token"]

        # 2. Fetch Discord user info
        user_resp = await client.get(
            DISCORD_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            logger.error("Discord user fetch failed: %s", user_resp.text)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch Discord user info.",
            )
        discord_user = user_resp.json()

    discord_id = discord_user["id"]
    username = discord_user.get("username", "")
    display_name = discord_user.get("global_name") or username
    avatar_hash = discord_user.get("avatar")

    # 3a. Fetch the user's server nickname using their own bearer token.
    # guilds.members.read scope lets us call /users/@me/guilds/{id}/member directly.
    # Priority: server nick (nick) → member's global_name → None.
    # ``fetched`` distinguishes "Discord answered" from "call failed" — on
    # failure we must NOT downgrade a previously stored nickname.
    fetched_nickname: str | None = None
    nickname_fetch_ok = False
    if settings.discord_guild_id:
        async with httpx.AsyncClient() as bearer_client:
            member_resp = await bearer_client.get(
                f"https://discord.com/api/users/@me/guilds/{settings.discord_guild_id}/member",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if member_resp.status_code == 200:
                member_data = member_resp.json()
                nickname_fetch_ok = True
                fetched_nickname = (
                    member_data.get("nick")
                    or member_data.get("user", {}).get("global_name")
                    or None
                )
            else:
                logger.warning(
                    "Guild member fetch failed for %s (status %s): %s",
                    discord_id,
                    member_resp.status_code,
                    member_resp.text,
                )

    # 3. Upsert user
    result = await db.execute(select(User).where(User.discord_id == discord_id))
    user = result.scalar_one_or_none()

    if user is None:
        # Determine role – bootstrap super-admin if configured
        role_name = ROLE_DRIVER
        if (
            settings.super_admin_discord_id
            and discord_id == settings.super_admin_discord_id
        ):
            role_name = ROLE_SUPER_ADMIN

        role_result = await db.execute(
            select(Role).where(Role.name == role_name)
        )
        role_obj = role_result.scalar_one()

        user = User(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
            guild_nickname=fetched_nickname or display_name or None,
            avatar_hash=avatar_hash,
            role_id=role_obj.id,
        )
        db.add(user)
    else:
        user.username = username
        user.display_name = display_name
        user.avatar_hash = avatar_hash
        # A failed fetch keeps the stored value — never downgrade it.
        if nickname_fetch_ok:
            user.guild_nickname = fetched_nickname or display_name or None
        elif not user.guild_nickname:
            user.guild_nickname = display_name or None

    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()

    if user.blocked:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been blocked.",
        )

    # 4. Create session
    session = Session(
        user_id=user.id,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=settings.session_max_age_hours),
    )
    db.add(session)
    await db.commit()

    # 4b. Auto-link the user's driver via SimGrid discord_uid — after the
    # response, so a SimGrid hiccup never affects login.
    background_tasks.add_task(link_driver_for_user, user.id, discord_id)

    # 5. Set cookie & redirect to frontend
    # Use X-Forwarded-Host (set by the frontend proxy) to get the
    # public domain, falling back to the Host header.
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
    origin = f"{scheme}://{host}".rstrip("/")
    is_secure = scheme == "https"

    redirect = RedirectResponse(url=origin, status_code=302)
    redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    redirect.set_cookie(
        key=SESSION_COOKIE,
        value=str(session.id),
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=settings.session_max_age_hours * 3600,
        path="/",
    )
    return redirect


@router.get("/me", response_model=UserOut, responses={204: {"description": "Not authenticated"}})
async def get_me(
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return the currently authenticated user, or 204 if not logged in."""
    if user is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return await build_user_out(user, db)


@router.post("/refresh-discord-nickname", response_model=UserOut)
async def refresh_discord_nickname(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-fetch the current user's server nickname via bot token.

    Called silently by the profile page; never downgrades the stored value
    on a failed fetch.
    """
    if not settings.discord_guild_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DISCORD_GUILD_ID is not configured on the server.",
        )

    if not settings.discord_bot_token:
        # No bot token — bearer token from OAuth is not stored, user must re-login.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="No bot token configured. Log out and log back in to refresh your nickname.",
        )

    async with httpx.AsyncClient() as client:
        member_resp = await client.get(
            f"https://discord.com/api/guilds/{settings.discord_guild_id}/members/{user.discord_id}",
            headers={"Authorization": f"Bot {settings.discord_bot_token}"},
        )
    if member_resp.status_code == 200:
        member_data = member_resp.json()
        user.guild_nickname = (
            member_data.get("nick")
            or member_data.get("user", {}).get("global_name")
            or user.display_name
            or None
        )
        await db.commit()
    elif member_resp.status_code == 404:
        # Not a member of the server (anymore) — fall back to the global name.
        user.guild_nickname = user.display_name or None
        await db.commit()
    else:
        # Transient Discord failure (429/5xx): keep the stored value.
        logger.warning(
            "Bot guild member fetch failed for %s (status %s)",
            user.discord_id, member_resp.status_code,
        )

    return await build_user_out(user, db)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Delete the current session and clear cookie."""
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        try:
            session_id = uuid.UUID(raw)
            result = await db.execute(
                select(Session).where(Session.id == session_id)
            )
            session = result.scalar_one_or_none()
            if session:
                await db.delete(session)
                await db.commit()
        except ValueError:
            pass
    response.delete_cookie(SESSION_COOKIE, path="/")

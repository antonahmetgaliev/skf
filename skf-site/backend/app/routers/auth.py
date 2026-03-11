"""Discord OAuth2 authentication endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import SESSION_COOKIE, get_current_user
from app.config import settings
from app.database import get_db
from app.models.user import Role, Session, User, ROLE_DRIVER, ROLE_SUPER_ADMIN
from app.schemas.auth import AuthUrlOut, UserOut, GuildNicknameUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"


@router.get("/discord", response_model=AuthUrlOut)
async def discord_login_url():
    """Return the Discord OAuth2 authorization URL."""
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_redirect_uri,
        "response_type": "code",
        "scope": "identify",
    }
    return AuthUrlOut(url=f"{DISCORD_AUTH_URL}?{urlencode(params)}")


@router.get("/discord/callback")
async def discord_callback(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth2 callback from Discord."""
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

    # 3a. Optionally fetch the user's server nickname from the SKF guild.
    # Priority: server nick → member's global_name → OAuth global_name (display_name)
    guild_nickname: str | None = None
    if settings.discord_guild_id and settings.discord_bot_token:
        async with httpx.AsyncClient() as bot_client:
            member_resp = await bot_client.get(
                f"https://discord.com/api/guilds/{settings.discord_guild_id}/members/{discord_id}",
                headers={"Authorization": f"Bot {settings.discord_bot_token}"},
            )
            if member_resp.status_code == 200:
                member_data = member_resp.json()
                guild_nickname = (
                    member_data.get("nick")
                    or member_data.get("user", {}).get("global_name")
                    or None
                )
            else:
                logger.warning(
                    "Could not fetch guild member for %s: %s",
                    discord_id,
                    member_resp.status_code,
                )
    # Final fallback: use the Discord global display name so it's never empty
    if guild_nickname is None:
        guild_nickname = display_name or None

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
            guild_nickname=guild_nickname,
            avatar_hash=avatar_hash,
            role_id=role_obj.id,
        )
        db.add(user)
    else:
        user.username = username
        user.display_name = display_name
        user.guild_nickname = guild_nickname
        user.avatar_hash = avatar_hash

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

    # 5. Set cookie & redirect to frontend
    # Use X-Forwarded-Host (set by the frontend proxy) to get the
    # public domain, falling back to the Host header.
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
    origin = f"{scheme}://{host}".rstrip("/")
    is_secure = scheme == "https"

    redirect = RedirectResponse(url=origin, status_code=302)
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


@router.get("/me", response_model=UserOut)
async def get_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the currently authenticated user."""
    from app.models.bwp import Driver

    result = await db.execute(select(Driver).where(Driver.user_id == user.id))
    linked_driver = result.scalar_one_or_none()
    return UserOut(
        id=user.id,
        discord_id=user.discord_id,
        username=user.username,
        display_name=user.display_name,
        guild_nickname=user.guild_nickname,
        avatar_url=user.avatar_url,
        role=user.role.name,
        blocked=user.blocked,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        driver_id=linked_driver.id if linked_driver else None,
    )


@router.patch("/guild-nickname", response_model=UserOut)
async def update_guild_nickname(
    body: GuildNicknameUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Allow the current user to manually set their racing/guild name."""
    name = body.guild_nickname.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name cannot be empty.")
    user.guild_nickname = name
    await db.commit()

    from app.models.bwp import Driver as DriverModel
    drv_result = await db.execute(select(DriverModel).where(DriverModel.user_id == user.id))
    linked_driver = drv_result.scalar_one_or_none()
    return UserOut(
        id=user.id,
        discord_id=user.discord_id,
        username=user.username,
        display_name=user.display_name,
        guild_nickname=user.guild_nickname,
        avatar_url=user.avatar_url,
        role=user.role.name,
        blocked=user.blocked,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        driver_id=linked_driver.id if linked_driver else None,
    )


@router.post("/refresh-guild-nickname", response_model=UserOut)
async def refresh_guild_nickname(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-fetch and update the current user's guild nickname from Discord."""
    if not settings.discord_guild_id or not settings.discord_bot_token:
        # No bot configured — fall back to the user's global display name
        user.guild_nickname = user.display_name or None
    else:
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
            elif member_resp.status_code == 404:
                user.guild_nickname = user.display_name or None
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to fetch guild member data from Discord.",
                )

    await db.commit()

    from app.models.bwp import Driver as DriverModel
    drv_result = await db.execute(select(DriverModel).where(DriverModel.user_id == user.id))
    linked_driver = drv_result.scalar_one_or_none()
    return UserOut(
        id=user.id,
        discord_id=user.discord_id,
        username=user.username,
        display_name=user.display_name,
        guild_nickname=user.guild_nickname,
        avatar_url=user.avatar_url,
        role=user.role.name,
        blocked=user.blocked,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        driver_id=linked_driver.id if linked_driver else None,
    )


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

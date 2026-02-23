"""Discord OAuth2 authentication endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import SESSION_COOKIE, get_current_user
from app.config import settings
from app.database import get_db
from app.models.user import Session, User, UserRole
from app.schemas.auth import AuthUrlOut, UserOut

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
    response: Response,
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

    # 3. Upsert user
    result = await db.execute(select(User).where(User.discord_id == discord_id))
    user = result.scalar_one_or_none()

    if user is None:
        # Determine role – bootstrap super-admin if configured
        role = UserRole.driver
        if (
            settings.super_admin_discord_id
            and discord_id == settings.super_admin_discord_id
        ):
            role = UserRole.super_admin

        user = User(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
            avatar_hash=avatar_hash,
            role=role,
        )
        db.add(user)
    else:
        user.username = username
        user.display_name = display_name
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

    response.status_code = 307
    response.headers["Location"] = origin
    response.set_cookie(
        key=SESSION_COOKIE,
        value=str(session.id),
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=settings.session_max_age_hours * 3600,
        path="/",
    )
    return response


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return UserOut(
        id=user.id,
        discord_id=user.discord_id,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=user.role.value,
        blocked=user.blocked,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
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

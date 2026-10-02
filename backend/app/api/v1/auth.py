"""Discord OAuth2 login and session endpoints."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import SESSION_COOKIE
from app.config import settings
from app.core.openapi import problem_responses
from app.database import get_db
from app.schemas.auth import AuthUrlOut
from app.services import auth as auth_service
from app.services.drivers import link_driver_for_user

router = APIRouter(prefix="/auth", tags=["Auth"])

# The Discord redirect URI is registered as /api/auth/discord/callback and
# cannot be changed, so the callback keeps its pre-v1 path.
legacy_router = APIRouter(prefix="/auth/discord", tags=["Auth"])

OAUTH_STATE_COOKIE = "oauth_state"


@router.get("/discord/authorization-url", response_model=AuthUrlOut)
async def discord_authorization_url(response: Response):
    """Return the Discord OAuth2 authorization URL (with CSRF state)."""
    state = secrets.token_urlsafe(32)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        httponly=True,
        secure=auth_service.frontend_is_secure(),
        samesite="lax",
        max_age=600,
        path="/",
    )
    return AuthUrlOut(url=auth_service.authorization_url(state))


@legacy_router.get(
    "/callback",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    responses={
        302: {
            "description": "Signed in: redirects to the frontend with the session cookie set.",
            "headers": {"Location": {"description": "The frontend URL.", "schema": {"type": "string"}}},
        },
        **problem_responses(400, 403, 502),
    },
)
async def discord_callback(
    code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    state: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth2 callback from Discord, then redirect to the frontend."""
    auth_service.check_state(state, request.cookies.get(OAUTH_STATE_COOKIE))
    user, session = await auth_service.login_with_discord(db, code)

    # Auto-link the user's driver via SimGrid discord_uid — after the
    # response, so a SimGrid hiccup never affects login.
    background_tasks.add_task(link_driver_for_user, user.id, user.discord_id)

    redirect = RedirectResponse(url=settings.frontend_url, status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    redirect.set_cookie(
        key=SESSION_COOKIE,
        value=str(session.id),
        httponly=True,
        secure=auth_service.frontend_is_secure(),
        samesite="lax",
        max_age=settings.session_max_age_hours * 3600,
        path="/",
    )
    return redirect


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """End the current session and clear the cookie."""
    await auth_service.end_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")

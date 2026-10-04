"""Discord OAuth2 login and token endpoints."""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AppError
from app.core.openapi import problem_responses
from app.database import get_db
from app.schemas.auth import AuthUrlOut, TokenCreate, TokenOut, TokenRevocationCreate
from app.services import auth as auth_service
from app.services import tokens
from app.services.drivers import link_driver_for_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

# The Discord redirect URI is registered as /api/auth/discord/callback and
# cannot be changed, so the callback keeps its pre-v1 path.
legacy_router = APIRouter(prefix="/auth/discord", tags=["Auth"])

OAUTH_STATE_COOKIE = "oauth_state"
# The frontend route that finishes the login.
FRONTEND_CALLBACK_PATH = "/auth/callback"


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


def _to_frontend(**fragment: str) -> RedirectResponse:
    """Send the browser to the frontend's callback page.

    The outcome travels in the URL fragment, which browsers never send to a
    server, so it stays out of access logs and ``Referer`` headers.
    """
    url = f"{settings.frontend_url.rstrip('/')}{FRONTEND_CALLBACK_PATH}#{urlencode(fragment)}"
    redirect = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    return redirect


@legacy_router.get(
    "/callback",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    responses={
        302: {
            "description": (
                "Redirects to the frontend's `/auth/callback`. The URL fragment carries "
                "`token` (a refresh token to exchange at `POST /api/v1/auth/tokens`) or, "
                "when the login failed, `error` (a problem `code`)."
            ),
            "headers": {"Location": {"description": "The frontend URL.", "schema": {"type": "string"}}},
        },
    },
)
async def discord_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    code: str | None = None,
    state: str = "",
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth2 callback from Discord, then redirect to the frontend."""
    if error or not code:
        # The user declined on Discord's consent screen.
        return _to_frontend(error="access_denied")
    try:
        auth_service.check_state(state, request.cookies.get(OAUTH_STATE_COOKIE))
        user, refresh_token = await auth_service.login_with_discord(db, code)
    except AppError as exc:
        logger.warning("Discord login failed: %s", exc.detail)
        return _to_frontend(error=exc.code)

    # Auto-link the user's driver via SimGrid discord_uid — after the
    # response, so a SimGrid hiccup never affects login.
    background_tasks.add_task(link_driver_for_user, user.id, user.discord_id)

    return _to_frontend(token=refresh_token)


@router.post(
    "/tokens",
    response_model=TokenOut,
    status_code=status.HTTP_200_OK,
    responses=problem_responses(401, 503),
)
async def create_tokens(body: TokenCreate, response: Response, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for an access token and the next refresh token.

    A refresh token works once. Presenting one that was already replaced ends
    the login it belongs to.
    """
    response.headers["Cache-Control"] = "no-store"
    pair = await tokens.refresh(db, body.refresh_token)
    return TokenOut(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post("/token-revocations", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_tokens(body: TokenRevocationCreate, db: AsyncSession = Depends(get_db)):
    """Sign out: end the login the refresh token belongs to."""
    await tokens.revoke(db, body.refresh_token)

"""Authentication dependencies."""

from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import Forbidden, ServiceUnavailable, Unauthorized
from app.database import get_db
from app.models.user import ROLE_ADMIN, ROLE_COMMUNITY_MANAGER, ROLE_JUDGE, ROLE_SUPER_ADMIN, User
from app.services import tokens

# Declared only so OpenAPI lists the schemes and marks the operations that
# need them; the values are still read and checked by the functions below.
_access_bearer = HTTPBearer(
    scheme_name="bearerAuth",
    bearerFormat="JWT",
    description="Access token from `POST /api/v1/auth/tokens`.",
    auto_error=False,
)
_ingest_bearer = HTTPBearer(
    scheme_name="ingestToken",
    description="Shared token of the external incident parsers.",
    auto_error=False,
)


def _bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return token if scheme.lower() == "bearer" and token else None


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the authenticated user, or ``None`` for an anonymous request.

    A request that *does* present a token must present a good one: an expired
    or revoked token is a 401 even where anonymous access is allowed, so the
    client refreshes instead of silently being served the public view.
    """
    token = _bearer_token(request)
    if token is None:
        return None

    invalid = Unauthorized("The access token is not valid.", code="invalid_token")
    claims = tokens.read_access_token(token)
    if claims is None:
        raise invalid
    # User.role is joined, so this is the only statement.
    user = await db.get(User, claims.user_id)
    if user is None or user.blocked:
        raise invalid
    if user.tokens_revoked_at and claims.issued_at <= tokens.as_utc(user.tokens_revoked_at):
        raise invalid
    return user


async def get_current_user(
    user: User | None = Depends(get_current_user_optional),
    _: HTTPAuthorizationCredentials | None = Depends(_access_bearer),
) -> User:
    """Return the authenticated user or raise 401."""
    if user is None:
        raise Unauthorized("Not authenticated.")
    return user


def is_admin(user: User | None) -> bool:
    """True when *user* is an admin or super-admin (handles ``None``)."""
    if user is None or user.role is None:
        return False
    return user.role.name in (ROLE_ADMIN, ROLE_SUPER_ADMIN)


def ensure_admin(user: User | None) -> None:
    """Guard the admin-only variant of a route that is otherwise public (``?include=...``)."""
    if user is None:
        raise Unauthorized("Not authenticated.")
    if not is_admin(user):
        raise Forbidden("Insufficient permissions.")


def require_role(*roles: str) -> Callable:
    """Return a FastAPI dependency that checks the user's role."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role.name not in roles:
            raise Forbidden("Insufficient permissions.")
        return user

    # Read by app.core.openapi to document who may call the operation.
    _check.required_roles = roles  # type: ignore[attr-defined]
    return _check


require_admin = require_role(ROLE_ADMIN, ROLE_SUPER_ADMIN)
require_admin_or_community_manager = require_role(ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_COMMUNITY_MANAGER)
# Roles that may judge incidents and see what only judges see.
JUDGE_ROLES = (ROLE_JUDGE, ROLE_ADMIN, ROLE_SUPER_ADMIN)

require_judge = require_role(*JUDGE_ROLES)


async def require_api_token(
    request: Request,
    _: HTTPAuthorizationCredentials | None = Depends(_ingest_bearer),
) -> None:
    """Validate ``Authorization: Bearer <token>`` against the configured incident API token."""
    token = settings.incident_api_token
    if not token:
        raise ServiceUnavailable("Incident API token not configured.")
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise Unauthorized("Missing bearer token.")
    if not secrets.compare_digest(auth_header[7:].encode(), token.encode()):
        raise Forbidden("Invalid API token.")

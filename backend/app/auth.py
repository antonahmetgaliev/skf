"""Authentication dependencies."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, Request
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.errors import Forbidden, ServiceUnavailable, Unauthorized
from app.database import get_db
from app.models.user import (
    ROLE_ADMIN,
    ROLE_COMMUNITY_MANAGER,
    ROLE_JUDGE,
    ROLE_MODERATOR,
    ROLE_SUPER_ADMIN,
    Session,
    User,
)

SESSION_COOKIE = "session_id"

# Declared only so OpenAPI lists the schemes and marks the operations that
# need them; the values are still read and checked by the functions below.
_session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="sessionCookie",
    description="Session id, set as a cookie by the Discord login.",
    auto_error=False,
)
_ingest_bearer = HTTPBearer(
    scheme_name="ingestToken",
    description="Shared token of the external incident parsers.",
    auto_error=False,
)


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the authenticated user or ``None``."""
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        session_id = uuid.UUID(raw)
    except ValueError:
        return None

    result = await db.execute(
        select(Session)
        .options(
            selectinload(Session.user).joinedload(User.role),
        )
        .where(
            Session.id == session_id,
            Session.expires_at > datetime.now(UTC),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    user = session.user
    if user.blocked:
        return None
    # Ensure role is loaded (joined eager load on User.role)
    return user


async def get_current_user(
    user: User | None = Depends(get_current_user_optional),
    _: str | None = Depends(_session_cookie),
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

require_moderator = require_role(ROLE_MODERATOR, ROLE_ADMIN, ROLE_SUPER_ADMIN)
require_judge = require_role(*JUDGE_ROLES)


async def check_community_access(user: User, community_id: uuid.UUID, db: AsyncSession) -> None:
    """Raise 403 if user is a community manager without access to this community."""
    if user.role.name in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return
    if user.role.name == ROLE_COMMUNITY_MANAGER:
        from app.models.community_manager import CommunityManager

        result = await db.execute(
            select(CommunityManager).where(
                CommunityManager.user_id == user.id,
                CommunityManager.community_id == community_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            return
    raise Forbidden("No access to this community.")


async def get_managed_community_ids(user: User, db: AsyncSession) -> list[uuid.UUID]:
    """Return community IDs that a community manager is assigned to."""
    from app.models.community_manager import CommunityManager

    result = await db.execute(
        select(CommunityManager.community_id).where(CommunityManager.user_id == user.id)
    )
    return list(result.scalars().all())


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

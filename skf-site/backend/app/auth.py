"""Authentication dependencies."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.database import get_db
from app.models.user import Session, User, ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_COMMUNITY_MANAGER

SESSION_COOKIE = "session_id"


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
            Session.expires_at > datetime.now(timezone.utc),
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
) -> User:
    """Return the authenticated user or raise 401."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    return user


def is_admin(user: User | None) -> bool:
    """True when *user* is an admin or super-admin (handles ``None``)."""
    if user is None or user.role is None:
        return False
    return user.role.name in (ROLE_ADMIN, ROLE_SUPER_ADMIN)


def require_role(*roles: str) -> Callable:
    """Return a FastAPI dependency that checks the user's role."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role.name not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return user

    return _check


require_admin = require_role(ROLE_ADMIN, ROLE_SUPER_ADMIN)
require_admin_or_community_manager = require_role(ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_COMMUNITY_MANAGER)
require_moderator = require_role("moderator", ROLE_ADMIN, ROLE_SUPER_ADMIN)
require_judge = require_role("racing_judge", ROLE_ADMIN, ROLE_SUPER_ADMIN)


async def check_community_access(
    user: User, community_id: uuid.UUID, db: AsyncSession
) -> None:
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
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No access to this community.",
    )


async def get_managed_community_ids(
    user: User, db: AsyncSession
) -> list[uuid.UUID]:
    """Return community IDs that a community manager is assigned to."""
    from app.models.community_manager import CommunityManager

    result = await db.execute(
        select(CommunityManager.community_id).where(
            CommunityManager.user_id == user.id
        )
    )
    return list(result.scalars().all())


async def require_api_token(request: Request) -> None:
    """Validate ``Authorization: Bearer <token>`` against the configured incident API token."""
    settings = Settings()  # type: ignore[call-arg]
    token = settings.incident_api_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Incident API token not configured.",
        )
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    if auth_header[7:] != token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API token.",
        )

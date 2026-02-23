"""Authentication dependencies."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.database import get_db
from app.models.user import Session, User, ROLE_SUPER_ADMIN

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


require_admin = require_role("admin", "super_admin")

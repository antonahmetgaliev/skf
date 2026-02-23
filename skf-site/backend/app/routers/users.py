"""User management endpoints (admin only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin, require_role
from app.database import get_db
from app.models.user import Session, User, UserRole
from app.schemas.auth import UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=list[UserOut])
async def list_users(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.username))
    users = result.scalars().all()
    return [
        UserOut(
            id=u.id,
            discord_id=u.discord_id,
            username=u.username,
            display_name=u.display_name,
            avatar_url=u.avatar_url,
            role=u.role.value,
            blocked=u.blocked,
            created_at=u.created_at,
            last_login_at=u.last_login_at,
        )
        for u in users
    ]


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    # Super-admin protections
    if target.role == UserRole.super_admin and admin.role != UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a super-admin can modify another super-admin.",
        )

    if body.role is not None:
        try:
            new_role = UserRole(body.role)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid role: {body.role}",
            )
        # Only super-admin can grant or revoke super_admin
        if (
            new_role == UserRole.super_admin or target.role == UserRole.super_admin
        ) and admin.role != UserRole.super_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only a super-admin can grant or revoke the super-admin role.",
            )
        target.role = new_role

    if body.blocked is not None:
        if target.role == UserRole.super_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot block a super-admin.",
            )
        target.blocked = body.blocked

    await db.commit()
    await db.refresh(target)

    return UserOut(
        id=target.id,
        discord_id=target.discord_id,
        username=target.username,
        display_name=target.display_name,
        avatar_url=target.avatar_url,
        role=target.role.value,
        blocked=target.blocked,
        created_at=target.created_at,
        last_login_at=target.last_login_at,
    )


@router.delete(
    "/{user_id}/sessions", status_code=status.HTTP_204_NO_CONTENT
)
async def force_logout(
    user_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete all sessions for a user (force logout)."""
    result = await db.execute(select(User).where(User.id == user_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found.")
    await db.execute(delete(Session).where(Session.user_id == user_id))
    await db.commit()

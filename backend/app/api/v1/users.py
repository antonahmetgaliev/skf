"""User management (admin only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.core.pagination import PageParams, page_params, paginate
from app.database import get_db
from app.models.user import User
from app.schemas.auth import ManagedCommunitiesOut, ManagedCommunitiesUpdate, UserOut, UserUpdate
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["Users"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[UserOut])
async def list_users(
    request: Request,
    response: Response,
    page: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
):
    users = await paginate(db, users_service.list_users_stmt(), page, request, response)
    return await users_service.build_user_outs(users, db)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    target = await users_service.update_user(db, admin, user_id, body)
    return await users_service.build_user_out(target, db)


@router.delete("/{user_id}/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_user_sessions(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete all sessions of a user (force logout)."""
    await users_service.revoke_sessions(db, user_id)


@router.get("/{user_id}/managed-communities", response_model=ManagedCommunitiesOut)
async def get_user_managed_communities(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ids = await users_service.get_managed_communities(db, user_id)
    return ManagedCommunitiesOut(community_ids=ids)


@router.put("/{user_id}/managed-communities", response_model=ManagedCommunitiesOut)
async def set_user_managed_communities(
    user_id: uuid.UUID,
    body: ManagedCommunitiesUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Replace the full set of communities the user manages."""
    ids = await users_service.set_managed_communities(db, user_id, body.community_ids)
    return ManagedCommunitiesOut(community_ids=ids)

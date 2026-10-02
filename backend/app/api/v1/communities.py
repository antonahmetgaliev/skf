"""Calendar communities and requests to add a new one."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    get_current_user,
    get_current_user_optional,
    require_admin,
    require_admin_or_community_manager,
)
from app.core.errors import Unauthorized
from app.core.openapi import problem_responses
from app.database import get_db
from app.models.user import User
from app.schemas.calendar import (
    CommunityCreate,
    CommunityOut,
    CommunityRequestCreate,
    CommunityUpdate,
)
from app.services import communities as service

router = APIRouter(tags=["Communities"])


@router.get("/communities", response_model=list[CommunityOut], responses=problem_responses(401, 403))
async def list_communities(
    scope: Literal["managed"] | None = Query(None),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Visible communities (SKF first).

    ``?scope=managed`` lists the communities the caller manages, hidden ones
    included: all of them for admins, assigned ones for community managers.
    """
    if scope == "managed":
        if user is None:
            raise Unauthorized("Not authenticated.")
        return await service.list_managed(db, user)
    return await service.list_visible(db)


@router.post("/communities", response_model=CommunityOut, status_code=status.HTTP_201_CREATED)
async def create_community(
    body: CommunityCreate,
    response: Response,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    community = await service.create(db, body)
    response.headers["Location"] = f"/api/v1/communities/{community.id}"
    return community


@router.patch("/communities/{community_id}", response_model=CommunityOut)
async def update_community(
    community_id: uuid.UUID,
    body: CommunityUpdate,
    user: User = Depends(require_admin_or_community_manager),
    db: AsyncSession = Depends(get_db),
):
    return await service.update(db, user, community_id, body)


@router.delete(
    "/communities/{community_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problem_responses(400),
)
async def delete_community(
    community_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await service.delete(db, community_id)


@router.post(
    "/community-requests",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problem_responses(429, 502, 503),
)
async def create_community_request(
    body: CommunityRequestCreate,
    user: User = Depends(get_current_user),
):
    """Forward a logged-in user's community request to the SKF Discord."""
    await service.submit_request(body, user)

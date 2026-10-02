"""Driver-name aliases: merge one imported spelling into another identity."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.core.pagination import PageParams, page_params, paginate
from app.database import get_db
from app.models.race_result import GiveawayNameAlias
from app.models.user import User
from app.repository import get_or_404
from app.schemas.giveaway import AliasCreate, AliasOut
from app.services import giveaway as service

router = APIRouter(prefix="/driver-aliases", tags=["Giveaway"])

_NOT_FOUND = "Alias not found"


@router.get("", response_model=list[AliasOut])
async def list_driver_aliases(
    request: Request,
    response: Response,
    page: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    return await paginate(db, service.aliases_query(), page, request, response)


@router.get("/{alias_id}", response_model=AliasOut)
async def get_driver_alias(
    alias_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    return await get_or_404(db, GiveawayNameAlias, alias_id, detail=_NOT_FOUND)


@router.post(
    "",
    response_model=AliasOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": AliasOut, "description": "An existing alias was updated"}},
)
async def upsert_driver_alias(
    payload: AliasCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Upsert keyed by the normalized alias: 201 when created, 200 when updated."""
    record, created = await service.upsert_alias(db, payload)
    if created:
        response.headers["Location"] = f"/api/v1/driver-aliases/{record.id}"
    else:
        response.status_code = status.HTTP_200_OK
    return record


@router.delete("/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_driver_alias(
    alias_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    record = await get_or_404(db, GiveawayNameAlias, alias_id, detail=_NOT_FOUND)
    await service.delete_alias(db, record)

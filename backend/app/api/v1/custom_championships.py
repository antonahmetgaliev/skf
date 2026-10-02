"""Custom championships (calendar events not on SimGrid) and their races."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin_or_community_manager
from app.core.pagination import PageParams, page_params, paginate
from app.database import get_db
from app.models.custom_championship import CustomChampionship
from app.models.user import User
from app.schemas.calendar import (
    CustomChampionshipCreate,
    CustomChampionshipOut,
    CustomChampionshipUpdate,
    CustomRaceCreate,
    CustomRaceOut,
    CustomRaceSync,
    CustomRaceUpdate,
)
from app.services import custom_championships as service

router = APIRouter(prefix="/custom-championships", tags=["Custom championships"])


async def get_accessible_custom_championship(
    champ_id: uuid.UUID,
    user: User = Depends(require_admin_or_community_manager),
    db: AsyncSession = Depends(get_db),
) -> CustomChampionship:
    """The championship at ``{champ_id}``, if the caller may manage it (else 403/404)."""
    return await service.get_accessible(db, user, champ_id)


def _location(*parts: object) -> str:
    return "/api/v1/custom-championships/" + "/".join(str(p) for p in parts)


@router.get("", response_model=list[CustomChampionshipOut])
async def list_custom_championships(
    request: Request,
    response: Response,
    community_id: uuid.UUID | None = Query(None, alias="communityId"),
    page: PageParams = Depends(page_params),
    user: User = Depends(require_admin_or_community_manager),
    db: AsyncSession = Depends(get_db),
):
    stmt = await service.list_stmt(db, user, community_id)
    return [service.to_out(c) for c in await paginate(db, stmt, page, request, response)]


@router.post("", response_model=CustomChampionshipOut, status_code=status.HTTP_201_CREATED)
async def create_custom_championship(
    body: CustomChampionshipCreate,
    response: Response,
    user: User = Depends(require_admin_or_community_manager),
    db: AsyncSession = Depends(get_db),
):
    champ = await service.create(db, user, body)
    response.headers["Location"] = _location(champ.id)
    return service.to_out(champ)


@router.get("/{champ_id}", response_model=CustomChampionshipOut)
async def get_custom_championship(
    champ: CustomChampionship = Depends(get_accessible_custom_championship),
):
    return service.to_out(champ)


@router.patch("/{champ_id}", response_model=CustomChampionshipOut)
async def update_custom_championship(
    body: CustomChampionshipUpdate,
    champ: CustomChampionship = Depends(get_accessible_custom_championship),
    user: User = Depends(require_admin_or_community_manager),
    db: AsyncSession = Depends(get_db),
):
    return service.to_out(await service.update(db, user, champ, body))


@router.delete("/{champ_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_championship(
    champ: CustomChampionship = Depends(get_accessible_custom_championship),
    db: AsyncSession = Depends(get_db),
):
    await service.delete(db, champ)


# ── Races ────────────────────────────────────────────────────────────────────


@router.post("/{champ_id}/races", response_model=CustomRaceOut, status_code=status.HTTP_201_CREATED)
async def create_custom_race(
    body: CustomRaceCreate,
    response: Response,
    champ: CustomChampionship = Depends(get_accessible_custom_championship),
    db: AsyncSession = Depends(get_db),
):
    race = await service.add_race(db, champ, body)
    response.headers["Location"] = _location(champ.id, "races", race.id)
    return race


@router.put("/{champ_id}/races", response_model=list[CustomRaceOut])
async def replace_custom_races(
    body: list[CustomRaceSync],
    champ: CustomChampionship = Depends(get_accessible_custom_championship),
    db: AsyncSession = Depends(get_db),
):
    """Replace the full race list in one request."""
    return await service.replace_races(db, champ, body)


@router.get("/{champ_id}/races/{race_id}", response_model=CustomRaceOut)
async def get_custom_race(
    race_id: uuid.UUID,
    champ: CustomChampionship = Depends(get_accessible_custom_championship),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_race(db, champ, race_id)


@router.patch("/{champ_id}/races/{race_id}", response_model=CustomRaceOut)
async def update_custom_race(
    race_id: uuid.UUID,
    body: CustomRaceUpdate,
    champ: CustomChampionship = Depends(get_accessible_custom_championship),
    db: AsyncSession = Depends(get_db),
):
    return await service.update_race(db, champ, race_id, body)


@router.delete("/{champ_id}/races/{race_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_race(
    race_id: uuid.UUID,
    champ: CustomChampionship = Depends(get_accessible_custom_championship),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_race(db, champ, race_id)

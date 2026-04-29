"""Championship standings proxy – calls SimGrid API server-side."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_optional, is_admin, require_admin
from app.database import get_db
from app.models.active_championship import ActiveChampionship
from app.models.user import User
from app.schemas.championship import (
    ChampionshipDetails,
    ChampionshipListItem,
    ChampionshipPodium,
    ChampionshipRace,
    ChampionshipStandingsData,
    DriverChampionshipResult,
)
from app.services.drivers import sync_drivers_from_standings
from app.services.simgrid import simgrid_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/championships", tags=["Championships"])


# ------------------------------------------------------------------
# Active championships management (admin only)
# ------------------------------------------------------------------

@router.get("/active", response_model=list[int])
async def list_active(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ActiveChampionship.simgrid_id))
    return list(result.scalars().all())


@router.put("/active/{simgrid_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_active(
    simgrid_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    existing = await db.get(ActiveChampionship, simgrid_id)
    if not existing:
        db.add(ActiveChampionship(simgrid_id=simgrid_id))
        await db.commit()


@router.delete("/active/{simgrid_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_active(
    simgrid_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    await db.execute(
        delete(ActiveChampionship).where(ActiveChampionship.simgrid_id == simgrid_id)
    )
    await db.commit()


# ------------------------------------------------------------------
# Championship list
# ------------------------------------------------------------------

@router.get("", response_model=list[ChampionshipListItem])
async def list_championships(
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    try:
        items = await simgrid_service.get_championships()
    except Exception:
        logger.warning("Failed to fetch championships from SimGrid", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch championships from SimGrid.",
        )

    db_result = await db.execute(select(ActiveChampionship.simgrid_id))
    active_ids = set(db_result.scalars().all())

    # Admins see all championships; regular users only see active ones
    if is_admin(user):
        return [
            item if item.id in active_ids
            else item.model_copy(update={"event_completed": True})
            for item in items
        ]
    return [item for item in items if item.id in active_ids]


@router.get("/podium", response_model=list[ChampionshipPodium])
async def get_champions_podium(db: AsyncSession = Depends(get_db)):
    """Return top-3 finishers for each completed championship."""
    active_result = await db.execute(select(ActiveChampionship.simgrid_id))
    active_ids = set(active_result.scalars().all())
    return await simgrid_service.build_champions_podiums(active_ids)


@router.get("/driver/{simgrid_driver_id}/results", response_model=list[DriverChampionshipResult])
async def get_driver_championship_results(simgrid_driver_id: int):
    """Return all cached championship results for a specific SimGrid driver ID."""
    return await simgrid_service.find_driver_championship_results(simgrid_driver_id)


@router.get("/{championship_id}/races", response_model=list[ChampionshipRace])
async def get_races(championship_id: int):
    """Return all races for a championship (including future ones)."""
    try:
        items = await simgrid_service.get_races(championship_id)
        races = [ChampionshipRace(**r) for r in items]
        races.sort(key=lambda r: r.starts_at or "")
        return races
    except Exception:
        logger.warning("Failed to fetch races for championship %s", championship_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch races from SimGrid.",
        )


@router.get("/{championship_id}", response_model=ChampionshipDetails)
async def get_championship(championship_id: int):
    try:
        return await simgrid_service.get_championship(championship_id)
    except Exception:
        logger.warning("Failed to fetch championship %s", championship_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch championship from SimGrid.",
        )


@router.get(
    "/{championship_id}/standings", response_model=ChampionshipStandingsData
)
async def get_standings(
    championship_id: int,
    background_tasks: BackgroundTasks,
):
    try:
        data = await simgrid_service.get_standings(championship_id)
        background_tasks.add_task(sync_drivers_from_standings, data.entries)
        return data
    except Exception:
        logger.warning("Failed to fetch standings for championship %s", championship_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch standings from SimGrid.",
        )

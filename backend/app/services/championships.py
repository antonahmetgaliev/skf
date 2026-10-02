"""SimGrid championship proxy, active-championship flags and incident windows.

SimGrid failures surface as :class:`BadGateway`; the SimGrid client itself
already falls back to stale cache where it can.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadGateway
from app.models.active_championship import ActiveChampionship
from app.models.incidents import Incident, IncidentWindow
from app.schemas.championship import (
    ChampionshipDetails,
    ChampionshipListItem,
    ChampionshipRace,
    ChampionshipStandingsData,
)
from app.schemas.incidents import IncidentWindowSummaryOut
from app.services.incidents import window_summary
from app.services.simgrid import simgrid_service

logger = logging.getLogger(__name__)


# ── Active championships ────────────────────────────────────────────────────


async def active_ids(db: AsyncSession) -> list[int]:
    result = await db.execute(select(ActiveChampionship.simgrid_id).order_by(ActiveChampionship.simgrid_id))
    return list(result.scalars().all())


async def set_active(db: AsyncSession, simgrid_id: int, active: bool) -> None:
    """Show or hide a championship. Idempotent; the id is not checked against SimGrid."""
    if not active:
        await db.execute(delete(ActiveChampionship).where(ActiveChampionship.simgrid_id == simgrid_id))
    elif await db.get(ActiveChampionship, simgrid_id) is None:
        db.add(ActiveChampionship(simgrid_id=simgrid_id))
    await db.commit()


# ── SimGrid proxy ───────────────────────────────────────────────────────────


async def list_championships(db: AsyncSession, *, include_inactive: bool) -> list[ChampionshipListItem]:
    """Active championships with their details; with *include_inactive* also the rest, as SimGrid lists them."""
    try:
        items = await simgrid_service.get_championships()
    except Exception as exc:
        logger.warning("Failed to fetch championships from SimGrid", exc_info=True)
        raise BadGateway("Failed to fetch championships from SimGrid.") from exc

    active = set(await active_ids(db))
    enriched = {
        item.id: item.model_copy(update={"is_active": True})
        for item in await simgrid_service.with_details([i for i in items if i.id in active])
    }
    return [enriched.get(item.id, item) for item in items if item.id in active or include_inactive]


async def get_championship(championship_id: int) -> ChampionshipDetails:
    try:
        return await simgrid_service.get_championship(championship_id)
    except Exception as exc:
        logger.warning("Failed to fetch championship %s", championship_id, exc_info=True)
        raise BadGateway("Failed to fetch championship from SimGrid.") from exc


async def get_races(championship_id: int) -> list[ChampionshipRace]:
    """All races of a championship (including future ones), by start time."""
    try:
        items = await simgrid_service.get_races(championship_id)
        races = [ChampionshipRace(**r) for r in items]
    except Exception as exc:
        logger.warning("Failed to fetch races for championship %s", championship_id, exc_info=True)
        raise BadGateway("Failed to fetch races from SimGrid.") from exc
    races.sort(key=lambda r: r.starts_at or "")
    return races


async def get_standings(championship_id: int) -> tuple[ChampionshipStandingsData, bool]:
    """Standings plus whether SimGrid was actually hit (not cache)."""
    try:
        return await simgrid_service.get_standings(championship_id)
    except Exception as exc:
        logger.warning("Failed to fetch standings for championship %s", championship_id, exc_info=True)
        raise BadGateway("Failed to fetch standings from SimGrid.") from exc


# ── Incident windows ────────────────────────────────────────────────────────


async def incident_windows(db: AsyncSession, championship_id: int) -> list[IncidentWindowSummaryOut]:
    """The championship's incident windows, one per round, keyed by race."""
    rows = await db.execute(
        select(IncidentWindow, func.count(Incident.id))
        .outerjoin(Incident, Incident.window_id == IncidentWindow.id)
        .where(
            IncidentWindow.championship_id == championship_id,
            IncidentWindow.race_id.is_not(None),
        )
        .group_by(IncidentWindow.id)
    )
    return [window_summary(window, count) for window, count in rows.all()]

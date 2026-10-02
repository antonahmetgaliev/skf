"""SimGrid championships (server-side proxy) and per-championship admin views."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.params import ChampionshipId, RaceId
from app.auth import ensure_admin, get_current_user_optional, require_admin
from app.core.openapi import NO_404, SIMGRID_RESPONSES, problem_responses
from app.database import get_db
from app.models.user import User
from app.schemas.championship import (
    ChampionshipOut,
    ChampionshipRaceOut,
    ChampionshipStandingsOut,
    ChampionshipSummaryOut,
    ChampionshipUpdate,
    RaceSessionOut,
)
from app.schemas.enums import RaceSessionKind
from app.schemas.giveaway import GiveawayEligibilityOut, UnmatchedDriverNameOut
from app.schemas.incidents import IncidentWindowStatusOut
from app.schemas.race_results import RoundsOut
from app.services import championship_results, giveaway, race_import
from app.services import championships as service
from app.services.drivers import sync_drivers_from_standings

router = APIRouter(prefix="/championships", tags=["Championships"])


@router.get(
    "",
    response_model=list[ChampionshipSummaryOut],
    responses={**SIMGRID_RESPONSES, **problem_responses(401, 403)},
)
async def list_championships(
    include: Literal["inactive"] | None = Query(
        None, description="`inactive` adds the championships hidden from the site; admins only."
    ),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """The championships shown on the site, in SimGrid's order."""
    if include is not None:
        ensure_admin(user)
    return await service.list_championships(db, include_inactive=include is not None)


@router.patch(
    "/{championshipId}",
    status_code=status.HTTP_204_NO_CONTENT,
    openapi_extra=NO_404,
)
async def update_championship(
    championship_id: ChampionshipId,
    body: ChampionshipUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Show or hide the championship on the site. Everything else about it lives in SimGrid."""
    await service.set_active(db, championship_id, body.is_active)


@router.get(
    "/{championshipId}",
    response_model=ChampionshipOut,
    responses=SIMGRID_RESPONSES,
    openapi_extra=NO_404,
)
async def get_championship(championship_id: ChampionshipId):
    return await service.get_championship(championship_id)


@router.get(
    "/{championshipId}/standings",
    response_model=ChampionshipStandingsOut,
    responses=SIMGRID_RESPONSES,
    openapi_extra=NO_404,
)
async def get_championship_standings(championship_id: ChampionshipId, background_tasks: BackgroundTasks):
    data, fetched_live = await service.get_standings(championship_id)
    # Only sync when SimGrid was actually hit — cache hits and stale
    # fallbacks cannot contain anything new.
    if fetched_live:
        background_tasks.add_task(sync_drivers_from_standings, data.entries, championship_id)
    return await championship_results.with_round_results(championship_id, data)


@router.get(
    "/{championshipId}/races",
    response_model=list[ChampionshipRaceOut],
    responses=SIMGRID_RESPONSES,
    openapi_extra=NO_404,
)
async def list_championship_races(championship_id: ChampionshipId):
    """All races of the championship, including future ones."""
    return await service.get_races(championship_id)


@router.get(
    "/{championshipId}/races/{raceId}/results",
    response_model=RaceSessionOut,
    responses=SIMGRID_RESPONSES,
    openapi_extra=NO_404,
)
async def get_race_results(
    championship_id: ChampionshipId,
    race_id: RaceId,
    session: RaceSessionKind = RaceSessionKind.RACE,
):
    """One race's classification (race or qualifying), ordered by class."""
    return await championship_results.race_session(championship_id, race_id, session)


@router.get(
    "/{championshipId}/incident-windows",
    response_model=list[IncidentWindowStatusOut],
    openapi_extra=NO_404,
)
async def list_championship_incident_windows(
    championship_id: ChampionshipId, db: AsyncSession = Depends(get_db)
):
    """The championship's incident windows, one per round, keyed by race."""
    return await service.incident_windows(db, championship_id)


@router.get(
    "/{championshipId}/rounds",
    response_model=RoundsOut,
    responses=SIMGRID_RESPONSES,
    openapi_extra=NO_404,
)
async def get_championship_rounds(
    championship_id: ChampionshipId,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """The championship's rounds with their result upload and incident window."""
    return await race_import.build_rounds(db, championship_id)


@router.get(
    "/{championshipId}/giveaway-eligibility",
    response_model=GiveawayEligibilityOut,
    tags=["Giveaway"],
    openapi_extra=NO_404,
)
async def get_giveaway_eligibility(
    championship_id: ChampionshipId,
    min_distance_pct: float = Query(50.0, alias="minDistancePct", ge=0, le=100),
    min_rounds: int = Query(3, alias="minRounds", ge=1),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Drivers who cleared the distance bar in enough rounds, grouped by class."""
    return await giveaway.eligibility(db, championship_id, min_distance_pct, min_rounds)


@router.get(
    "/{championshipId}/unmatched-driver-names",
    response_model=list[UnmatchedDriverNameOut],
    tags=["Giveaway"],
    openapi_extra=NO_404,
)
async def get_unmatched_driver_names(
    championship_id: ChampionshipId,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Imported names with no driver record, plus ranked spelling hints."""
    return await giveaway.unmatched_names(db, championship_id)

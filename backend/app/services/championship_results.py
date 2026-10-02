"""Per-race results from SimGrid ``session_results``.

Serves one session's classification (race or qualifying) and fills the
per-round columns of the standings. ``position_cache`` is the position within
the car class; the overall position and grid slot exist only for LMU
(``external_data.rfactor``).
"""

from __future__ import annotations

import asyncio
import logging

from app.core.errors import BadGateway, NotFound
from app.schemas.championship import (
    ChampionshipStandingsData,
    DriverRaceResult,
    RaceResultEntry,
    RaceSessionOut,
    RaceStatus,
)
from app.schemas.simgrid_raw import RawSessionResult
from app.services.simgrid import simgrid_service

logger = logging.getLogger(__name__)

SIMGRID_SESSIONS = {"race": "race_1", "qualifying": "qualifying"}


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _status(r: RawSessionResult) -> RaceStatus:
    if r.dns:
        return "dns"
    rf = r.external_data.rfactor if r.external_data else None
    status = (rf.status or "").upper() if rf else ""
    if status in ("DQ", "DSQ", "DISQUALIFIED"):
        return "dq"
    if status == "DNF" or r.dnf:
        return "dnf"
    return "classified"


def map_session(results: list[RawSessionResult], session: str = "race") -> list[RaceResultEntry]:
    """Map raw results, ordered by class then class position.

    Race positions are SimGrid's (they include stewards' penalties).
    Qualifying is re-ranked by best lap: SimGrid can put a driver without a
    timed lap on pole.
    """
    entries: list[RaceResultEntry] = []
    for r in results:
        rf = r.external_data.rfactor if r.external_data else None
        entrant = r.sessionable
        cc = entrant.championship_car_class if entrant else None
        entries.append(
            RaceResultEntry(
                user_id=entrant.user_id if entrant else None,
                display_name=r.sessionable_name or r.imported_name or "",
                car=r.car_name or "",
                car_number=r.car_number,
                car_class=(cc.display_name if cc else None) or "",
                position=_int(rf.finished) if rf else None,
                class_position=r.position_cache,
                start_position=_int(rf.class_st) if rf else None,
                laps=r.lap_count,
                best_lap_ms=r.best_lap or None,
                total_time_ms=r.total_time or None,
                penalty_s=r.total_time_penalty or 0,
                points=r.points_total,
                status=_status(r),
                rating_change=r.grid_rating_change,
            )
        )

    entries.sort(
        key=lambda e: (
            e.car_class,
            e.class_position if e.class_position is not None else float("inf"),
        )
    )

    by_class: dict[str, list[RaceResultEntry]] = {}
    for e in entries:
        by_class.setdefault(e.car_class, []).append(e)
    if session == "qualifying":
        for group in by_class.values():
            group.sort(key=lambda e: (e.best_lap_ms is None, e.best_lap_ms or 0))
            for rank, e in enumerate(group, start=1):
                e.class_position = rank
        entries = [e for group in by_class.values() for e in group]
    for group in by_class.values():
        best = min((e.best_lap_ms for e in group if e.best_lap_ms), default=None)
        leader = next((e for e in group if e.status != "dns" and e.laps), None)
        for e in group:
            e.is_class_best_lap = best is not None and e.best_lap_ms == best
            if leader is None or e is leader or e.status == "dns" or e.laps is None:
                continue
            e.laps_down = max(0, (leader.laps or 0) - e.laps)
            if e.laps_down == 0 and e.total_time_ms and leader.total_time_ms:
                e.gap_ms = e.total_time_ms - leader.total_time_ms
    return entries


async def _race_ids(championship_id: int) -> set[int]:
    try:
        races = await simgrid_service.get_races(championship_id)
    except Exception as exc:
        logger.warning("Failed to fetch races for championship %s", championship_id, exc_info=True)
        raise BadGateway("Failed to fetch races from SimGrid.") from exc
    return {r["id"] for r in races if isinstance(r, dict) and isinstance(r.get("id"), int)}


async def race_session(championship_id: int, race_id: int, session: str) -> RaceSessionOut:
    """One session's classification for a race of the championship."""
    if race_id not in await _race_ids(championship_id):
        raise NotFound("Race not found in this championship.")
    try:
        raw = await simgrid_service.get_session_results(
            championship_id,
            race_id,
            SIMGRID_SESSIONS[session],
        )
    except Exception as exc:
        logger.warning("Failed to fetch %s results for race %s", session, race_id, exc_info=True)
        raise BadGateway("Failed to fetch race results from SimGrid.") from exc
    return RaceSessionOut(race_id=race_id, session=session, entries=map_session(raw, session))


async def with_round_results(
    championship_id: int,
    data: ChampionshipStandingsData,
) -> ChampionshipStandingsData:
    """Fill each standings entry's per-round results (race session only).

    A round that fails to load just stays empty; standings never fail on it.
    """
    rounds = [(i, r) for i, r in enumerate(data.races) if r.results_available]
    fetched = await asyncio.gather(
        *(simgrid_service.get_session_results(championship_id, r.id, "race_1") for _, r in rounds),
        return_exceptions=True,
    )

    by_user: dict[int, list[DriverRaceResult]] = {}
    for (index, race), raw in zip(rounds, fetched, strict=True):
        if isinstance(raw, BaseException):
            logger.warning("Failed to fetch results for race %s", race.id, exc_info=raw)
            continue
        for e in map_session(raw):
            if e.user_id is None:
                continue
            by_user.setdefault(e.user_id, []).append(
                DriverRaceResult(
                    race_id=race.id,
                    race_index=index,
                    points=e.points,
                    position=e.class_position,
                    status=e.status,
                )
            )

    entries = [
        e.model_copy(update={"race_results": by_user.get(e.id, [])}) if e.id is not None else e
        for e in data.entries
    ]
    return data.model_copy(update={"entries": entries})

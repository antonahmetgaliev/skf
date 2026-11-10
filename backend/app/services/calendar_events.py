"""Calendar: merge active SimGrid championships with custom championships.

Also serves the simulator and car-class catalogues the calendar filters use.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from time import monotonic
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.errors import Unprocessable
from app.models.active_championship import ActiveChampionship
from app.models.community import Community
from app.models.custom_championship import CustomChampionship
from app.schemas.calendar import CalendarEventOut, CalendarEventType, CalendarRaceOut, CommunityOut
from app.services.simgrid import simgrid_service

logger = logging.getLogger(__name__)

# Simulators SimGrid does not list but our custom championships use.
_EXTRA_SIMULATORS: set[str] = {
    "Richard Burns Rally",
}


# ── Catalogues ───────────────────────────────────────────────────────────────


async def list_simulators() -> list[str]:
    """Simulator/game names from SimGrid plus manually added extras."""
    try:
        games = await simgrid_service.get_games()
        names = {g["name"] for g in games if isinstance(g, dict) and g.get("name")}
    except Exception:
        logger.warning("Could not load simulators from SimGrid", exc_info=True)
        names = set()
    return sorted(names | _EXTRA_SIMULATORS)


async def list_car_classes(game_id: int | None) -> list[str]:
    """Car class names from SimGrid, optionally filtered by game."""
    try:
        classes = await simgrid_service.get_car_classes(game_id)
    except Exception:
        logger.warning("Could not load car classes from SimGrid", exc_info=True)
        return []
    return sorted(c["name"] for c in classes if isinstance(c, dict) and c.get("name") and c["name"] != "All")


# ── Date helpers ─────────────────────────────────────────────────────────────


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _classify_simgrid(
    start_date: str | None,
    end_date: str | None,
    event_completed: bool,
    accepting_registrations: bool,
) -> CalendarEventType:
    """Classify a SimGrid championship – uses full datetime for accuracy."""
    now = datetime.now(UTC)
    start = _parse_date(start_date)
    end = _parse_date(end_date)

    if start and start > now:
        return CalendarEventType.UPCOMING
    if event_completed:
        return CalendarEventType.PAST
    if end and end < now:
        return CalendarEventType.PAST
    if start and start <= now:
        return CalendarEventType.ONGOING
    if accepting_registrations:
        return CalendarEventType.ONGOING
    return CalendarEventType.UPCOMING


def _overlaps_range(
    start: datetime | None,
    end: datetime | None,
    races: list[CalendarRaceOut],
    range_start: datetime,
    range_end: datetime,
) -> bool:
    """Check if a championship or any of its races overlap with the range."""
    for race in races:
        if race.date:
            rd = _parse_date(race.date)
            red = _parse_date(race.end_date) if race.end_date else None
            if rd and red:
                if rd <= range_end and red >= range_start:
                    return True
            elif rd and range_start <= rd <= range_end:
                return True

    if start and end:
        return start <= range_end and end >= range_start
    if start:
        return range_start <= start <= range_end
    if end:
        return range_start <= end <= range_end
    return False


def _date_range(start: date, end: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(start, time.min, tzinfo=UTC),
        datetime.combine(end, time(23, 59, 59), tzinfo=UTC),
    )


# ── SimGrid ──────────────────────────────────────────────────────────────────


async def _fetch_races(cid: int) -> tuple[int, list[dict]]:
    try:
        return cid, await simgrid_service.get_races(cid)
    except Exception:
        logger.warning("Failed to fetch races for championship %s", cid, exc_info=True)
        return cid, []


async def _fetch_detail(cid: int) -> tuple[int, dict | None]:
    try:
        details = await simgrid_service.get_championship(cid)
        return cid, details.model_dump(by_alias=False)
    except Exception:
        logger.warning("Failed to fetch details for championship %s", cid, exc_info=True)
        return cid, None


def _simgrid_races(raw_races: list[dict]) -> list[CalendarRaceOut]:
    races: list[CalendarRaceOut] = []
    for r in raw_races:
        race_date = r.get("starts_at") or r.get("startsAt") or r.get("start_date") or r.get("startDate")
        track = r.get("track")
        track_name = None
        if isinstance(track, dict):
            track_name = track.get("name")
        elif isinstance(track, str):
            track_name = track
        races.append(
            CalendarRaceOut(
                date=race_date,
                track=track_name,
                name=r.get("display_name") or r.get("race_name") or r.get("displayName"),
            )
        )
    return races


@dataclass(frozen=True)
class _SimgridEntry:
    """A SimGrid championship as the calendar shows it, minus what depends on the request."""

    event: CalendarEventOut
    completed: bool


@dataclass(frozen=True)
class _Snapshot:
    built_at: datetime
    entries: list[_SimgridEntry]


# Building the SimGrid half costs three cache-table reads per active
# championship (or SimGrid calls on a miss), whatever range is asked for. It is
# built once, kept in memory and rebuilt in the background when it gets old, so
# a request never waits for it except right after a start or an invalidation.
_SNAPSHOT_TTL = timedelta(minutes=5)
_snapshot: _Snapshot | None = None
_refresh_task: asyncio.Task[None] | None = None
_running: set[asyncio.Task[None]] = set()
_generation = 0


def invalidate_snapshot() -> None:
    """Forget the SimGrid half; call after a write that changes what it shows."""
    global _snapshot, _refresh_task, _generation
    _generation += 1
    _snapshot = None
    _refresh_task = None


async def _build_simgrid_entries() -> list[_SimgridEntry]:
    async with database.async_session() as db:
        skf = (
            await db.execute(select(Community).where(Community.is_skf.is_(True)).limit(1))
        ).scalar_one_or_none()
        community = CommunityOut.model_validate(skf) if skf else None
        active_ids = set((await db.execute(select(ActiveChampionship.simgrid_id))).scalars().all())
    if not active_ids:
        return []

    championships = [c for c in await simgrid_service.get_championships() if c.id in active_ids]
    race_pairs, detail_pairs = await asyncio.gather(
        asyncio.gather(*[_fetch_races(c.id) for c in championships]),
        asyncio.gather(*[_fetch_detail(c.id) for c in championships]),
    )
    races_by_id = dict(race_pairs)
    details_by_id = {cid: data for cid, data in detail_pairs if data is not None}

    entries: list[_SimgridEntry] = []
    for champ in championships:
        raw_races = races_by_id.get(champ.id, [])
        races = _simgrid_races(raw_races)
        all_races_ended = bool(raw_races) and all(r.get("ended", False) for r in raw_races)
        detail: dict[str, Any] = details_by_id.get(champ.id, {})

        # The list endpoint only returns ``id`` and ``name``; dates and the
        # registration state come from the details, then from the races.
        effective_start = champ.start_date or detail.get("start_date")
        effective_end = champ.end_date or detail.get("end_date")
        race_dates = [d for d in (_parse_date(r.date) for r in races if r.date) if d]
        if race_dates:
            effective_start = effective_start or min(race_dates).isoformat()
            effective_end = effective_end or max(race_dates).isoformat()

        completed = champ.event_completed or all_races_ended
        accepting_registrations = champ.accepting_registrations or bool(detail.get("accepting_registrations"))
        entries.append(
            _SimgridEntry(
                event=CalendarEventOut(
                    id=str(champ.id),
                    name=champ.name,
                    game=detail.get("game_name") or "",
                    description=detail.get("description"),
                    image=detail.get("image"),
                    start_date=effective_start,
                    end_date=effective_end,
                    event_type=_classify_simgrid(
                        effective_start, effective_end, completed, accepting_registrations
                    ),
                    source="simgrid",
                    simgrid_championship_id=champ.id,
                    community=community,
                    accepting_registrations=accepting_registrations,
                    capacity=detail.get("capacity"),
                    spots_taken=detail.get("spots_taken"),
                    registration_url=detail.get("url") or None,
                    races=races,
                ),
                completed=completed,
            )
        )
    return entries


async def _refresh_snapshot(generation: int) -> None:
    global _snapshot
    started = monotonic()
    try:
        entries = await _build_simgrid_entries()
    except Exception:
        logger.warning("Could not load SimGrid championships for the calendar", exc_info=True)
        return
    # An invalidation while this was running makes the result out of date.
    if generation != _generation:
        return
    _snapshot = _Snapshot(built_at=datetime.now(UTC), entries=entries)
    logger.info(
        "Calendar SimGrid snapshot built: %d championships in %.2fs", len(entries), monotonic() - started
    )


def _start_refresh() -> asyncio.Task[None]:
    """The running rebuild, started if there is none: callers share one."""
    global _refresh_task
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(_refresh_snapshot(_generation))
        _running.add(_refresh_task)
        _refresh_task.add_done_callback(_running.discard)
    return _refresh_task


async def _simgrid_entries() -> list[_SimgridEntry]:
    snapshot = _snapshot
    if snapshot is None:
        # Shielded: a client that goes away must not cancel the build others wait for.
        await asyncio.shield(_start_refresh())
        snapshot = _snapshot
        return snapshot.entries if snapshot else []
    if datetime.now(UTC) - snapshot.built_at > _SNAPSHOT_TTL:
        _start_refresh()
    return snapshot.entries


async def _simgrid_events(range_start: datetime, range_end: datetime) -> list[CalendarEventOut]:
    events: list[CalendarEventOut] = []
    for entry in await _simgrid_entries():
        event = entry.event
        start = _parse_date(event.start_date)
        end = _parse_date(event.end_date)

        # Dateless championships are included (unscheduled) — skip the range filter.
        has_any_date = start is not None or end is not None or any(r.date for r in event.races)
        if has_any_date and not _overlaps_range(start, end, event.races, range_start, range_end):
            continue

        # The type depends on the current time, so it is not part of the snapshot.
        event_type = _classify_simgrid(
            event.start_date, event.end_date, entry.completed, event.accepting_registrations
        )
        events.append(event.model_copy(update={"event_type": event_type}))
    return events


# ── Custom championships ─────────────────────────────────────────────────────


async def _custom_events(
    db: AsyncSession, range_start: datetime, range_end: datetime
) -> list[CalendarEventOut]:
    result = await db.execute(select(CustomChampionship).where(CustomChampionship.is_visible.is_(True)))
    events: list[CalendarEventOut] = []
    for champ in result.scalars().all():
        race_dates = [r.date for r in champ.races if r.date is not None]
        all_dates = race_dates + [r.end_date for r in champ.races if r.end_date is not None]
        earliest = min(race_dates) if race_dates else None
        latest = max(all_dates) if all_dates else None

        races = [
            CalendarRaceOut(
                date=r.date.isoformat() if r.date else None,
                end_date=r.end_date.isoformat() if r.end_date else None,
                track=r.track,
            )
            for r in champ.races
        ]

        # Championships without dated races are still shown (as dateless).
        if race_dates and not _overlaps_range(earliest, latest, races, range_start, range_end):
            continue

        community = champ.community
        events.append(
            CalendarEventOut(
                id=str(champ.id),
                name=champ.name,
                game=champ.game_rel.name if champ.game_rel is not None else champ.game,
                car_class=champ.car_class,
                description=champ.description,
                start_date=earliest.isoformat() if earliest else None,
                end_date=latest.isoformat() if latest else None,
                event_type=CalendarEventType.FUTURE,
                source="custom",
                custom_championship_id=champ.id,
                community=CommunityOut.model_validate(community) if community else None,
                races=races,
            )
        )
    return events


async def list_calendar_events(db: AsyncSession, start: date, end: date) -> list[CalendarEventOut]:
    """Merged SimGrid + custom championship events between two dates, both included.

    Always includes every visible community's championships alongside SKF
    events; filtering by community/game/class happens on the frontend.
    """
    if end < start:
        raise Unprocessable("`to` must not be earlier than `from`.")
    range_start, range_end = _date_range(start, end)
    return [
        *await _simgrid_events(range_start, range_end),
        *await _custom_events(db, range_start, range_end),
    ]

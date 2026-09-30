"""Calendar: merge active SimGrid championships with custom championships.

Also serves the simulator and car-class catalogues the calendar filters use.
"""

from __future__ import annotations

import asyncio
import logging
from calendar import monthrange
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.active_championship import ActiveChampionship
from app.models.community import Community
from app.models.custom_championship import CustomChampionship
from app.schemas.calendar import CalendarEvent, CalendarEventType, CalendarRace
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
    races: list[CalendarRace],
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


def _date_range(year: int, month: int | None) -> tuple[datetime, datetime]:
    if month is not None:
        _, days_in_month = monthrange(year, month)
        return (
            datetime(year, month, 1, tzinfo=UTC),
            datetime(year, month, days_in_month, 23, 59, 59, tzinfo=UTC),
        )
    return (
        datetime(year, 1, 1, tzinfo=UTC),
        datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC),
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


def _simgrid_races(raw_races: list[dict]) -> list[CalendarRace]:
    races: list[CalendarRace] = []
    for r in raw_races:
        race_date = r.get("starts_at") or r.get("startsAt") or r.get("start_date") or r.get("startDate")
        track = r.get("track")
        track_name = None
        if isinstance(track, dict):
            track_name = track.get("name")
        elif isinstance(track, str):
            track_name = track
        races.append(
            CalendarRace(
                date=race_date,
                track=track_name,
                name=r.get("display_name") or r.get("race_name") or r.get("displayName"),
            )
        )
    return races


async def _simgrid_events(
    db: AsyncSession, range_start: datetime, range_end: datetime
) -> list[CalendarEvent]:
    skf = (
        await db.execute(select(Community).where(Community.is_skf.is_(True)).limit(1))
    ).scalar_one_or_none()

    active_ids = set((await db.execute(select(ActiveChampionship.simgrid_id))).scalars().all())
    try:
        championships = await simgrid_service.with_details(
            [c for c in await simgrid_service.get_championships() if c.id in active_ids]
        )
    except Exception:
        logger.warning("Could not load SimGrid championships for the calendar", exc_info=True)
        championships = []

    races_by_id = dict(await asyncio.gather(*[_fetch_races(c.id) for c in championships]))
    details_by_id = {
        cid: data
        for cid, data in await asyncio.gather(*[_fetch_detail(c.id) for c in championships])
        if data is not None
    }

    events: list[CalendarEvent] = []
    for champ in championships:
        raw_races = races_by_id.get(champ.id, [])
        races = _simgrid_races(raw_races)
        all_races_ended = bool(raw_races) and all(r.get("ended", False) for r in raw_races)
        detail: dict[str, Any] = details_by_id.get(champ.id, {})

        effective_start = champ.start_date
        effective_end = champ.end_date
        # Dateless single-event championships: fall back to the detail dates.
        if not effective_start and not races and detail:
            effective_start = detail.get("start_date")
            effective_end = detail.get("end_date")
        race_dates = [d for d in (_parse_date(r.date) for r in races if r.date) if d]
        if race_dates:
            effective_start = effective_start or min(race_dates).isoformat()
            effective_end = effective_end or max(race_dates).isoformat()

        start = _parse_date(effective_start)
        end = _parse_date(effective_end)
        event_type = _classify_simgrid(
            effective_start,
            effective_end,
            champ.event_completed or all_races_ended,
            champ.accepting_registrations,
        )

        # Dateless championships are included (unscheduled) — skip the range filter.
        has_any_date = start is not None or end is not None or any(r.date for r in races)
        if has_any_date and not _overlaps_range(start, end, races, range_start, range_end):
            continue

        events.append(
            CalendarEvent(
                id=str(champ.id),
                name=champ.name,
                game=detail.get("game_name") or "",
                description=detail.get("description"),
                image=detail.get("image"),
                start_date=effective_start,
                end_date=effective_end,
                event_type=event_type,
                source="simgrid",
                simgrid_championship_id=champ.id,
                community_id=skf.id if skf else None,
                community_name=skf.name if skf else None,
                community_color=skf.color if skf else None,
                community_discord_url=skf.discord_url if skf else None,
                community_is_skf=True,
                accepting_registrations=(
                    champ.accepting_registrations or bool(detail.get("accepting_registrations"))
                ),
                capacity=detail.get("capacity"),
                spots_taken=detail.get("spots_taken"),
                registration_url=detail.get("url") or None,
                races=races,
            )
        )
    return events


# ── Custom championships ─────────────────────────────────────────────────────


async def _custom_events(db: AsyncSession, range_start: datetime, range_end: datetime) -> list[CalendarEvent]:
    result = await db.execute(select(CustomChampionship).where(CustomChampionship.is_visible.is_(True)))
    events: list[CalendarEvent] = []
    for champ in result.scalars().all():
        race_dates = [r.date for r in champ.races if r.date is not None]
        all_dates = race_dates + [r.end_date for r in champ.races if r.end_date is not None]
        earliest = min(race_dates) if race_dates else None
        latest = max(all_dates) if all_dates else None

        races = [
            CalendarRace(
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
            CalendarEvent(
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
                community_id=community.id if community else None,
                community_name=community.name if community else None,
                community_color=community.color if community else None,
                community_discord_url=community.discord_url if community else None,
                community_is_skf=community.is_skf if community else False,
                races=races,
            )
        )
    return events


async def list_calendar_events(db: AsyncSession, year: int, month: int | None) -> list[CalendarEvent]:
    """Merged SimGrid + custom championship events for a month (or a whole year).

    Always includes every visible community's championships alongside SKF
    events; filtering by community/game/class happens on the frontend.
    """
    range_start, range_end = _date_range(year, month)
    return [
        *await _simgrid_events(db, range_start, range_end),
        *await _custom_events(db, range_start, range_end),
    ]

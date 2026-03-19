"""Calendar router – CRUD for custom championships/races + merged calendar endpoint."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from calendar import monthrange

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.custom_championship import CustomChampionship, CustomRace
from app.models.simgrid_cache import SimgridCache
from app.models.user import User
from app.schemas.calendar import (
    CalendarEvent,
    CalendarEventType,
    CalendarRace,
    CustomChampionshipCreate,
    CustomChampionshipOut,
    CustomChampionshipUpdate,
    CustomRaceCreate,
    CustomRaceOut,
    CustomRaceUpdate,
)
from app.services.simgrid import simgrid_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["Calendar"])


# ── Helpers ──────────────────────────────────────────────────────────────────


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
    """Classify a SimGrid championship – mirrors frontend getStatusOrder logic."""
    today = datetime.now(timezone.utc).date()
    start = _parse_date(start_date)
    end = _parse_date(end_date)

    if start and start.date() > today:
        return CalendarEventType.UPCOMING
    if event_completed:
        return CalendarEventType.PAST
    if end and end.date() < today:
        return CalendarEventType.PAST
    if start and start.date() <= today:
        return CalendarEventType.ONGOING
    if accepting_registrations:
        return CalendarEventType.ONGOING
    return CalendarEventType.UPCOMING


async def _get_championship_or_404(
    champ_id: uuid.UUID, db: AsyncSession
) -> CustomChampionship:
    result = await db.execute(
        select(CustomChampionship).where(CustomChampionship.id == champ_id)
    )
    champ = result.scalar_one_or_none()
    if champ is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom championship not found.",
        )
    return champ


# ── Merged calendar endpoint ─────────────────────────────────────────────────


@router.get("/events", response_model=list[CalendarEvent])
async def get_calendar_events(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
):
    """Return merged SimGrid + custom championship events for the given month."""
    _, days_in_month = monthrange(year, month)
    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    month_end = datetime(year, month, days_in_month, 23, 59, 59, tzinfo=timezone.utc)

    events: list[CalendarEvent] = []

    # ── SimGrid championships ──
    try:
        championships = await simgrid_service.get_championships()
    except Exception:
        championships = []

    # Load cached standings to get individual race dates
    result = await db.execute(
        select(SimgridCache).where(SimgridCache.cache_key.like("standings_%"))
    )
    standings_caches: dict[int, dict] = {
        _extract_champ_id(c.cache_key): c.data
        for c in result.scalars().all()
        if _extract_champ_id(c.cache_key) is not None
    }

    # Fetch standings on-demand for championships without cached data.
    # This populates the cache so subsequent requests are fast.
    uncached_ids = [c.id for c in championships if c.id not in standings_caches]
    if uncached_ids:
        async def _fetch_one(cid: int) -> tuple[int, dict | None]:
            try:
                data = await simgrid_service.get_standings(cid)
                return cid, data.model_dump()
            except Exception:
                logger.debug("Failed to fetch standings for championship %s", cid)
                return cid, None

        results = await asyncio.gather(*[_fetch_one(cid) for cid in uncached_ids])
        for cid, data in results:
            if data is not None:
                standings_caches[cid] = data

    for champ in championships:
        # Build race list from standings data (cached or freshly fetched)
        races: list[CalendarRace] = []
        all_races_ended = False
        standings_data = standings_caches.get(champ.id)
        if isinstance(standings_data, dict):
            raw_races = standings_data.get("races", [])
            for r in raw_races:
                race_date = r.get("starts_at") or r.get("startsAt")
                races.append(CalendarRace(
                    date=race_date,
                    track=None,
                    name=r.get("display_name") or r.get("displayName"),
                ))
            # If all races in standings have ended, treat as completed
            if raw_races and all(r.get("ended", False) for r in raw_races):
                all_races_ended = True

        # Derive effective start/end from race dates when championship dates are missing
        effective_start = champ.start_date
        effective_end = champ.end_date
        race_dates = [_parse_date(r.date) for r in races if r.date]
        race_dates = [d for d in race_dates if d is not None]
        if race_dates:
            if not effective_start:
                effective_start = min(race_dates).isoformat()
            if not effective_end:
                effective_end = max(race_dates).isoformat()

        start = _parse_date(effective_start)
        end = _parse_date(effective_end)
        effectively_completed = champ.event_completed or all_races_ended
        event_type = _classify_simgrid(
            effective_start, effective_end,
            effectively_completed, champ.accepting_registrations,
        )

        # Dateless championships are included (unscheduled) — skip month filter
        has_any_date = start is not None or end is not None or any(r.date for r in races)
        if has_any_date and not _overlaps_month(start, end, races, month_start, month_end):
            continue

        events.append(CalendarEvent(
            id=str(champ.id),
            name=champ.name,
            game="",
            start_date=effective_start,
            end_date=effective_end,
            event_type=event_type,
            source="simgrid",
            simgrid_championship_id=champ.id,
            races=races,
        ))

    # ── Custom championships ──
    custom_champs_result = await db.execute(
        select(CustomChampionship).where(CustomChampionship.is_visible.is_(True))
    )
    for champ in custom_champs_result.scalars().all():
        race_dates = [r.date for r in champ.races if r.date is not None]
        earliest = min(race_dates) if race_dates else None
        latest = max(race_dates) if race_dates else None

        custom_races = [
            CalendarRace(
                date=r.date.isoformat() if r.date else None,
                track=r.track,
                name=None,
            )
            for r in champ.races
        ]

        # Check overlap
        if not _overlaps_month(earliest, latest, custom_races, month_start, month_end):
            # Still include if championship has no races with dates (show as dateless)
            if race_dates:
                continue

        events.append(CalendarEvent(
            id=str(champ.id),
            name=champ.name,
            game=champ.game,
            car_class=champ.car_class,
            description=champ.description,
            start_date=earliest.isoformat() if earliest else None,
            end_date=latest.isoformat() if latest else None,
            event_type=CalendarEventType.FUTURE,
            source="custom",
            custom_championship_id=str(champ.id),
            races=custom_races,
        ))

    return events


def _extract_champ_id(cache_key: str) -> int | None:
    try:
        return int(cache_key.split("_", 1)[1])
    except (ValueError, IndexError):
        return None


def _overlaps_month(
    start: datetime | None,
    end: datetime | None,
    races: list[CalendarRace],
    month_start: datetime,
    month_end: datetime,
) -> bool:
    """Check if a championship or any of its races overlap with the month."""
    # Check individual race dates
    for race in races:
        if race.date:
            rd = _parse_date(race.date)
            if rd and month_start <= rd <= month_end:
                return True

    # Check championship date range
    if start and end:
        return start <= month_end and end >= month_start
    if start:
        return start <= month_end and start >= month_start
    if end:
        return end >= month_start and end <= month_end

    return False


# ── Custom championship CRUD ─────────────────────────────────────────────────


@router.get("/custom-championships", response_model=list[CustomChampionshipOut])
async def list_custom_championships(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CustomChampionship).order_by(CustomChampionship.created_at.desc())
    )
    return result.scalars().all()


@router.post(
    "/custom-championships",
    response_model=CustomChampionshipOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_custom_championship(
    body: CustomChampionshipCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    champ = CustomChampionship(
        name=body.name.strip(),
        game=body.game.strip(),
        car_class=body.car_class.strip() if body.car_class else None,
        description=body.description,
        created_by_user_id=admin.id,
    )
    for idx, race_data in enumerate(body.races):
        champ.races.append(
            CustomRace(
                date=race_data.date,
                track=race_data.track.strip() if race_data.track else None,
                sort_order=idx,
            )
        )
    db.add(champ)
    await db.commit()
    await db.refresh(champ)
    return champ


@router.patch(
    "/custom-championships/{champ_id}",
    response_model=CustomChampionshipOut,
)
async def update_custom_championship(
    champ_id: uuid.UUID,
    body: CustomChampionshipUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    champ = await _get_championship_or_404(champ_id, db)
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(champ, field, value)
    await db.commit()
    await db.refresh(champ)
    return champ


@router.delete(
    "/custom-championships/{champ_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_custom_championship(
    champ_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    champ = await _get_championship_or_404(champ_id, db)
    await db.delete(champ)
    await db.commit()


# ── Custom race CRUD ─────────────────────────────────────────────────────────


@router.post(
    "/custom-championships/{champ_id}/races",
    response_model=CustomRaceOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_race(
    champ_id: uuid.UUID,
    body: CustomRaceCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    champ = await _get_championship_or_404(champ_id, db)
    max_order = max((r.sort_order for r in champ.races), default=-1)
    race = CustomRace(
        championship_id=champ.id,
        date=body.date,
        track=body.track.strip() if body.track else None,
        sort_order=max_order + 1,
    )
    db.add(race)
    await db.commit()
    await db.refresh(race)
    return race


@router.patch(
    "/custom-championships/{champ_id}/races/{race_id}",
    response_model=CustomRaceOut,
)
async def update_race(
    champ_id: uuid.UUID,
    race_id: uuid.UUID,
    body: CustomRaceUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _get_championship_or_404(champ_id, db)
    result = await db.execute(
        select(CustomRace).where(
            CustomRace.id == race_id,
            CustomRace.championship_id == champ_id,
        )
    )
    race = result.scalar_one_or_none()
    if race is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Race not found."
        )
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(race, field, value)
    await db.commit()
    await db.refresh(race)
    return race


@router.delete(
    "/custom-championships/{champ_id}/races/{race_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_race(
    champ_id: uuid.UUID,
    race_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _get_championship_or_404(champ_id, db)
    result = await db.execute(
        select(CustomRace).where(
            CustomRace.id == race_id,
            CustomRace.championship_id == champ_id,
        )
    )
    race = result.scalar_one_or_none()
    if race is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Race not found."
        )
    await db.delete(race)
    await db.commit()

"""Calendar router – CRUD for communities, games, custom championships/races + merged calendar endpoint."""

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
from app.models.active_championship import ActiveChampionship
from app.models.community import Community, Game
from app.models.custom_championship import CustomChampionship, CustomRace
from app.models.user import User
from app.schemas.calendar import (
    CalendarEvent,
    CalendarEventType,
    CalendarRace,
    CommunityCreate,
    CommunityOut,
    CommunityUpdate,
    CustomChampionshipCreate,
    CustomChampionshipOut,
    CustomChampionshipUpdate,
    CustomRaceCreate,
    CustomRaceOut,
    CustomRaceUpdate,
    GameCreate,
    GameOut,
    GameUpdate,
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
    """Classify a SimGrid championship – uses full datetime for accuracy."""
    now = datetime.now(timezone.utc)
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


def _champ_to_out(champ: CustomChampionship) -> CustomChampionshipOut:
    """Convert a CustomChampionship ORM object to output schema with game_name."""
    data = CustomChampionshipOut.model_validate(champ)
    if champ.game_rel is not None:
        data.game_name = champ.game_rel.name
    return data


# ── Community CRUD ───────────────────────────────────────────────────────────


@router.get("/communities", response_model=list[CommunityOut])
async def list_communities(
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint – returns visible communities for calendar filters."""
    result = await db.execute(
        select(Community)
        .where(Community.is_visible.is_(True))
        .order_by(Community.name)
    )
    return result.scalars().all()


@router.post(
    "/communities",
    response_model=CommunityOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_community(
    body: CommunityCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    community = Community(
        name=body.name.strip(),
        color=body.color.strip() if body.color else None,
        discord_url=body.discord_url.strip() if body.discord_url else None,
    )
    db.add(community)
    await db.commit()
    await db.refresh(community)
    return community


@router.patch("/communities/{community_id}", response_model=CommunityOut)
async def update_community(
    community_id: uuid.UUID,
    body: CommunityUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Community).where(Community.id == community_id)
    )
    community = result.scalar_one_or_none()
    if community is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Community not found."
        )
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(community, field, value)
    await db.commit()
    await db.refresh(community)
    return community


@router.delete(
    "/communities/{community_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_community(
    community_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Community).where(Community.id == community_id)
    )
    community = result.scalar_one_or_none()
    if community is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Community not found."
        )
    await db.delete(community)
    await db.commit()


# ── Game CRUD ────────────────────────────────────────────────────────────────


@router.get("/games", response_model=list[GameOut])
async def list_games(
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint – returns all games for filter dropdowns and forms."""
    result = await db.execute(select(Game).order_by(Game.name))
    return result.scalars().all()


@router.post(
    "/games",
    response_model=GameOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_game(
    body: GameCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    game = Game(name=body.name.strip())
    db.add(game)
    await db.commit()
    await db.refresh(game)
    return game


@router.patch("/games/{game_id}", response_model=GameOut)
async def update_game(
    game_id: uuid.UUID,
    body: GameUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Game).where(Game.id == game_id))
    game = result.scalar_one_or_none()
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Game not found."
        )
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(game, field, value)
    await db.commit()
    await db.refresh(game)
    return game


@router.delete("/games/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_game(
    game_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Game).where(Game.id == game_id))
    game = result.scalar_one_or_none()
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Game not found."
        )
    await db.delete(game)
    await db.commit()


# ── Merged calendar endpoint ─────────────────────────────────────────────────


@router.get("/events", response_model=list[CalendarEvent])
async def get_calendar_events(
    year: int = Query(..., ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
):
    """Return merged SimGrid + custom championship events for the given month (or full year).

    Always includes all visible communities' championships alongside SKF events.
    Filtering by community/game/class is done on the frontend.
    """
    if month is not None:
        _, days_in_month = monthrange(year, month)
        range_start = datetime(year, month, 1, tzinfo=timezone.utc)
        range_end = datetime(year, month, days_in_month, 23, 59, 59, tzinfo=timezone.utc)
    else:
        range_start = datetime(year, 1, 1, tzinfo=timezone.utc)
        range_end = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    events: list[CalendarEvent] = []

    # ── SimGrid championships (active only) ──
    active_result = await db.execute(select(ActiveChampionship.simgrid_id))
    active_ids = set(active_result.scalars().all())

    try:
        all_championships = await simgrid_service.get_championships()
        championships = [c for c in all_championships if c.id in active_ids]
    except Exception:
        championships = []

    # Fetch races + details only for active championships
    races_caches: dict[int, list[dict]] = {}

    async def _fetch_races(cid: int) -> tuple[int, list[dict]]:
        try:
            return cid, await simgrid_service.get_races(cid)
        except Exception:
            logger.debug("Failed to fetch races for championship %s", cid)
            return cid, []

    fetch_results = await asyncio.gather(
        *[_fetch_races(c.id) for c in championships]
    )
    for cid, data in fetch_results:
        races_caches[cid] = data

    detail_caches: dict[int, dict] = {}

    async def _fetch_detail(cid: int) -> tuple[int, dict | None]:
        try:
            details = await simgrid_service.get_championship(cid)
            return cid, details.model_dump()
        except Exception:
            return cid, None

    detail_results = await asyncio.gather(
        *[_fetch_detail(c.id) for c in championships]
    )
    for cid, data in detail_results:
        if data is not None:
            detail_caches[cid] = data

    for champ in championships:
        # Build race list from races endpoint data
        races: list[CalendarRace] = []
        all_races_ended = False
        raw_races = races_caches.get(champ.id, [])
        for r in raw_races:
            race_date = (
                r.get("starts_at") or r.get("startsAt")
                or r.get("start_date") or r.get("startDate")
            )
            track = r.get("track")
            track_name = None
            if isinstance(track, dict):
                track_name = track.get("name")
            elif isinstance(track, str):
                track_name = track
            races.append(CalendarRace(
                date=race_date,
                track=track_name,
                name=r.get("display_name") or r.get("race_name") or r.get("displayName"),
            ))
        # If all races have ended, treat as completed
        if raw_races and all(r.get("ended", False) for r in raw_races):
            all_races_ended = True

        # Derive effective start/end from race dates when championship dates are missing
        effective_start = champ.start_date
        effective_end = champ.end_date

        # Fallback: use championship detail dates for dateless single-event championships
        if not effective_start and not races and champ.id in detail_caches:
            detail = detail_caches[champ.id]
            effective_start = detail.get("startDate") or detail.get("start_date")
            effective_end = detail.get("endDate") or detail.get("end_date")
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
        if has_any_date and not _overlaps_month(start, end, races, range_start, range_end):
            continue

        detail = detail_caches.get(champ.id, {})
        events.append(CalendarEvent(
            id=str(champ.id),
            name=champ.name,
            game=detail.get("gameName") or detail.get("game_name") or "",
            description=detail.get("description"),
            image=detail.get("image"),
            start_date=effective_start,
            end_date=effective_end,
            event_type=event_type,
            source="simgrid",
            simgrid_championship_id=champ.id,
            races=races,
        ))

    # ── Custom championships (SKF + all communities) ──
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
        if not _overlaps_month(earliest, latest, custom_races, range_start, range_end):
            # Still include if championship has no races with dates (show as dateless)
            if race_dates:
                continue

        # Resolve community metadata
        community = champ.community
        community_id = str(community.id) if community else None
        community_name = community.name if community else None
        community_color = community.color if community else None

        # Use game name from Game relation if available, fall back to game string field
        game_name = champ.game
        if champ.game_rel is not None:
            game_name = champ.game_rel.name

        events.append(CalendarEvent(
            id=str(champ.id),
            name=champ.name,
            game=game_name,
            car_class=champ.car_class,
            description=champ.description,
            start_date=earliest.isoformat() if earliest else None,
            end_date=latest.isoformat() if latest else None,
            event_type=CalendarEventType.FUTURE,
            source="custom",
            custom_championship_id=str(champ.id),
            community_id=community_id,
            community_name=community_name,
            community_color=community_color,
            races=custom_races,
        ))

    return events


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
    community_id: uuid.UUID | None = Query(None, alias="communityId"),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(CustomChampionship).order_by(CustomChampionship.created_at.desc())
    if community_id is not None:
        query = query.where(CustomChampionship.community_id == community_id)
    result = await db.execute(query)
    return [_champ_to_out(c) for c in result.scalars().all()]


@router.post(
    "/custom-championships",
    response_model=CustomChampionshipOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_custom_championship(
    body: CustomChampionshipCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    champ = CustomChampionship(
        name=body.name.strip(),
        game=body.game.strip(),
        car_class=body.car_class.strip() if body.car_class else None,
        description=body.description,
        community_id=body.community_id,
        game_id=body.game_id,
        created_by_user_id=_.id,
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
    return _champ_to_out(champ)


@router.patch(
    "/custom-championships/{champ_id}",
    response_model=CustomChampionshipOut,
)
async def update_custom_championship(
    champ_id: uuid.UUID,
    body: CustomChampionshipUpdate,
    _: User = Depends(require_admin),
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
    return _champ_to_out(champ)


@router.delete(
    "/custom-championships/{champ_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_custom_championship(
    champ_id: uuid.UUID,
    _: User = Depends(require_admin),
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
    _: User = Depends(require_admin),
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
    _: User = Depends(require_admin),
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
    _: User = Depends(require_admin),
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

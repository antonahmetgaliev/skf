"""Championship standings proxy – calls SimGrid API server-side."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.active_championship import ActiveChampionship
from app.models.simgrid_cache import SimgridCache
from app.models.user import User
from app.schemas.championship import (
    ChampionshipDetails,
    ChampionshipListItem,
    ChampionshipPodium,
    ChampionshipRace,
    ChampionshipStandingsData,
    DriverChampionshipResult,
    PodiumEntry,
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
async def list_championships(force: bool = Query(False), db: AsyncSession = Depends(get_db)):
    try:
        items = await simgrid_service.get_championships(force=force)
    except Exception:
        logger.warning("Failed to fetch championships from SimGrid", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch championships from SimGrid.",
        )

    # Championships in the active list are active; all others are finished.
    result = await db.execute(select(ActiveChampionship.simgrid_id))
    active_ids = set(result.scalars().all())

    return [
        item if item.id in active_ids
        else item.model_copy(update={"event_completed": True})
        for item in items
    ]


@router.get("/podium", response_model=list[ChampionshipPodium])
async def get_champions_podium(db: AsyncSession = Depends(get_db)):
    """Return top-3 finishers for each completed championship."""
    result = await db.execute(
        select(SimgridCache).where(SimgridCache.cache_key.like("standings_%"))
    )
    caches = result.scalars().all()

    # Only non-active championships are considered finished
    active_result = await db.execute(select(ActiveChampionship.simgrid_id))
    active_ids = set(active_result.scalars().all())

    try:
        championships = await simgrid_service.get_championships()
        champ_map = {c.id: c for c in championships}
    except Exception:
        champ_map = {}

    podiums: list[ChampionshipPodium] = []
    for cache in caches:
        try:
            champ_id = int(cache.cache_key.split("_", 1)[1])
        except (ValueError, IndexError):
            continue
        if champ_id in active_ids:
            continue
        data = cache.data
        if not isinstance(data, dict):
            continue
        entries = data.get("entries", [])
        top3 = [
            e for e in entries
            if e.get("position") in (1, 2, 3) and not (e.get("dsq") or e.get("dsq", False))
        ]
        top3.sort(key=lambda e: e.get("position", 999))
        if not top3:
            continue
        champ = champ_map.get(champ_id)
        podiums.append(ChampionshipPodium(
            championship_id=champ_id,
            championship_name=champ.name if champ else f"Championship #{champ_id}",
            podium=[
                PodiumEntry(
                    simgrid_driver_id=e.get("id"),
                    display_name=e.get("displayName") or e.get("display_name", ""),
                    position=e.get("position"),
                )
                for e in top3
            ],
        ))

    podiums.sort(key=lambda p: -p.championship_id)
    return podiums


@router.get("/raw-cache", include_in_schema=False)
async def raw_championship_cache(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Debug: return the raw cached SimGrid championship list to inspect field names."""
    result = await db.execute(
        select(SimgridCache).where(SimgridCache.cache_key.like("championships_list%"))
    )
    row = result.scalars().first()
    if not row:
        return {"error": "no cache entry found"}
    items = row.data
    if not items:
        return {"error": "empty cache"}
    return {"keys": list(items[0].keys()) if items else [], "sample": items[0] if items else {}}


@router.get("/raw-detail-cache", include_in_schema=False)
async def raw_detail_cache(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Debug: return raw cached championship detail to inspect field names."""
    result = await db.execute(
        select(SimgridCache).where(SimgridCache.cache_key.like("championship_%"))
    )
    row = result.scalars().first()
    if not row:
        return {"error": "no cache entry found"}
    data = row.data
    if not data or not isinstance(data, dict):
        return {"error": "empty cache"}
    return {"keys": list(data.keys()), "sample_values": {k: type(v).__name__ for k, v in data.items()}}


@router.get("/raw-standings-cache/{championship_id}", include_in_schema=False)
async def raw_standings_cache(
    championship_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Debug: return the cached standings data (post-parsing)."""
    result = await db.execute(
        select(SimgridCache).where(
            SimgridCache.cache_key == f"standings_{championship_id}"
        )
    )
    row = result.scalars().first()
    if not row:
        return {"error": "no cache entry found"}
    return row.data


@router.get("/raw-standings-api/{championship_id}", include_in_schema=False)
async def raw_standings_api(
    championship_id: int,
    _: User = Depends(require_admin),
):
    """Debug: return the raw SimGrid standings API response (unparsed)."""
    import httpx
    from app.config import settings
    headers = {}
    if settings.simgrid_api_key:
        headers["Authorization"] = f"Bearer {settings.simgrid_api_key}"
    async with httpx.AsyncClient(base_url=settings.simgrid_base_url, headers=headers, timeout=30.0) as client:
        resp = await client.get(f"/api/v1/championships/{championship_id}/standings")
        resp.raise_for_status()
        return resp.json()


@router.get("/driver/{simgrid_driver_id}/results", response_model=list[DriverChampionshipResult])
async def get_driver_championship_results(
    simgrid_driver_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return all cached championship results for a specific SimGrid driver ID."""
    # Build championship name/date map from the cached list (already in DB)
    try:
        championships = await simgrid_service.get_championships()
        champ_map = {c.id: c for c in championships}
    except Exception:
        champ_map = {}

    # Query all standings caches directly from the database
    result = await db.execute(
        select(SimgridCache).where(SimgridCache.cache_key.like("standings_%"))
    )
    caches = result.scalars().all()

    driver_results: list[DriverChampionshipResult] = []
    for cache in caches:
        try:
            champ_id = int(cache.cache_key.split("_", 1)[1])
        except (ValueError, IndexError):
            continue

        data = cache.data
        if not isinstance(data, dict):
            continue

        for entry in data.get("entries", []):
            if entry.get("id") == simgrid_driver_id:
                champ = champ_map.get(champ_id)
                driver_results.append(DriverChampionshipResult(
                    championship_id=champ_id,
                    championship_name=champ.name if champ else f"Championship #{champ_id}",
                    position=entry.get("position"),
                    score=entry.get("score", 0),
                    dsq=entry.get("dsq", False),
                    start_date=champ.start_date if champ else None,
                    end_date=champ.end_date if champ else None,
                    accepting_registrations=champ.accepting_registrations if champ else False,
                ))
                break

    driver_results.sort(
        key=lambda r: (r.position is None, r.position or 999, -r.championship_id)
    )
    return driver_results


@router.get("/{championship_id}/races", response_model=list[ChampionshipRace])
async def get_races(championship_id: int, force: bool = Query(False)):
    """Return all races for a championship (including future ones)."""
    try:
        raw = await simgrid_service.get_races(championship_id, force=force)
        return [ChampionshipRace(**r) for r in raw]
    except Exception:
        logger.warning("Failed to fetch races for championship %s", championship_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch races from SimGrid.",
        )


@router.get("/{championship_id}", response_model=ChampionshipDetails)
async def get_championship(championship_id: int, force: bool = Query(False)):
    try:
        return await simgrid_service.get_championship(championship_id, force=force)
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
    force: bool = Query(False),
):
    try:
        data = await simgrid_service.get_standings(championship_id, force=force)
        # Sync driver profiles non-blocking after response is sent
        background_tasks.add_task(sync_drivers_from_standings, data.entries)
        return data
    except Exception:
        logger.warning("Failed to fetch standings for championship %s", championship_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch standings from SimGrid.",
        )

"""Championship standings proxy – calls SimGrid API server-side."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.simgrid_cache import SimgridCache
from app.schemas.championship import (
    ChampionshipDetails,
    ChampionshipListItem,
    ChampionshipStandingsData,
    DriverChampionshipResult,
)
from app.services.drivers import sync_drivers_from_standings
from app.services.simgrid import simgrid_service

router = APIRouter(prefix="/championships", tags=["Championships"])


@router.get("", response_model=list[ChampionshipListItem])
async def list_championships(force: bool = Query(False), db: AsyncSession = Depends(get_db)):
    try:
        items = await simgrid_service.get_championships(force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    # Derive event_completed from cached standings: if all races are ended, the championship is over.
    result = await db.execute(
        select(SimgridCache).where(SimgridCache.cache_key.like("standings_%"))
    )
    caches = result.scalars().all()

    completed_ids: set[int] = set()
    for cache in caches:
        try:
            champ_id = int(cache.cache_key.split("_", 1)[1])
        except (ValueError, IndexError):
            continue
        data = cache.data
        if not isinstance(data, dict):
            continue
        races = data.get("races", [])
        if races and all(r.get("ended", False) for r in races):
            completed_ids.add(champ_id)

    return [
        item.model_copy(update={"event_completed": True}) if item.id in completed_ids else item
        for item in items
    ]


@router.get("/raw-cache", include_in_schema=False)
async def raw_championship_cache(db: AsyncSession = Depends(get_db)):
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


@router.get("/{championship_id}", response_model=ChampionshipDetails)
async def get_championship(championship_id: int, force: bool = Query(False)):
    try:
        return await simgrid_service.get_championship(championship_id, force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


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
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/{championship_id}/refresh-cache")
async def refresh_cache(championship_id: int, background_tasks: BackgroundTasks):
    """Force re-fetch all data for a championship from SimGrid."""
    try:
        await simgrid_service.invalidate_cache(championship_id)
        details = await simgrid_service.get_championship(championship_id, force=True)
        standings = await simgrid_service.get_standings(championship_id, force=True)
        background_tasks.add_task(sync_drivers_from_standings, standings.entries)
        return {"status": "ok", "championship": details.name, "entries": len(standings.entries)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

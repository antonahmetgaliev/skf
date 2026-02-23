"""Championship standings proxy – calls SimGrid API server-side."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.championship import (
    ChampionshipDetails,
    ChampionshipListItem,
    ChampionshipStandingsData,
)
from app.services.simgrid import simgrid_service

router = APIRouter(prefix="/championships", tags=["Championships"])


@router.get("", response_model=list[ChampionshipListItem])
async def list_championships(force: bool = Query(False)):
    try:
        return await simgrid_service.get_championships(force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{championship_id}", response_model=ChampionshipDetails)
async def get_championship(championship_id: int, force: bool = Query(False)):
    try:
        return await simgrid_service.get_championship(championship_id, force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get(
    "/{championship_id}/standings", response_model=ChampionshipStandingsData
)
async def get_standings(championship_id: int, force: bool = Query(False)):
    try:
        return await simgrid_service.get_standings(championship_id, force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/{championship_id}/refresh-cache")
async def refresh_cache(championship_id: int):
    """Force re-fetch all data for a championship from SimGrid."""
    try:
        await simgrid_service.invalidate_cache(championship_id)
        details = await simgrid_service.get_championship(championship_id, force=True)
        standings = await simgrid_service.get_standings(championship_id, force=True)
        return {"status": "ok", "championship": details.name, "entries": len(standings.entries)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

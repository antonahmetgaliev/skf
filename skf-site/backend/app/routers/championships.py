"""Championship standings proxy – calls SimGrid API server-side."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.championship import (
    ChampionshipDetails,
    ChampionshipListItem,
    ChampionshipStandingsData,
)
from app.services.simgrid import simgrid_service

router = APIRouter(prefix="/championships", tags=["Championships"])


@router.get("", response_model=list[ChampionshipListItem])
async def list_championships():
    try:
        return await simgrid_service.get_championships()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{championship_id}", response_model=ChampionshipDetails)
async def get_championship(championship_id: int):
    try:
        return await simgrid_service.get_championship(championship_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get(
    "/{championship_id}/standings", response_model=ChampionshipStandingsData
)
async def get_standings(championship_id: int):
    try:
        return await simgrid_service.get_standings(championship_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

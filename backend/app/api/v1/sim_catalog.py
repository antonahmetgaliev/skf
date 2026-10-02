"""Simulator and car-class catalogues (from SimGrid) for calendar filters."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.openapi import STALE_RESPONSES
from app.services import calendar_events as service

router = APIRouter(tags=["Catalog"])


@router.get("/simulators", response_model=list[str], responses=STALE_RESPONSES)
async def list_simulators():
    return await service.list_simulators()


@router.get("/car-classes", response_model=list[str], responses=STALE_RESPONSES)
async def list_car_classes(
    game_id: int | None = Query(None, alias="simgridGameId", description="SimGrid's numeric game id."),
):
    return await service.list_car_classes(game_id)

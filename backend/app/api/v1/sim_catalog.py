"""Simulator and car-class catalogues (from SimGrid) for calendar filters."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services import calendar_events as service

router = APIRouter(tags=["Calendar"])


@router.get("/simulators", response_model=list[str])
async def list_simulators():
    return await service.list_simulators()


@router.get("/car-classes", response_model=list[str])
async def list_car_classes(game_id: int | None = Query(None, alias="gameId")):
    return await service.list_car_classes(game_id)

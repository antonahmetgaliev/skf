"""Merged calendar of SimGrid and custom championships."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.openapi import STALE_RESPONSES
from app.database import get_db
from app.schemas.calendar import CalendarEvent
from app.services import calendar_events as service

router = APIRouter(tags=["Calendar"])


@router.get("/calendar-events", response_model=list[CalendarEvent], responses=STALE_RESPONSES)
async def list_calendar_events(
    year: int = Query(..., ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
):
    """SimGrid + custom championship events for a month, or the whole year."""
    return await service.list_calendar_events(db, year, month)

"""Merged calendar of SimGrid and custom championships."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.openapi import STALE_RESPONSES
from app.database import get_db
from app.schemas.calendar import CalendarEventOut
from app.services import calendar_events as service

router = APIRouter(tags=["Calendar"])


@router.get("/calendar-events", response_model=list[CalendarEventOut], responses=STALE_RESPONSES)
async def list_calendar_events(
    from_: date = Query(..., alias="from"),
    to: date = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """SimGrid + custom championship events between two dates, both included."""
    return await service.list_calendar_events(db, from_, to)

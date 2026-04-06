"""Incident management router."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user, require_admin, require_judge
from app.database import get_db
from app.models.incidents import Incident, IncidentResolution, IncidentWindow
from app.models.user import User
from app.schemas.incidents import (
    IncidentCreate,
    IncidentOut,
    IncidentWindowCreate,
    IncidentWindowListItem,
    IncidentWindowOut,
    IncidentWindowUpdate,
    ResolveIncident,
)

router = APIRouter(prefix="/incidents", tags=["Incidents"])


def _window_with_incidents_query():
    return select(IncidentWindow).options(
        selectinload(IncidentWindow.incidents).selectinload(Incident.resolution)
    )


async def _get_window_or_404(window_id: uuid.UUID, db: AsyncSession) -> IncidentWindow:
    result = await db.execute(
        _window_with_incidents_query().where(IncidentWindow.id == window_id)
    )
    window = result.scalar_one_or_none()
    if window is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Window not found."
        )
    return window


async def _get_incident_or_404(
    incident_id: uuid.UUID, db: AsyncSession
) -> Incident:
    result = await db.execute(
        select(Incident)
        .options(selectinload(Incident.resolution))
        .where(Incident.id == incident_id)
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found."
        )
    return incident


# ── Windows ─────────────────────────────────────────────────────────────────

@router.get("/windows", response_model=list[IncidentWindowListItem])
async def list_windows(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(IncidentWindow).order_by(IncidentWindow.opened_at.desc())
    )
    return result.scalars().all()


@router.post(
    "/windows",
    response_model=IncidentWindowOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_window(
    payload: IncidentWindowCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    now = datetime.now(timezone.utc)
    window = IncidentWindow(
        championship_id=payload.championship_id,
        championship_name=payload.championship_name,
        race_id=payload.race_id,
        race_name=payload.race_name,
        interval_hours=payload.interval_hours,
        opened_at=now,
        closes_at=now + timedelta(hours=payload.interval_hours),
        opened_by_user_id=_.id,
    )
    db.add(window)
    await db.commit()
    return await _get_window_or_404(window.id, db)


@router.get("/windows/{window_id}", response_model=IncidentWindowOut)
async def get_window(
    window_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return await _get_window_or_404(window_id, db)


@router.patch("/windows/{window_id}", response_model=IncidentWindowOut)
async def update_window(
    window_id: uuid.UUID,
    payload: IncidentWindowUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    window = await _get_window_or_404(window_id, db)
    if payload.is_manually_closed is not None:
        window.is_manually_closed = payload.is_manually_closed
    if payload.interval_hours is not None:
        window.interval_hours = payload.interval_hours
        window.closes_at = window.opened_at + timedelta(hours=payload.interval_hours)
    await db.commit()
    return await _get_window_or_404(window_id, db)


@router.delete(
    "/windows/{window_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_window(
    window_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    window = await _get_window_or_404(window_id, db)
    await db.delete(window)
    await db.commit()


# ── Incidents ────────────────────────────────────────────────────────────────

@router.post(
    "/windows/{window_id}/incidents",
    response_model=IncidentOut,
    status_code=status.HTTP_201_CREATED,
)
async def file_incident(
    window_id: uuid.UUID,
    payload: IncidentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    window = await _get_window_or_404(window_id, db)
    if not window.is_open:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This incident window is closed.",
        )
    incident = Incident(
        window_id=window.id,
        reporter_user_id=current_user.id,
        driver1_name=payload.driver1_name,
        driver1_driver_id=payload.driver1_driver_id,
        driver2_name=payload.driver2_name,
        driver2_driver_id=payload.driver2_driver_id,
        lap_number=payload.lap_number,
        turn=payload.turn,
        description=payload.description,
    )
    db.add(incident)
    await db.commit()
    return await _get_incident_or_404(incident.id, db)


@router.patch("/{incident_id}/resolve", response_model=IncidentOut)
async def resolve_incident(
    incident_id: uuid.UUID,
    payload: ResolveIncident,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    incident = await _get_incident_or_404(incident_id, db)
    if incident.resolution is not None:
        incident.resolution.verdict = payload.verdict
        incident.resolution.time_penalty_seconds = payload.time_penalty_seconds
        incident.resolution.bwp_points = payload.bwp_points
        incident.resolution.judge_user_id = _.id
        incident.resolution.resolved_at = datetime.now(timezone.utc)
    else:
        db.add(
            IncidentResolution(
                incident_id=incident.id,
                judge_user_id=_.id,
                verdict=payload.verdict,
                time_penalty_seconds=payload.time_penalty_seconds,
                bwp_points=payload.bwp_points,
            )
        )
    incident.status = "resolved"
    await db.commit()
    return await _get_incident_or_404(incident_id, db)


@router.patch("/{incident_id}/apply-bwp", response_model=IncidentOut)
async def apply_bwp(
    incident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    incident = await _get_incident_or_404(incident_id, db)
    if incident.resolution is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Incident has not been resolved yet.",
        )
    incident.resolution.bwp_applied = True
    await db.commit()
    return await _get_incident_or_404(incident_id, db)


@router.patch("/{incident_id}/unapply-bwp", response_model=IncidentOut)
async def unapply_bwp(
    incident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    incident = await _get_incident_or_404(incident_id, db)
    if incident.resolution is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Incident has not been resolved yet.",
        )
    incident.resolution.bwp_applied = False
    await db.commit()
    return await _get_incident_or_404(incident_id, db)

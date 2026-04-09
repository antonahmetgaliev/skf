"""Incident management router."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user, require_admin, require_api_token, require_judge
from app.database import get_db
from app.models.bwp import BwpPoint, Driver
from app.services.simgrid import simgrid_service
from app.models.incidents import (
    Incident, IncidentDriver, IncidentResolution, IncidentWindow, VerdictRule,
    DescriptionPreset,
)
from app.models.user import User
from app.schemas.incidents import (
    BulkResolveIncident,
    IncidentBatchCreate,
    IncidentFileCreate,
    IncidentOut,
    IncidentDriverOut,
    IncidentWindowCreate,
    IncidentWindowListItem,
    IncidentWindowOut,
    IncidentWindowUpdate,
    ResolveDriverIncident,
    VerdictRuleCreate,
    VerdictRuleOut,
    VerdictRuleUpdate,
    DescriptionPresetCreate,
    DescriptionPresetOut,
    DescriptionPresetUpdate,
)

router = APIRouter(prefix="/incidents", tags=["Incidents"])


# ── Query helpers ────────────────────────────────────────────────────────────

def _window_with_incidents_query():
    return select(IncidentWindow).options(
        selectinload(IncidentWindow.incidents)
        .selectinload(Incident.drivers)
        .selectinload(IncidentDriver.resolution)
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


async def _get_incident_driver_or_404(
    incident_driver_id: uuid.UUID, db: AsyncSession
) -> IncidentDriver:
    result = await db.execute(
        select(IncidentDriver)
        .options(selectinload(IncidentDriver.resolution))
        .where(IncidentDriver.id == incident_driver_id)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Incident driver not found."
        )
    return entry


async def _match_driver(name: str, db: AsyncSession) -> uuid.UUID | None:
    """Case-insensitive match of driver name against BWP Driver table."""
    result = await db.execute(
        select(Driver.id).where(func.lower(Driver.name) == name.lower())
    )
    row = result.scalar_one_or_none()
    return row


async def _update_incident_status(incident_id: uuid.UUID, db: AsyncSession) -> None:
    """Set incident status to 'resolved' when all its drivers have resolutions."""
    # Expire any cached Incident so we get fresh relationship data
    result = await db.execute(
        select(Incident).where(Incident.id == incident_id)
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        return
    # Refresh drivers + their resolutions
    await db.refresh(incident, attribute_names=["drivers"])
    for d in incident.drivers:
        await db.refresh(d, attribute_names=["resolution"])
    all_resolved = all(d.resolution is not None for d in incident.drivers)
    incident.status = "resolved" if all_resolved else "open"


# ── Verdict rules ────────────────────────────────────────────────────────────

@router.get("/verdict-rules", response_model=list[VerdictRuleOut])
async def list_verdict_rules(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(VerdictRule).order_by(VerdictRule.sort_order)
    )
    return result.scalars().all()


@router.post(
    "/verdict-rules",
    response_model=VerdictRuleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_verdict_rule(
    payload: VerdictRuleCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    # Auto-set sort_order to max + 1
    result = await db.execute(select(func.coalesce(func.max(VerdictRule.sort_order), 0)))
    max_order = result.scalar_one()
    rule = VerdictRule(
        verdict=payload.verdict,
        default_bwp=payload.default_bwp,
        sort_order=max_order + 1,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/verdict-rules/{rule_id}", response_model=VerdictRuleOut)
async def update_verdict_rule(
    rule_id: uuid.UUID,
    payload: VerdictRuleUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    result = await db.execute(select(VerdictRule).where(VerdictRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verdict rule not found.")
    if payload.verdict is not None:
        rule.verdict = payload.verdict
    if payload.default_bwp is not None:
        rule.default_bwp = payload.default_bwp
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/verdict-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_verdict_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    result = await db.execute(select(VerdictRule).where(VerdictRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verdict rule not found.")
    await db.delete(rule)
    await db.commit()


# ── Description presets ──────────────────────────────────────────────────────

@router.get("/description-presets", response_model=list[DescriptionPresetOut])
async def list_description_presets(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DescriptionPreset).order_by(DescriptionPreset.sort_order)
    )
    return result.scalars().all()


@router.post(
    "/description-presets",
    response_model=DescriptionPresetOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_description_preset(
    payload: DescriptionPresetCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    result = await db.execute(
        select(func.coalesce(func.max(DescriptionPreset.sort_order), 0))
    )
    max_order = result.scalar_one()
    preset = DescriptionPreset(text=payload.text, sort_order=max_order + 1)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.patch("/description-presets/{preset_id}", response_model=DescriptionPresetOut)
async def update_description_preset(
    preset_id: uuid.UUID,
    payload: DescriptionPresetUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    result = await db.execute(
        select(DescriptionPreset).where(DescriptionPreset.id == preset_id)
    )
    preset = result.scalar_one_or_none()
    if preset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Description preset not found.")
    if payload.text is not None:
        preset.text = payload.text
    await db.commit()
    await db.refresh(preset)
    return preset


@router.delete("/description-presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_description_preset(
    preset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    result = await db.execute(
        select(DescriptionPreset).where(DescriptionPreset.id == preset_id)
    )
    preset = result.scalar_one_or_none()
    if preset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Description preset not found.")
    await db.delete(preset)
    await db.commit()


# ── Batch ingestion (token-auth'd) ──────────────────────────────────────────

@router.post(
    "/ingest",
    response_model=IncidentWindowOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_token)],
)
async def ingest_incidents(
    payload: IncidentBatchCreate,
    db: AsyncSession = Depends(get_db),
):
    # Find or create window by race_id
    q = select(IncidentWindow).where(IncidentWindow.race_id == payload.race_id)
    result = await db.execute(q)
    window = result.scalar_one_or_none()

    if window is None:
        race_name = await simgrid_service.get_race_name(payload.race_id)
        today = date.today().isoformat()
        now = datetime.now(timezone.utc)
        window = IncidentWindow(
            championship_id=payload.championship_id,
            race_id=payload.race_id,
            race_name=race_name,
            date=today,
            interval_hours=24,
            opened_at=now,
            closes_at=now + timedelta(hours=24),
        )
        db.add(window)
        await db.flush()

    # Create incidents + drivers
    for inc_data in payload.incidents:
        incident = Incident(
            window_id=window.id,
            session_name=inc_data.session_name,
            time=inc_data.time,
        )
        db.add(incident)
        await db.flush()

        for idx, driver_name in enumerate(inc_data.drivers):
            driver_id = await _match_driver(driver_name, db)
            db.add(IncidentDriver(
                incident_id=incident.id,
                driver_name=driver_name,
                driver_id=driver_id,
                sort_order=idx,
            ))

    await db.commit()

    # Expire cached window so selectinload re-fetches all incidents
    await db.refresh(window, attribute_names=["incidents"])
    return await _get_window_or_404(window.id, db)


# ── Windows ──────────────────────────────────────────────────────────────────

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
    user: User = Depends(require_admin),
):
    now = datetime.now(timezone.utc)
    window = IncidentWindow(
        championship_id=payload.championship_id,
        championship_name=payload.championship_name,
        race_id=payload.race_id,
        race_name=payload.race_name,
        date=payload.date,
        interval_hours=payload.interval_hours,
        opened_at=now,
        closes_at=now + timedelta(hours=payload.interval_hours),
        opened_by_user_id=user.id,
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


@router.delete("/windows/{window_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_window(
    window_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    window = await _get_window_or_404(window_id, db)
    await db.delete(window)
    await db.commit()


# ── Manual file incident ────────────────────────────────────────────────────

@router.post(
    "/windows/{window_id}/incidents",
    response_model=IncidentOut,
    status_code=status.HTTP_201_CREATED,
)
async def file_incident(
    window_id: uuid.UUID,
    payload: IncidentFileCreate,
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
        session_name=payload.session_name,
        time=payload.time,
        description=payload.description,
    )
    db.add(incident)
    await db.flush()

    for idx, driver_name in enumerate(payload.drivers):
        driver_id = await _match_driver(driver_name, db)
        db.add(IncidentDriver(
            incident_id=incident.id,
            driver_name=driver_name,
            driver_id=driver_id,
            sort_order=idx,
        ))

    await db.commit()

    # Reload with relationships
    result = await db.execute(
        select(Incident)
        .options(selectinload(Incident.drivers).selectinload(IncidentDriver.resolution))
        .where(Incident.id == incident.id)
    )
    return result.scalar_one()


# ── Per-driver resolve ──────────────────────────────────────────────────────

@router.patch(
    "/drivers/{incident_driver_id}/resolve",
    response_model=IncidentDriverOut,
)
async def resolve_driver(
    incident_driver_id: uuid.UUID,
    payload: ResolveDriverIncident,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_judge),
):
    entry = await _get_incident_driver_or_404(incident_driver_id, db)
    if entry.resolution is not None:
        entry.resolution.verdict = payload.verdict
        entry.resolution.bwp_points = payload.bwp_points
        entry.resolution.judge_user_id = user.id
        entry.resolution.resolved_at = datetime.now(timezone.utc)
    else:
        db.add(IncidentResolution(
            incident_driver_id=entry.id,
            judge_user_id=user.id,
            verdict=payload.verdict,
            bwp_points=payload.bwp_points,
        ))

    await db.flush()
    await _update_incident_status(entry.incident_id, db)
    await db.commit()

    # Refresh to pick up newly created resolution
    await db.refresh(entry, attribute_names=["resolution"])
    return entry


# ── Bulk resolve (one button per incident) ───────────────────────────────────

@router.patch(
    "/{incident_id}/resolve",
    response_model=IncidentOut,
)
async def bulk_resolve_incident(
    incident_id: uuid.UUID,
    payload: BulkResolveIncident,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_judge),
):
    # Verify incident exists
    result = await db.execute(
        select(Incident)
        .options(selectinload(Incident.drivers).selectinload(IncidentDriver.resolution))
        .where(Incident.id == incident_id)
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")

    driver_map = {d.id: d for d in incident.drivers}
    now = datetime.now(timezone.utc)

    for drv_payload in payload.drivers:
        entry = driver_map.get(drv_payload.incident_driver_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Driver {drv_payload.incident_driver_id} not in this incident.",
            )
        if entry.resolution is not None:
            entry.resolution.verdict = drv_payload.verdict
            entry.resolution.bwp_points = drv_payload.bwp_points
            entry.resolution.description = payload.description
            entry.resolution.judge_user_id = user.id
            entry.resolution.resolved_at = now
        else:
            db.add(IncidentResolution(
                incident_driver_id=entry.id,
                judge_user_id=user.id,
                verdict=drv_payload.verdict,
                bwp_points=drv_payload.bwp_points,
                description=payload.description,
            ))

    await db.flush()
    await _update_incident_status(incident_id, db)
    await db.commit()

    # Reload
    result = await db.execute(
        select(Incident)
        .options(selectinload(Incident.drivers).selectinload(IncidentDriver.resolution))
        .where(Incident.id == incident_id)
    )
    return result.scalar_one()


# ── BWP apply / discard ─────────────────────────────────────────────────────

@router.patch(
    "/drivers/{incident_driver_id}/apply-bwp",
    response_model=IncidentDriverOut,
)
async def apply_bwp(
    incident_driver_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    entry = await _get_incident_driver_or_404(incident_driver_id, db)
    if entry.resolution is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver has not been resolved yet.",
        )
    if not entry.resolution.bwp_points:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No BWP points to apply.",
        )
    entry.resolution.bwp_applied = True

    # Auto-create BwpPoint if driver is linked
    if entry.driver_id:
        today = date.today()
        db.add(BwpPoint(
            driver_id=entry.driver_id,
            points=entry.resolution.bwp_points,
            issued_on=today,
            expires_on=today + timedelta(days=90),
        ))

    await db.commit()
    return await _get_incident_driver_or_404(incident_driver_id, db)


@router.patch(
    "/drivers/{incident_driver_id}/discard",
    response_model=IncidentDriverOut,
)
async def discard_bwp(
    incident_driver_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    entry = await _get_incident_driver_or_404(incident_driver_id, db)
    if entry.resolution is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver has not been resolved yet.",
        )
    entry.resolution.bwp_points = None
    entry.resolution.bwp_applied = False
    await db.commit()
    return await _get_incident_driver_or_404(incident_driver_id, db)

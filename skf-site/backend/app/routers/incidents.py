"""Incident management router."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user, get_current_user_optional, require_admin, require_api_token, require_judge
from app.database import get_db
from app.models.bwp import BwpPoint, Driver
from app.services.driver_matching import match_driver_id_by_name
from app.services.incident_bwp import apply_resolution_bwp
from app.services.race_import import add_ingested_incidents, find_or_create_window
from app.models.incidents import (
    Incident, IncidentDriver, IncidentResolution, IncidentWindow, VerdictRule,
    DescriptionPreset,
)
from app.models.user import User
from app.schemas.incidents import (
    BulkResolveIncident,
    IncidentBatchCreate,
    IncidentDriverAdd,
    IncidentDriverLink,
    IncidentFileCreate,
    IncidentOut,
    IncidentDriverOut,
    IncidentWindowCreate,
    IncidentWindowListItem,
    IncidentWindowOut,
    IncidentWindowUpdate,
    PublishWindowOut,
    ResolveRemainingOut,
    ResolveDriverIncident,
    VerdictRuleCreate,
    VerdictRuleOut,
    VerdictRuleReorder,
    VerdictRuleUpdate,
    DescriptionPresetCreate,
    DescriptionPresetOut,
    DescriptionPresetUpdate,
    BwpAuditEntry,
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
    return await match_driver_id_by_name(db, name)


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


async def _promote_default_rule(rule_id: uuid.UUID, db: AsyncSession) -> None:
    """Make *rule_id* the one default verdict.

    Clear-then-set as two statements so the partial unique index is satisfied
    at every statement boundary, not just at commit.
    """
    await db.execute(
        update(VerdictRule)
        .where(VerdictRule.is_default.is_(True))
        .values(is_default=False)
    )
    await db.flush()
    await db.execute(
        update(VerdictRule).where(VerdictRule.id == rule_id).values(is_default=True)
    )


async def _get_default_verdict_rule(db: AsyncSession) -> VerdictRule | None:
    result = await db.execute(
        select(VerdictRule).where(VerdictRule.is_default.is_(True))
    )
    return result.scalar_one_or_none()


# ── Verdict rules ────────────────────────────────────────────────────────────

@router.get("/verdict-rules", response_model=list[VerdictRuleOut])
async def list_verdict_rules(
    db: AsyncSession = Depends(get_db),
    # The catalogue is public knowledge — it is printed in the regulations, and
    # every viewer needs the default rule to tell a penalty from "no action".
    _: User | None = Depends(get_current_user_optional),
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
    await db.flush()
    if payload.is_default:
        await _promote_default_rule(rule.id, db)
    await db.commit()
    await db.refresh(rule)
    return rule


# Registered before the parameterised route so "order" is never read as an id.
@router.put("/verdict-rules/order", response_model=list[VerdictRuleOut])
async def reorder_verdict_rules(
    payload: VerdictRuleReorder,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    """Reassign sort_order to match the given id order.

    sort_order has always existed and has always been the ORDER BY, but until
    now the only way to change it was to delete a rule and recreate it.
    """
    for index, rule_id in enumerate(payload.ids):
        await db.execute(
            update(VerdictRule).where(VerdictRule.id == rule_id).values(sort_order=index)
        )
    await db.commit()
    result = await db.execute(select(VerdictRule).order_by(VerdictRule.sort_order))
    return result.scalars().all()


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
    if payload.is_default is False:
        # Demoting directly would leave the league with no default at all.
        # The only way out of default is for another rule to take the role.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set another verdict rule as the default instead.",
        )
    if payload.is_default:
        await _promote_default_rule(rule.id, db)
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
    if rule.is_default:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Set another verdict rule as the default before deleting this one.",
        )
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
    """Deprecated: kept while the desktop parsers are phased out.

    Admins now upload the round's result file in the Race results tab and
    the backend parses the contacts itself (`services/race_import.py`).
    """
    window = await find_or_create_window(
        db, race_id=payload.race_id, championship_id=payload.championship_id
    )
    await add_ingested_incidents(db, window, payload.incidents)
    await db.commit()

    # Expire cached window so selectinload re-fetches all incidents
    await db.refresh(window, attribute_names=["incidents"])
    return await _get_window_or_404(window.id, db)


# ── Windows ──────────────────────────────────────────────────────────────────

@router.get("/windows", response_model=list[IncidentWindowListItem])
async def list_windows(
    championship_id: int | None = Query(None, alias="championshipId"),
    db: AsyncSession = Depends(get_db),
):
    query = select(IncidentWindow).order_by(IncidentWindow.opened_at.desc())
    if championship_id is not None:
        query = query.where(IncidentWindow.championship_id == championship_id)
    result = await db.execute(query)
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
    if payload.race_id is not None:
        existing = await db.execute(
            select(IncidentWindow.id).where(IncidentWindow.race_id == payload.race_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This race already has an incident window.",
            )
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
    current_user: User | None = Depends(get_current_user_optional),
):
    window = await _get_window_or_404(window_id, db)
    # Non-judges see all incidents but verdicts are hidden on unpublished ones
    is_judge = (
        current_user is not None
        and current_user.role is not None
        and current_user.role.name in ("racing_judge", "admin", "super_admin")
    )
    if not is_judge:
        for inc in window.incidents:
            if not inc.is_published:
                for drv in inc.drivers:
                    drv.resolution = None
    return window


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
    current_user: User | None = Depends(get_current_user_optional),
):
    window = await _get_window_or_404(window_id, db)
    if not window.is_open:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This incident window is closed.",
        )
    incident = Incident(
        window_id=window.id,
        reporter_user_id=current_user.id if current_user else None,
        session_name=payload.session_name,
        lap=payload.lap,
        corner=payload.corner,
        description=payload.description,
    )
    db.add(incident)
    await db.flush()

    for idx, driver_name in enumerate(payload.drivers):
        driver_id = await _match_driver(driver_name, db)
        db.add(IncidentDriver(
            incident_id=incident.id,
            driver_name=driver_name.strip(),
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


# ── Duplicate incident ──────────────────────────────────────────────────────

@router.post(
    "/{incident_id}/duplicate",
    response_model=IncidentOut,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_incident(
    incident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_judge),
):
    result = await db.execute(
        select(Incident)
        .options(selectinload(Incident.drivers))
        .where(Incident.id == incident_id)
    )
    src = result.scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")

    new_inc = Incident(
        window_id=src.window_id,
        reporter_user_id=user.id,
        session_name=src.session_name,
        time=src.time,
        lap=src.lap,
        corner=src.corner,
        description=src.description,
        source=src.source,
        is_published=src.is_published,
    )
    db.add(new_inc)
    await db.flush()

    for drv in src.drivers:
        db.add(IncidentDriver(
            incident_id=new_inc.id,
            driver_name=drv.driver_name,
            driver_id=drv.driver_id,
            sort_order=drv.sort_order,
        ))

    await db.commit()

    result = await db.execute(
        select(Incident)
        .options(selectinload(Incident.drivers).selectinload(IncidentDriver.resolution))
        .where(Incident.id == new_inc.id)
    )
    return result.scalar_one()


# ── Add / remove driver from incident ──────────────────────────────────────

@router.post(
    "/{incident_id}/drivers",
    response_model=IncidentOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_driver_to_incident(
    incident_id: uuid.UUID,
    payload: IncidentDriverAdd,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    result = await db.execute(
        select(Incident)
        .options(selectinload(Incident.drivers).selectinload(IncidentDriver.resolution))
        .where(Incident.id == incident_id)
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")

    max_order = max((d.sort_order for d in incident.drivers), default=-1)
    driver_id = await _match_driver(payload.driver_name, db)
    db.add(IncidentDriver(
        incident_id=incident.id,
        driver_name=payload.driver_name.strip(),
        driver_id=driver_id,
        sort_order=max_order + 1,
    ))
    await db.commit()
    db.expire(incident)  # expire_on_commit=False means we must force a fresh reload

    result = await db.execute(
        select(Incident)
        .options(selectinload(Incident.drivers).selectinload(IncidentDriver.resolution))
        .where(Incident.id == incident_id)
    )
    return result.scalar_one()


@router.delete(
    "/drivers/{incident_driver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_driver_from_incident(
    incident_driver_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    entry = await _get_incident_driver_or_404(incident_driver_id, db)
    await db.delete(entry)
    await db.commit()


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

    # One lookup per request, and only when something actually needs it.
    default_rule: VerdictRule | None = None
    if any(p.verdict is None for p in payload.drivers):
        default_rule = await _get_default_verdict_rule(db)
        if default_rule is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No default verdict is configured.",
            )

    # Only touch the description when it was actually sent. Writing it
    # unconditionally let a partial save blank the text for the whole incident.
    description_sent = "description" in payload.model_fields_set

    for drv_payload in payload.drivers:
        entry = driver_map.get(drv_payload.incident_driver_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Driver {drv_payload.incident_driver_id} not in this incident.",
            )
        # Store the verdict *text*, never a reference: a published verdict must
        # not change when the rule is later renamed or re-priced.
        if drv_payload.verdict is None:
            verdict = default_rule.verdict
            bwp_points = default_rule.default_bwp
        else:
            verdict = drv_payload.verdict
            bwp_points = drv_payload.bwp_points

        if entry.resolution is not None:
            entry.resolution.verdict = verdict
            entry.resolution.bwp_points = bwp_points
            if description_sent:
                entry.resolution.description = payload.description
            entry.resolution.judge_user_id = user.id
            entry.resolution.resolved_at = now
        else:
            db.add(IncidentResolution(
                incident_driver_id=entry.id,
                judge_user_id=user.id,
                verdict=verdict,
                bwp_points=bwp_points,
                description=payload.description if description_sent else None,
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


# ── Resolve everything still open in a window ────────────────────────────────

@router.post(
    "/windows/{window_id}/resolve-remaining",
    response_model=ResolveRemainingOut,
)
async def resolve_remaining_in_window(
    window_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_judge),
):
    """Apply the default verdict to every driver in the window still awaiting one.

    One request for the whole round rather than one per incident: a steward
    closing out a race weekend should not be firing dozens of calls, and this
    way the round is resolved atomically or not at all. Drivers that already
    have a resolution are left exactly as the judge left them.
    """
    window = await _get_window_or_404(window_id, db)

    unresolved = [
        drv
        for incident in window.incidents
        for drv in incident.drivers
        if drv.resolution is None
    ]
    if not unresolved:
        return ResolveRemainingOut(
            **IncidentWindowOut.model_validate(window).model_dump(by_alias=False),
            resolved_count=0,
        )

    default_rule = await _get_default_verdict_rule(db)
    if default_rule is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No default verdict is configured.",
        )

    for drv in unresolved:
        db.add(IncidentResolution(
            incident_driver_id=drv.id,
            judge_user_id=user.id,
            # The verdict text, never a reference — renaming the rule later
            # must not rewrite decisions already handed down.
            verdict=default_rule.verdict,
            bwp_points=default_rule.default_bwp,
        ))

    await db.flush()
    for incident in window.incidents:
        await _update_incident_status(incident.id, db)
    await db.commit()

    db.expire(window)
    result = await db.execute(
        _window_with_incidents_query().where(IncidentWindow.id == window_id)
    )
    refreshed = result.scalar_one()
    return ResolveRemainingOut(
        **IncidentWindowOut.model_validate(refreshed).model_dump(by_alias=False),
        resolved_count=len(unresolved),
    )


# ── Publish all incidents in a window ────────────────────────────────────────

@router.post(
    "/windows/{window_id}/publish-all",
    response_model=PublishWindowOut,
)
async def publish_all_incidents(
    window_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    """Reveal every verdict in the window and issue the BWP they carry.

    Publishing is the single point where verdicts become visible and penalties
    reach licences, so both happen in one transaction. Re-publishing is safe:
    apply_resolution_bwp short-circuits on already-applied resolutions.
    """
    window = await _get_window_or_404(window_id, db)
    if not window.incidents:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This window has no incidents to publish.",
        )

    unlinked = 0
    for incident in window.incidents:
        incident.is_published = True
        for drv in incident.drivers:
            await apply_resolution_bwp(drv, db)
            res = drv.resolution
            if res is not None and res.bwp_points and not res.bwp_applied:
                unlinked += 1

    await db.commit()
    db.expire(window)
    result = await db.execute(
        select(IncidentWindow)
        .options(
            selectinload(IncidentWindow.incidents)
            .selectinload(Incident.drivers)
            .selectinload(IncidentDriver.resolution)
        )
        .where(IncidentWindow.id == window_id)
    )
    published = result.scalar_one()
    return PublishWindowOut(
        **IncidentWindowOut.model_validate(published).model_dump(by_alias=False),
        unlinked_count=unlinked,
    )


# ── Link an incident driver to a driver record ───────────────────────────────

@router.patch(
    "/drivers/{incident_driver_id}/link",
    response_model=IncidentDriverOut,
)
async def link_incident_driver(
    incident_driver_id: uuid.UUID,
    payload: IncidentDriverLink,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    """Attach a free-text incident driver to an actual driver record.

    Names arrive as free text from the ingest bot and from whoever files an
    incident, and are matched by exact (case-insensitive) equality. Anything
    the matcher misses — a typo, a nickname, a transliteration — needs a human
    to say who this is; backfill cannot, because it matches by the same rule
    that already failed.
    """
    entry = await _get_incident_driver_or_404(incident_driver_id, db)
    driver = await db.get(Driver, payload.driver_id)
    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found."
        )
    entry.driver_id = driver.id
    await db.commit()
    return await _get_incident_driver_or_404(incident_driver_id, db)


# ── BWP audit / backfill ─────────────────────────────────────────────────────

@router.get("/bwp-audit", response_model=list[BwpAuditEntry])
async def bwp_audit(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return incident drivers where BWP was applied but no BwpPoint was created.

    This happens when the incident driver had no driver_id link at apply time.
    """
    rows = await db.execute(
        select(IncidentDriver, Driver)
        .join(IncidentResolution, IncidentResolution.incident_driver_id == IncidentDriver.id)
        .outerjoin(Driver, func.lower(Driver.name) == func.lower(IncidentDriver.driver_name))
        .where(IncidentResolution.bwp_applied == True)  # noqa: E712
        .where(IncidentDriver.driver_id.is_(None))
    )
    return [
        BwpAuditEntry(
            incident_driver_id=inc_drv.id,
            driver_name=inc_drv.driver_name,
            bwp_points=inc_drv.resolution.bwp_points or 0,
            matched_driver_id=drv.id if drv else None,
            matched_driver_name=drv.name if drv else None,
        )
        for inc_drv, drv in rows.all()
    ]


@router.post("/bwp-backfill", response_model=dict)
async def bwp_backfill(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Create missing BwpPoints for applied incident BWPs where driver_id was NULL.

    For each unlinked IncidentDriver where bwp_applied=True, if the driver_name
    can be matched to a Driver by name, creates the missing BwpPoint, links
    driver_id, and returns a summary.
    """
    rows = await db.execute(
        select(IncidentDriver, Driver)
        .join(IncidentResolution, IncidentResolution.incident_driver_id == IncidentDriver.id)
        .outerjoin(Driver, func.lower(Driver.name) == func.lower(IncidentDriver.driver_name))
        .where(IncidentResolution.bwp_applied == True)  # noqa: E712
        .where(IncidentDriver.driver_id.is_(None))
    )
    fixed = 0
    unmatched: list[str] = []
    for inc_drv, drv in rows.all():
        if drv is None:
            if inc_drv.driver_name not in unmatched:
                unmatched.append(inc_drv.driver_name)
            continue
        # Link and create the missing BwpPoint
        inc_drv.driver_id = drv.id
        bwp_pts = inc_drv.resolution.bwp_points or 0
        if bwp_pts:
            today = date.today()
            point = BwpPoint(
                driver_id=drv.id,
                points=bwp_pts,
                issued_on=today,
                expires_on=today + timedelta(days=90),
            )
            db.add(point)
            await db.flush()
            # Without this link the backfilled point could never be traced
            # back to the resolution that caused it.
            inc_drv.resolution.applied_bwp_point_id = point.id
        fixed += 1

    await db.commit()
    return {"fixed": fixed, "unmatched": unmatched}

"""Incident windows, incidents, verdicts and the BWP they carry.

Routers only parse requests and shape responses; everything that decides
something lives here. Functions that change data commit, except where noted.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import is_admin
from app.core.errors import BadRequest, Conflict, NotFound, Unprocessable
from app.models.bwp import Driver
from app.models.incidents import (
    DescriptionPreset,
    Incident,
    IncidentDriver,
    IncidentResolution,
    IncidentWindow,
    VerdictRule,
)
from app.models.user import ROLE_JUDGE, User
from app.repository import get_or_404
from app.schemas.incidents import (
    BulkResolveIncident,
    BwpAuditEntry,
    BwpBackfillOut,
    DescriptionPresetCreate,
    DescriptionPresetUpdate,
    IncidentFileCreate,
    IncidentWindowCreate,
    IncidentWindowUpdate,
    ResolveDriverIncident,
    VerdictRuleCreate,
    VerdictRuleUpdate,
)
from app.services.driver_matching import match_driver_id_by_name
from app.services.incident_bwp import apply_resolution_bwp


def can_see_verdicts(user: User | None) -> bool:
    """Judges and admins see verdicts before they are published."""
    return is_admin(user) or (user is not None and user.role is not None and user.role.name == ROLE_JUDGE)


# ── Loading ──────────────────────────────────────────────────────────────────

_INCIDENT_TREE = selectinload(Incident.drivers).selectinload(IncidentDriver.resolution)


def _window_query() -> Select:
    return select(IncidentWindow).options(
        selectinload(IncidentWindow.incidents)
        .selectinload(Incident.drivers)
        .selectinload(IncidentDriver.resolution)
    )


async def load_window(db: AsyncSession, window_id: uuid.UUID) -> IncidentWindow:
    """The window with every incident, driver and resolution, freshly read."""
    window = (
        await db.execute(
            _window_query()
            .where(IncidentWindow.id == window_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if window is None:
        raise NotFound("Window not found.")
    return window


async def load_incident(db: AsyncSession, incident_id: uuid.UUID) -> Incident:
    """The incident with its drivers and resolutions, freshly read."""
    incident = (
        await db.execute(
            select(Incident)
            .options(_INCIDENT_TREE)
            .where(Incident.id == incident_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if incident is None:
        raise NotFound("Incident not found.")
    return incident


async def load_incident_driver(db: AsyncSession, incident_driver_id: uuid.UUID) -> IncidentDriver:
    entry = (
        await db.execute(
            select(IncidentDriver)
            .options(selectinload(IncidentDriver.resolution))
            .where(IncidentDriver.id == incident_driver_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if entry is None:
        raise NotFound("Incident driver not found.")
    return entry


async def update_incident_status(db: AsyncSession, incident_id: uuid.UUID) -> None:
    """``resolved`` once the incident has drivers and every one has a verdict."""
    incident = await db.get(Incident, incident_id)
    if incident is None:
        return
    total, unresolved = (
        await db.execute(
            select(
                func.count(IncidentDriver.id),
                func.count(IncidentDriver.id).filter(IncidentResolution.id.is_(None)),
            )
            .outerjoin(IncidentResolution, IncidentResolution.incident_driver_id == IncidentDriver.id)
            .where(IncidentDriver.incident_id == incident_id)
        )
    ).one()
    incident.status = "resolved" if total and not unresolved else "open"


# ── Verdict rules ────────────────────────────────────────────────────────────

async def list_verdict_rules(db: AsyncSession) -> list[VerdictRule]:
    return list((await db.execute(select(VerdictRule).order_by(VerdictRule.sort_order))).scalars().all())


async def _promote_default_rule(db: AsyncSession, rule_id: uuid.UUID) -> None:
    """Make *rule_id* the one default verdict.

    Clear-then-set as two statements so the partial unique index is satisfied
    at every statement boundary, not just at commit.
    """
    await db.execute(update(VerdictRule).where(VerdictRule.is_default.is_(True)).values(is_default=False))
    await db.flush()
    await db.execute(update(VerdictRule).where(VerdictRule.id == rule_id).values(is_default=True))


async def _default_rule(db: AsyncSession) -> VerdictRule:
    rule = (await db.execute(select(VerdictRule).where(VerdictRule.is_default.is_(True)))).scalar_one_or_none()
    if rule is None:
        raise Conflict("No default verdict is configured.")
    return rule


async def create_verdict_rule(db: AsyncSession, payload: VerdictRuleCreate) -> VerdictRule:
    max_order = await db.scalar(select(func.coalesce(func.max(VerdictRule.sort_order), 0)))
    rule = VerdictRule(verdict=payload.verdict, default_bwp=payload.default_bwp, sort_order=max_order + 1)
    db.add(rule)
    await db.flush()
    if payload.is_default:
        await _promote_default_rule(db, rule.id)
    await db.commit()
    await db.refresh(rule)
    return rule


async def reorder_verdict_rules(db: AsyncSession, ids: list[uuid.UUID]) -> list[VerdictRule]:
    """Reassign sort_order to match the given id order."""
    existing = set((await db.execute(select(VerdictRule.id))).scalars().all())
    if len(ids) != len(set(ids)) or set(ids) != existing:
        raise Unprocessable("The order must list every verdict rule exactly once.")
    if ids:
        await db.execute(
            update(VerdictRule).values(
                sort_order=case({rule_id: i for i, rule_id in enumerate(ids)}, value=VerdictRule.id)
            )
        )
    await db.commit()
    return await list_verdict_rules(db)


async def update_verdict_rule(db: AsyncSession, rule_id: uuid.UUID, payload: VerdictRuleUpdate) -> VerdictRule:
    rule = await get_or_404(db, VerdictRule, rule_id)
    if payload.is_default is False:
        # Demoting directly would leave the league with no default at all.
        # The only way out of default is for another rule to take the role.
        raise BadRequest("Set another verdict rule as the default instead.")
    if payload.verdict is not None:
        rule.verdict = payload.verdict
    if payload.default_bwp is not None:
        rule.default_bwp = payload.default_bwp
    if payload.is_default:
        await _promote_default_rule(db, rule.id)
    await db.commit()
    await db.refresh(rule)
    return rule


async def delete_verdict_rule(db: AsyncSession, rule_id: uuid.UUID) -> None:
    rule = await get_or_404(db, VerdictRule, rule_id)
    if rule.is_default:
        raise Conflict("Set another verdict rule as the default before deleting this one.")
    await db.delete(rule)
    await db.commit()


# ── Description presets ──────────────────────────────────────────────────────

async def list_description_presets(db: AsyncSession) -> list[DescriptionPreset]:
    return list(
        (await db.execute(select(DescriptionPreset).order_by(DescriptionPreset.sort_order))).scalars().all()
    )


async def create_description_preset(db: AsyncSession, payload: DescriptionPresetCreate) -> DescriptionPreset:
    max_order = await db.scalar(select(func.coalesce(func.max(DescriptionPreset.sort_order), 0)))
    preset = DescriptionPreset(text=payload.text, sort_order=max_order + 1)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


async def update_description_preset(
    db: AsyncSession, preset_id: uuid.UUID, payload: DescriptionPresetUpdate
) -> DescriptionPreset:
    preset = await get_or_404(db, DescriptionPreset, preset_id)
    if payload.text is not None:
        preset.text = payload.text
    await db.commit()
    await db.refresh(preset)
    return preset


async def delete_description_preset(db: AsyncSession, preset_id: uuid.UUID) -> None:
    preset = await get_or_404(db, DescriptionPreset, preset_id)
    await db.delete(preset)
    await db.commit()


# ── Windows ──────────────────────────────────────────────────────────────────

def list_windows_query(championship_id: int | None = None) -> Select:
    query = select(IncidentWindow).order_by(IncidentWindow.opened_at.desc())
    if championship_id is not None:
        query = query.where(IncidentWindow.championship_id == championship_id)
    return query


async def create_window(db: AsyncSession, payload: IncidentWindowCreate, user: User) -> IncidentWindow:
    if payload.race_id is not None:
        existing = await db.scalar(select(IncidentWindow.id).where(IncidentWindow.race_id == payload.race_id))
        if existing is not None:
            raise Conflict("This race already has an incident window.")
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
    return await load_window(db, window.id)


async def update_window(db: AsyncSession, window_id: uuid.UUID, payload: IncidentWindowUpdate) -> IncidentWindow:
    window = await get_or_404(db, IncidentWindow, window_id, detail="Window not found.")
    if payload.is_manually_closed is not None:
        window.is_manually_closed = payload.is_manually_closed
    if payload.interval_hours is not None:
        window.interval_hours = payload.interval_hours
        window.closes_at = window.opened_at + timedelta(hours=payload.interval_hours)
    await db.commit()
    return await load_window(db, window_id)


async def delete_window(db: AsyncSession, window_id: uuid.UUID) -> None:
    window = await load_window(db, window_id)
    await db.delete(window)
    await db.commit()


# ── Incidents ────────────────────────────────────────────────────────────────

async def file_incident(
    db: AsyncSession, window_id: uuid.UUID, payload: IncidentFileCreate, reporter: User | None
) -> Incident:
    window = await get_or_404(db, IncidentWindow, window_id, detail="Window not found.")
    if not window.is_open:
        raise Conflict("This incident window is closed.")
    incident = Incident(
        window_id=window.id,
        reporter_user_id=reporter.id if reporter else None,
        session_name=payload.session_name,
        lap=payload.lap,
        corner=payload.corner,
        description=payload.description,
    )
    db.add(incident)
    await db.flush()
    for idx, driver_name in enumerate(payload.drivers):
        db.add(IncidentDriver(
            incident_id=incident.id,
            driver_name=driver_name.strip(),
            driver_id=await match_driver_id_by_name(db, driver_name),
            sort_order=idx,
        ))
    await db.commit()
    return await load_incident(db, incident.id)


async def copy_incident(db: AsyncSession, incident_id: uuid.UUID, user: User) -> Incident:
    """A fresh, unresolved copy of the incident with the same drivers.

    The copy is always unpublished: it has no verdicts yet, and publishing is
    something a whole window goes through, not a side effect of copying.
    """
    src = await load_incident(db, incident_id)
    copy = Incident(
        window_id=src.window_id,
        reporter_user_id=user.id,
        session_name=src.session_name,
        time=src.time,
        lap=src.lap,
        corner=src.corner,
        description=src.description,
        source=src.source,
        is_published=False,
    )
    db.add(copy)
    await db.flush()
    for drv in src.drivers:
        db.add(IncidentDriver(
            incident_id=copy.id,
            driver_name=drv.driver_name,
            driver_id=drv.driver_id,
            sort_order=drv.sort_order,
        ))
    await db.commit()
    return await load_incident(db, copy.id)


async def add_driver(db: AsyncSession, incident_id: uuid.UUID, driver_name: str) -> IncidentDriver:
    incident = await load_incident(db, incident_id)
    entry = IncidentDriver(
        incident_id=incident.id,
        driver_name=driver_name.strip(),
        driver_id=await match_driver_id_by_name(db, driver_name),
        sort_order=max((d.sort_order for d in incident.drivers), default=-1) + 1,
    )
    db.add(entry)
    await db.flush()
    # A new driver has no verdict yet, so a resolved incident is open again.
    await update_incident_status(db, incident.id)
    await db.commit()
    return await load_incident_driver(db, entry.id)


async def remove_driver(db: AsyncSession, incident_driver_id: uuid.UUID) -> None:
    entry = await load_incident_driver(db, incident_driver_id)
    incident_id = entry.incident_id
    await db.delete(entry)
    await db.flush()
    # Removing the last unresolved driver may resolve the incident.
    await update_incident_status(db, incident_id)
    await db.commit()


async def link_driver(db: AsyncSession, incident_driver_id: uuid.UUID, driver_id: uuid.UUID) -> IncidentDriver:
    """Attach a free-text incident driver to an actual driver record.

    Names arrive as free text and are matched by exact (case-insensitive)
    equality. Anything the matcher misses needs a human to say who this is.
    """
    entry = await load_incident_driver(db, incident_driver_id)
    driver = await get_or_404(db, Driver, driver_id)
    entry.driver_id = driver.id
    await db.commit()
    return await load_incident_driver(db, incident_driver_id)


def _set_resolution(
    db: AsyncSession,
    entry: IncidentDriver,
    judge: User,
    verdict: str,
    bwp_points: int | None,
    *,
    now: datetime,
    description: str | None = None,
    set_description: bool = False,
) -> None:
    # Store the verdict *text*, never a reference: a published verdict must
    # not change when the rule is later renamed or re-priced.
    if entry.resolution is not None:
        entry.resolution.verdict = verdict
        entry.resolution.bwp_points = bwp_points
        if set_description:
            entry.resolution.description = description
        entry.resolution.judge_user_id = judge.id
        entry.resolution.resolved_at = now
    else:
        db.add(IncidentResolution(
            incident_driver_id=entry.id,
            judge_user_id=judge.id,
            verdict=verdict,
            bwp_points=bwp_points,
            description=description if set_description else None,
        ))


async def resolve_driver(
    db: AsyncSession, incident_driver_id: uuid.UUID, payload: ResolveDriverIncident, judge: User
) -> IncidentDriver:
    entry = await load_incident_driver(db, incident_driver_id)
    _set_resolution(db, entry, judge, payload.verdict, payload.bwp_points, now=datetime.now(timezone.utc))
    await db.flush()
    await update_incident_status(db, entry.incident_id)
    await db.commit()
    return await load_incident_driver(db, incident_driver_id)


async def resolve_incident(
    db: AsyncSession, incident_id: uuid.UUID, payload: BulkResolveIncident, judge: User
) -> Incident:
    """Set the verdict of several drivers of one incident at once.

    A driver sent without a verdict gets the default rule.
    """
    incident = await load_incident(db, incident_id)
    driver_map = {d.id: d for d in incident.drivers}
    default_rule = await _default_rule(db) if any(p.verdict is None for p in payload.drivers) else None
    # Only touch the description when it was actually sent. Writing it
    # unconditionally let a partial save blank the text for the whole incident.
    description_sent = "description" in payload.model_fields_set
    now = datetime.now(timezone.utc)

    for item in payload.drivers:
        entry = driver_map.get(item.incident_driver_id)
        if entry is None:
            raise BadRequest(f"Driver {item.incident_driver_id} not in this incident.")
        if item.verdict is None:
            verdict, bwp_points = default_rule.verdict, default_rule.default_bwp
        else:
            verdict, bwp_points = item.verdict, item.bwp_points
        _set_resolution(
            db, entry, judge, verdict, bwp_points,
            now=now, description=payload.description, set_description=description_sent,
        )

    await db.flush()
    await update_incident_status(db, incident_id)
    await db.commit()
    return await load_incident(db, incident_id)


async def resolve_remaining(db: AsyncSession, window_id: uuid.UUID, judge: User) -> tuple[IncidentWindow, int]:
    """Apply the default verdict to every driver in the window still awaiting one.

    The round is resolved atomically or not at all; drivers that already have
    a resolution are left exactly as the judge left them. Returns the fresh
    window and how many drivers were resolved.
    """
    window = await load_window(db, window_id)
    unresolved = [drv for incident in window.incidents for drv in incident.drivers if drv.resolution is None]
    if not unresolved:
        return window, 0

    rule = await _default_rule(db)
    now = datetime.now(timezone.utc)
    for drv in unresolved:
        _set_resolution(db, drv, judge, rule.verdict, rule.default_bwp, now=now)
    await db.flush()
    for incident_id in {drv.incident_id for drv in unresolved}:
        await update_incident_status(db, incident_id)
    await db.commit()
    return await load_window(db, window_id), len(unresolved)


async def publish_window(db: AsyncSession, window_id: uuid.UUID) -> tuple[IncidentWindow, int]:
    """Reveal every verdict in the window and issue the BWP they carry.

    Publishing is the single point where verdicts become visible and penalties
    reach licences, so both happen in one transaction. Re-publishing is safe:
    apply_resolution_bwp short-circuits on already-applied resolutions.
    Returns the fresh window and how many penalties reached no licence
    because the driver is not linked to a record.
    """
    window = await load_window(db, window_id)
    if not window.incidents:
        raise Conflict("This window has no incidents to publish.")

    unlinked = 0
    for incident in window.incidents:
        incident.is_published = True
        for drv in incident.drivers:
            await apply_resolution_bwp(drv, db)
            res = drv.resolution
            if res is not None and res.bwp_points and not res.bwp_applied:
                unlinked += 1
    await db.commit()
    return await load_window(db, window_id), unlinked


# ── BWP audit / backfill ─────────────────────────────────────────────────────

def _unlinked_applied_query() -> Select:
    """Applied penalties whose incident driver was never linked to a record."""
    return (
        select(IncidentDriver, Driver)
        .options(selectinload(IncidentDriver.resolution))
        .join(IncidentResolution, IncidentResolution.incident_driver_id == IncidentDriver.id)
        .outerjoin(Driver, func.lower(Driver.name) == func.lower(IncidentDriver.driver_name))
        .where(IncidentResolution.bwp_applied.is_(True))
        .where(IncidentDriver.driver_id.is_(None))
    )


async def bwp_audit(db: AsyncSession) -> list[BwpAuditEntry]:
    rows = (await db.execute(_unlinked_applied_query())).all()
    return [
        BwpAuditEntry(
            incident_driver_id=inc_drv.id,
            driver_name=inc_drv.driver_name,
            bwp_points=inc_drv.resolution.bwp_points or 0,
            matched_driver_id=drv.id if drv else None,
            matched_driver_name=drv.name if drv else None,
        )
        for inc_drv, drv in rows
    ]


async def bwp_backfill(db: AsyncSession) -> BwpBackfillOut:
    """Issue the missing points for penalties applied against an unlinked driver.

    Each such driver whose name now matches a record is linked to it and gets
    its point through the same rule publishing uses.
    """
    rows = (await db.execute(_unlinked_applied_query())).all()
    fixed = 0
    unmatched: list[str] = []
    for inc_drv, drv in rows:
        if drv is None:
            if inc_drv.driver_name not in unmatched:
                unmatched.append(inc_drv.driver_name)
            continue
        inc_drv.driver_id = drv.id
        if inc_drv.resolution.bwp_points:
            # Marked applied although no point exists: clear the flag so the
            # shared rule issues the point and records which one it was.
            inc_drv.resolution.bwp_applied = False
            await apply_resolution_bwp(inc_drv, db)
        fixed += 1
    await db.commit()
    return BwpBackfillOut(fixed=fixed, unmatched=unmatched)

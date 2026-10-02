"""BWP audit: applied penalties that never reached a licence, and the backfill that fixes them."""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bwp import Driver
from app.models.incidents import (
    IncidentDriver,
    IncidentResolution,
)
from app.schemas.incidents import (
    BwpAuditEntry,
    BwpBackfillOut,
)
from app.services.incident_bwp import apply_resolution_bwp

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

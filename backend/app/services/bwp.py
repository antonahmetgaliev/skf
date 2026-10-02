"""BWP licence domain logic: drivers, points, penalty rules and clearances.

Routers stay thin; everything that reads or changes BWP state lives here and
raises :mod:`app.core.errors` exceptions, never ``HTTPException``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.models.bwp import BwpPoint, Driver, PenaltyClearance, PenaltyRule, utc_today
from app.repository import get_or_404, next_sort_order
from app.schemas.bwp import (
    BwpPointCreate,
    BwpPointUpdate,
    BwpResetCreate,
    DriverCreate,
    DriverUpdate,
    PenaltyRuleCreate,
    PenaltyRuleUpdate,
)

DEFAULT_RESET_NOTE = "All penalties cleared — points reset"

# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------


def drivers_query(simgrid_id: int | None = None) -> Select:
    stmt = select(Driver).order_by(Driver.name, Driver.id)
    if simgrid_id is not None:
        stmt = stmt.where(Driver.simgrid_driver_id == simgrid_id)
    return stmt


async def get_driver(db: AsyncSession, driver_id: uuid.UUID) -> Driver:
    return await get_or_404(db, Driver, driver_id, detail="Driver not found.")


async def get_driver_for_user(db: AsyncSession, user_id: uuid.UUID) -> Driver:
    driver = (await db.execute(select(Driver).where(Driver.user_id == user_id))).scalars().first()
    if driver is None:
        raise NotFound("No linked driver.")
    return driver


async def _ensure_name_free(db: AsyncSession, name: str, exclude_id: uuid.UUID | None = None) -> None:
    stmt = select(Driver.id).where(Driver.name.ilike(name))
    if exclude_id is not None:
        stmt = stmt.where(Driver.id != exclude_id)
    if (await db.execute(stmt)).first() is not None:
        raise Conflict("Driver name already exists.")


async def create_driver(db: AsyncSession, body: DriverCreate) -> Driver:
    name = body.name.strip()
    await _ensure_name_free(db, name)
    driver = Driver(name=name)
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return driver


async def update_driver(db: AsyncSession, driver_id: uuid.UUID, body: DriverUpdate) -> Driver:
    driver = await get_driver(db, driver_id)
    new_name = body.name.strip()
    await _ensure_name_free(db, new_name, exclude_id=driver_id)
    driver.name = new_name
    if body.simgrid_driver_id is not None:
        driver.simgrid_driver_id = body.simgrid_driver_id
        driver.simgrid_display_name = driver.simgrid_display_name or new_name
    await db.commit()
    await db.refresh(driver)
    return driver


async def delete_driver(db: AsyncSession, driver_id: uuid.UUID) -> None:
    driver = await get_driver(db, driver_id)
    await db.delete(driver)
    await db.commit()


async def set_my_driver_photo(db: AsyncSession, user_id: uuid.UUID, photo_url: str | None) -> Driver:
    driver = await get_driver_for_user(db, user_id)
    driver.photo_url = photo_url
    await db.commit()
    await db.refresh(driver)
    return driver


# ---------------------------------------------------------------------------
# BWP points
# ---------------------------------------------------------------------------


async def add_point(db: AsyncSession, driver_id: uuid.UUID, body: BwpPointCreate) -> BwpPoint:
    await get_driver(db, driver_id)
    point = BwpPoint(
        driver_id=driver_id,
        points=body.points,
        issued_on=body.issued_on,
        expires_on=body.expires_on,
    )
    db.add(point)
    await db.commit()
    await db.refresh(point)
    return point


async def delete_point(db: AsyncSession, point_id: uuid.UUID) -> None:
    point = await get_or_404(db, BwpPoint, point_id, detail="Point not found.")
    await db.delete(point)
    await db.commit()


async def expire_point(db: AsyncSession, point_id: uuid.UUID, body: BwpPointUpdate) -> BwpPoint:
    """Expire a single point today; a point that already expired is left as is."""
    point = await get_or_404(db, BwpPoint, point_id, detail="Point not found.")
    today = utc_today()
    if point.expires_on <= today:
        return point
    point.expires_on = today
    point.note = body.note.strip() or None
    await db.commit()
    await db.refresh(point)
    return point


async def reset_driver(db: AsyncSession, driver_id: uuid.UUID, body: BwpResetCreate) -> Driver:
    """Expire all active points of a driver and drop their clearances.

    Used once a driver has served every penalty so they start accumulating
    afresh. Points are expired today (not deleted) so history is kept;
    clearances are removed so they don't carry over to the next cycle.
    """
    driver = await get_driver(db, driver_id)
    today = utc_today()
    note = body.note.strip() or DEFAULT_RESET_NOTE

    for point in driver.points:
        if point.expires_on > today:
            point.expires_on = today
            point.note = note
    for clearance in list(driver.clearances):
        await db.delete(clearance)

    await db.commit()
    await db.refresh(driver)
    return driver


# ---------------------------------------------------------------------------
# Penalty rules
# ---------------------------------------------------------------------------


async def list_penalty_rules(db: AsyncSession) -> list[PenaltyRule]:
    result = await db.execute(select(PenaltyRule).order_by(PenaltyRule.sort_order))
    return list(result.scalars().all())


async def get_penalty_rule(db: AsyncSession, rule_id: uuid.UUID) -> PenaltyRule:
    return await get_or_404(db, PenaltyRule, rule_id, detail="Penalty rule not found.")


async def create_penalty_rule(db: AsyncSession, body: PenaltyRuleCreate) -> PenaltyRule:
    rule = PenaltyRule(
        threshold=body.threshold,
        label=body.label,
        sort_order=await next_sort_order(db, PenaltyRule.sort_order),
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def update_penalty_rule(db: AsyncSession, rule_id: uuid.UUID, body: PenaltyRuleUpdate) -> PenaltyRule:
    rule = await get_penalty_rule(db, rule_id)
    if body.threshold is not None:
        rule.threshold = body.threshold
    if body.label is not None:
        rule.label = body.label
    await db.commit()
    await db.refresh(rule)
    return rule


async def delete_penalty_rule(db: AsyncSession, rule_id: uuid.UUID) -> None:
    rule = await get_penalty_rule(db, rule_id)
    await db.delete(rule)
    await db.commit()


# ---------------------------------------------------------------------------
# Penalty clearances
# ---------------------------------------------------------------------------


async def _find_clearance(
    db: AsyncSession, driver_id: uuid.UUID, rule_id: uuid.UUID
) -> PenaltyClearance | None:
    result = await db.execute(
        select(PenaltyClearance).where(
            PenaltyClearance.driver_id == driver_id,
            PenaltyClearance.penalty_rule_id == rule_id,
        )
    )
    return result.scalars().first()


async def put_clearance(
    db: AsyncSession, driver_id: uuid.UUID, rule_id: uuid.UUID
) -> tuple[PenaltyClearance, bool]:
    """Mark a rule as cleared for a driver. Returns ``(clearance, created)``."""
    await get_driver(db, driver_id)
    await get_penalty_rule(db, rule_id)
    existing = await _find_clearance(db, driver_id, rule_id)
    if existing is not None:
        return existing, False
    clearance = PenaltyClearance(driver_id=driver_id, penalty_rule_id=rule_id)
    db.add(clearance)
    await db.commit()
    await db.refresh(clearance)
    return clearance, True


async def delete_clearance(db: AsyncSession, driver_id: uuid.UUID, rule_id: uuid.UUID) -> None:
    clearance = await _find_clearance(db, driver_id, rule_id)
    if clearance is None:
        raise NotFound("Clearance not found.")
    await db.delete(clearance)
    await db.commit()

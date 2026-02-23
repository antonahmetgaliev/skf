"""BWP License CRUD endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.bwp import BwpPoint, Driver, PenaltyClearance, PenaltyRule
from app.models.user import User
from app.schemas.bwp import (
    BwpPointCreate,
    BwpPointOut,
    DriverBrief,
    DriverCreate,
    DriverOut,
    PenaltyClearanceOut,
    PenaltyRuleCreate,
    PenaltyRuleOut,
    PenaltyRuleUpdate,
)

router = APIRouter(prefix="/bwp", tags=["BWP License"])


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------


@router.get("/drivers", response_model=list[DriverOut])
async def list_drivers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Driver).order_by(Driver.name))
    return result.scalars().all()


@router.post("/drivers", response_model=DriverOut, status_code=status.HTTP_201_CREATED)
async def create_driver(
    body: DriverCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(Driver).where(Driver.name.ilike(body.name.strip()))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver name already exists.",
        )
    driver = Driver(name=body.name.strip())
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return driver


@router.delete("/drivers/{driver_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_driver(
    driver_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Driver).where(Driver.id == driver_id))
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    await db.delete(driver)
    await db.commit()


# ---------------------------------------------------------------------------
# BWP Points
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/{driver_id}/points",
    response_model=BwpPointOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_point(
    driver_id: uuid.UUID,
    body: BwpPointCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Driver).where(Driver.id == driver_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Driver not found.")

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


@router.delete("/points/{point_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_point(
    point_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(BwpPoint).where(BwpPoint.id == point_id))
    point = result.scalar_one_or_none()
    if not point:
        raise HTTPException(status_code=404, detail="Point not found.")
    await db.delete(point)
    await db.commit()


# ---------------------------------------------------------------------------
# Penalty Rules
# ---------------------------------------------------------------------------


@router.get("/penalty-rules", response_model=list[PenaltyRuleOut])
async def list_penalty_rules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PenaltyRule).order_by(PenaltyRule.sort_order))
    return result.scalars().all()


@router.post(
    "/penalty-rules",
    response_model=PenaltyRuleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_penalty_rule(
    body: PenaltyRuleCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Auto-increment sort_order
    result = await db.execute(
        select(PenaltyRule.sort_order).order_by(PenaltyRule.sort_order.desc()).limit(1)
    )
    max_order = result.scalar_one_or_none() or 0
    rule = PenaltyRule(
        threshold=body.threshold,
        label=body.label,
        sort_order=max_order + 1,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/penalty-rules/{rule_id}", response_model=PenaltyRuleOut)
async def update_penalty_rule(
    rule_id: uuid.UUID,
    body: PenaltyRuleUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PenaltyRule).where(PenaltyRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Penalty rule not found.")
    if body.threshold is not None:
        rule.threshold = body.threshold
    if body.label is not None:
        rule.label = body.label
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/penalty-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_penalty_rule(
    rule_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PenaltyRule).where(PenaltyRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Penalty rule not found.")
    await db.delete(rule)
    await db.commit()


# ---------------------------------------------------------------------------
# Penalty Clearances
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/{driver_id}/clearances/{rule_id}",
    response_model=PenaltyClearanceOut,
    status_code=status.HTTP_201_CREATED,
)
async def set_clearance(
    driver_id: uuid.UUID,
    rule_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a penalty rule as cleared for a driver."""
    result = await db.execute(select(Driver).where(Driver.id == driver_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Driver not found.")
    result = await db.execute(select(PenaltyRule).where(PenaltyRule.id == rule_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Penalty rule not found.")
    # Check if already cleared
    result = await db.execute(
        select(PenaltyClearance).where(
            PenaltyClearance.driver_id == driver_id,
            PenaltyClearance.penalty_rule_id == rule_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    clearance = PenaltyClearance(driver_id=driver_id, penalty_rule_id=rule_id)
    db.add(clearance)
    await db.commit()
    await db.refresh(clearance)
    return clearance


@router.delete(
    "/drivers/{driver_id}/clearances/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_clearance(
    driver_id: uuid.UUID,
    rule_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Un-mark a penalty rule as cleared for a driver."""
    result = await db.execute(
        select(PenaltyClearance).where(
            PenaltyClearance.driver_id == driver_id,
            PenaltyClearance.penalty_rule_id == rule_id,
        )
    )
    clearance = result.scalar_one_or_none()
    if not clearance:
        raise HTTPException(status_code=404, detail="Clearance not found.")
    await db.delete(clearance)
    await db.commit()

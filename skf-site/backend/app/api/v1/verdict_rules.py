"""Verdict rules and description presets: the stewards' catalogues."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, get_current_user_optional, require_judge
from app.database import get_db
from app.models.user import User
from app.schemas.incidents import (
    DescriptionPresetCreate,
    DescriptionPresetOut,
    DescriptionPresetUpdate,
    VerdictRuleCreate,
    VerdictRuleOut,
    VerdictRuleReorder,
    VerdictRuleUpdate,
)
from app.services import incidents as svc

router = APIRouter(tags=["Incidents"])


# ── Verdict rules ────────────────────────────────────────────────────────────


@router.get("/verdict-rules", response_model=list[VerdictRuleOut])
async def list_verdict_rules(
    db: AsyncSession = Depends(get_db),
    # The catalogue is public knowledge — it is printed in the regulations, and
    # every viewer needs the default rule to tell a penalty from "no action".
    _: User | None = Depends(get_current_user_optional),
):
    return await svc.list_verdict_rules(db)


@router.post("/verdict-rules", response_model=VerdictRuleOut, status_code=status.HTTP_201_CREATED)
async def create_verdict_rule(
    payload: VerdictRuleCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    return await svc.create_verdict_rule(db, payload)


@router.put("/verdict-rules/order", response_model=list[VerdictRuleOut])
async def reorder_verdict_rules(
    payload: VerdictRuleReorder,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    return await svc.reorder_verdict_rules(db, payload.ids)


@router.patch("/verdict-rules/{rule_id}", response_model=VerdictRuleOut)
async def update_verdict_rule(
    rule_id: uuid.UUID,
    payload: VerdictRuleUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    return await svc.update_verdict_rule(db, rule_id, payload)


@router.delete("/verdict-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_verdict_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    await svc.delete_verdict_rule(db, rule_id)


# ── Description presets ──────────────────────────────────────────────────────


@router.get("/description-presets", response_model=list[DescriptionPresetOut])
async def list_description_presets(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return await svc.list_description_presets(db)


@router.post("/description-presets", response_model=DescriptionPresetOut, status_code=status.HTTP_201_CREATED)
async def create_description_preset(
    payload: DescriptionPresetCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    return await svc.create_description_preset(db, payload)


@router.patch("/description-presets/{preset_id}", response_model=DescriptionPresetOut)
async def update_description_preset(
    preset_id: uuid.UUID,
    payload: DescriptionPresetUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    return await svc.update_description_preset(db, preset_id, payload)


@router.delete("/description-presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_description_preset(
    preset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    await svc.delete_description_preset(db, preset_id)

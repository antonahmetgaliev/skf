"""BWP penalty rules: thresholds and the penalty each one triggers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.params import RuleId
from app.auth import require_admin
from app.database import get_db
from app.models.user import User
from app.schemas.bwp import PenaltyRuleCreate, PenaltyRuleOut, PenaltyRuleUpdate
from app.services import bwp as service

router = APIRouter(prefix="/penalty-rules", tags=["Penalty rules"])


@router.get("", response_model=list[PenaltyRuleOut])
async def list_penalty_rules(db: AsyncSession = Depends(get_db)):
    return await service.list_penalty_rules(db)


@router.post("", response_model=PenaltyRuleOut, status_code=status.HTTP_201_CREATED)
async def create_penalty_rule(
    body: PenaltyRuleCreate,
    response: Response,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rule = await service.create_penalty_rule(db, body)
    response.headers["Location"] = f"/api/v1/penalty-rules/{rule.id}"
    return rule


@router.get("/{ruleId}", response_model=PenaltyRuleOut)
async def get_penalty_rule(rule_id: RuleId, db: AsyncSession = Depends(get_db)):
    return await service.get_penalty_rule(db, rule_id)


@router.patch("/{ruleId}", response_model=PenaltyRuleOut)
async def update_penalty_rule(
    rule_id: RuleId,
    body: PenaltyRuleUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await service.update_penalty_rule(db, rule_id, body)


@router.delete("/{ruleId}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_penalty_rule(
    rule_id: RuleId,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_penalty_rule(db, rule_id)

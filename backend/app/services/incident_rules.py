"""Verdict rules and description presets: the stewards' configuration."""

from __future__ import annotations

import uuid

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest, Conflict, Unprocessable
from app.models.incidents import (
    DescriptionPreset,
    VerdictRule,
)
from app.repository import get_or_404
from app.schemas.incidents import (
    DescriptionPresetCreate,
    DescriptionPresetUpdate,
    VerdictRuleCreate,
    VerdictRuleUpdate,
)

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


async def default_rule(db: AsyncSession) -> VerdictRule:
    rule = (
        await db.execute(select(VerdictRule).where(VerdictRule.is_default.is_(True)))
    ).scalar_one_or_none()
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


async def update_verdict_rule(
    db: AsyncSession, rule_id: uuid.UUID, payload: VerdictRuleUpdate
) -> VerdictRule:
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

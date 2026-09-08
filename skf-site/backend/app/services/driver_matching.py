"""Shared driver-identity matching helpers.

Single home for the name-matching logic used by the incident driver matcher
and the SimGrid standings sync, so the rules cannot drift apart.
Account↔driver linking does not use names at all — it is deterministic via
SimGrid's discord_uid (see app.services.drivers).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bwp import Driver


async def match_driver_id_by_name(
    db: AsyncSession, name: str
) -> uuid.UUID | None:
    """Case-insensitive exact match of a driver name against both the
    canonical name and the SimGrid display name."""
    normalized = name.strip().lower()
    if not normalized:
        return None
    result = await db.execute(
        select(Driver.id).where(
            or_(
                func.lower(Driver.name) == normalized,
                func.lower(Driver.simgrid_display_name) == normalized,
            )
        )
    )
    return result.scalars().first()

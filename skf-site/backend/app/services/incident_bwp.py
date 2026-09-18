"""Turning an incident resolution into a licence penalty.

One home for the rule, so that publishing a window and any manual repair
cannot drift apart — and so the idempotency guard is impossible to forget.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bwp import BwpPoint
from app.models.incidents import IncidentDriver
from app.services.driver_matching import match_driver_id_by_name

# The regulations' "points remain active for 3 months".
BWP_ACTIVE_DAYS = 90


async def apply_resolution_bwp(entry: IncidentDriver, db: AsyncSession) -> bool:
    """Issue this driver's BWP onto their licence. Returns True if a point was created.

    Does **not** commit: the caller owns the transaction, which is what lets a
    whole window's penalties be issued atomically.

    A resolution is only marked applied when a point genuinely exists. The
    previous behaviour marked it applied even when the driver was unlinked and
    no point could be created, which silently wrote the penalty off — that is
    the entire reason the unlinked-penalties audit has any work to do.
    """
    resolution = entry.resolution
    if resolution is None or not resolution.bwp_points:
        return False
    if resolution.bwp_applied:
        # Idempotent: republishing a window must not double the penalty.
        return False

    if not entry.driver_id:
        entry.driver_id = await match_driver_id_by_name(db, entry.driver_name)
    if not entry.driver_id:
        # Still unknown — leave the penalty owed and visible rather than
        # marking it applied against nobody.
        return False

    today = date.today()
    point = BwpPoint(
        driver_id=entry.driver_id,
        points=resolution.bwp_points,
        issued_on=today,
        expires_on=today + timedelta(days=BWP_ACTIVE_DAYS),
    )
    db.add(point)
    await db.flush()
    # Remember which point this created, so it can be traced back and undone.
    resolution.applied_bwp_point_id = point.id
    resolution.bwp_applied = True
    return True

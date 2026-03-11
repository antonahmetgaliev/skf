"""Driver-profile utilities: sync SimGrid standings entries into the drivers table."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.bwp import Driver
from app.schemas.championship import StandingEntry

logger = logging.getLogger(__name__)


async def sync_drivers_from_standings(entries: list[StandingEntry]) -> None:
    """Upsert Driver rows from SimGrid standings entries.

    Runs in a fresh DB session so it can be safely called as a
    FastAPI BackgroundTask after the HTTP response has been sent.
    """
    from app.database import async_session

    async with async_session() as db:
        try:
            for entry in entries:
                await _upsert_entry(entry, db)
            await db.commit()
        except Exception:
            logger.exception("Driver sync failed; rolling back")
            await db.rollback()


async def _upsert_entry(entry: StandingEntry, db) -> None:  # type: ignore[type-arg]
    display_name = (entry.display_name or "").strip()
    if not display_name:
        return

    country = entry.country_code or None

    # 1. Match by SimGrid driver ID (most reliable)
    result = await db.execute(
        select(Driver).where(Driver.simgrid_driver_id == entry.id)
    )
    driver = result.scalar_one_or_none()
    if driver:
        driver.simgrid_display_name = display_name
        if country:
            driver.country_code = country
        return

    # 2. Match by name (case-insensitive) where not yet linked to SimGrid
    result = await db.execute(
        select(Driver).where(
            Driver.name.ilike(display_name),
            Driver.simgrid_driver_id.is_(None),
        )
    )
    driver = result.scalar_one_or_none()
    if driver:
        driver.simgrid_driver_id = entry.id
        driver.simgrid_display_name = display_name
        if country:
            driver.country_code = country
        return

    # 3. Match via previously set simgrid_display_name (handles name changes)
    result = await db.execute(
        select(Driver).where(
            Driver.simgrid_display_name.ilike(display_name),
        )
    )
    driver = result.scalar_one_or_none()
    if driver:
        driver.simgrid_driver_id = entry.id
        if country:
            driver.country_code = country
        return

    # 4. Insert new driver – use a savepoint so a unique-name collision
    #    only rolls back this single insert, not the whole batch.
    try:
        async with db.begin_nested():
            new_driver = Driver(
                name=display_name,
                simgrid_driver_id=entry.id,
                simgrid_display_name=display_name,
                country_code=country,
            )
            db.add(new_driver)
    except IntegrityError:
        logger.warning("Skipped duplicate driver name during sync: %r", display_name)

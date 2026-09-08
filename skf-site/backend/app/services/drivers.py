"""Driver-profile utilities: sync SimGrid standings entries into the drivers table."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.bwp import Driver
from app.models.user import User
from app.schemas.championship import StandingEntry

logger = logging.getLogger(__name__)


async def sync_drivers_from_standings(
    entries: list[StandingEntry],
    championship_id: int | None = None,
) -> None:
    """Upsert Driver rows from SimGrid standings entries.

    Runs in a fresh DB session so it can be safely called as a
    FastAPI BackgroundTask after the HTTP response has been sent.
    Each entry is processed in its own savepoint so one bad row
    cannot discard the rest of the batch.

    When ``championship_id`` is given, the championship's participating
    users are fetched too and drivers are auto-linked to site users via
    SimGrid's ``discord_uid`` — a deterministic match, unlike names.
    """
    from app.database import async_session

    async with async_session() as db:
        for entry in entries:
            try:
                async with db.begin_nested():
                    await _upsert_entry(entry, db)
            except Exception:
                logger.exception(
                    "Driver sync failed for entry %r (simgrid id %r)",
                    entry.display_name, entry.id,
                )
        try:
            await db.commit()
        except Exception:
            logger.exception("Driver sync commit failed; rolling back")
            await db.rollback()
            return

        if championship_id is not None:
            try:
                await _auto_link_by_discord_uid(championship_id, db)
            except Exception:
                logger.exception(
                    "Discord-uid auto-link failed for championship %s",
                    championship_id,
                )


async def _upsert_entry(entry: StandingEntry, db) -> None:  # type: ignore[type-arg]
    display_name = (entry.display_name or "").strip()
    if not display_name:
        return
    # Entries without a SimGrid user id cannot be identified reliably —
    # never store the registration id or 0 in their place.
    if not entry.id:
        return

    country = entry.country_code or None
    lowered = display_name.lower()

    # 1. Match by SimGrid driver ID (most reliable)
    result = await db.execute(
        select(Driver).where(Driver.simgrid_driver_id == entry.id)
    )
    driver = result.scalars().first()
    if driver:
        driver.simgrid_display_name = display_name
        if country:
            driver.country_code = country
        return

    # 2. Match by name (case-insensitive) where not yet linked to SimGrid
    result = await db.execute(
        select(Driver).where(
            func.lower(Driver.name) == lowered,
            Driver.simgrid_driver_id.is_(None),
        )
    )
    driver = result.scalars().first()
    if driver:
        driver.simgrid_driver_id = entry.id
        driver.simgrid_display_name = display_name
        if country:
            driver.country_code = country
        return

    # 3. Match via previously set simgrid_display_name (handles name changes).
    # Only for drivers not yet bound to a SimGrid id — a colliding display
    # name must never reassign someone else's identity.
    result = await db.execute(
        select(Driver).where(
            func.lower(Driver.simgrid_display_name) == lowered,
            Driver.simgrid_driver_id.is_(None),
        )
    )
    driver = result.scalars().first()
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


async def link_driver_for_user(user_id, discord_id: str) -> None:
    """Auto-link a just-logged-in user to their driver via SimGrid.

    Resolves the user's SimGrid id through ``discord_uid`` and claims the
    matching unclaimed driver row. Fire-and-forget (BackgroundTask after the
    OAuth redirect) — a SimGrid hiccup must never affect login.
    """
    from app.database import async_session
    from app.services.simgrid import simgrid_service

    try:
        async with async_session() as db:
            existing = await db.execute(
                select(Driver.id).where(Driver.user_id == user_id)
            )
            if existing.scalars().first() is not None:
                return

            simgrid_user_id = await simgrid_service.get_user_by_discord_id(discord_id)
            if not simgrid_user_id:
                return

            result = await db.execute(
                select(Driver).where(
                    Driver.simgrid_driver_id == simgrid_user_id,
                    Driver.user_id.is_(None),
                )
            )
            driver = result.scalars().first()
            if driver is None:
                return
            driver.user_id = user_id
            await db.commit()
            logger.info(
                "Auto-linked driver %s to user %s via discord_uid at login",
                driver.id, user_id,
            )
    except Exception:
        logger.exception("Login auto-link failed for user %s", user_id)


async def _auto_link_by_discord_uid(championship_id: int, db) -> None:  # type: ignore[type-arg]
    """Link unclaimed drivers to site users via SimGrid's discord_uid."""
    from app.services.simgrid import simgrid_service

    participants = await simgrid_service.get_participating_users(championship_id)
    discord_by_simgrid_id = {
        p.user_id: p.discord_uid for p in participants if p.discord_uid
    }
    if not discord_by_simgrid_id:
        return

    result = await db.execute(
        select(Driver).where(
            Driver.simgrid_driver_id.in_(discord_by_simgrid_id.keys()),
            Driver.user_id.is_(None),
        )
    )
    unlinked_drivers = result.scalars().all()
    if not unlinked_drivers:
        return

    uids = {
        discord_by_simgrid_id[d.simgrid_driver_id] for d in unlinked_drivers
    }
    users_result = await db.execute(
        select(User).where(User.discord_id.in_(uids))
    )
    users_by_discord_id = {u.discord_id: u for u in users_result.scalars().all()}

    linked = 0
    for driver in unlinked_drivers:
        user = users_by_discord_id.get(
            discord_by_simgrid_id[driver.simgrid_driver_id]
        )
        if user is None:
            continue
        # One driver per user — skip users who already claimed a driver.
        existing = await db.execute(
            select(Driver.id).where(Driver.user_id == user.id)
        )
        if existing.scalars().first() is not None:
            continue
        try:
            async with db.begin_nested():
                driver.user_id = user.id
            linked += 1
        except IntegrityError:
            logger.warning(
                "Auto-link race for driver %s / user %s; skipped",
                driver.id, user.id,
            )
    await db.commit()
    if linked:
        logger.info(
            "Auto-linked %d driver(s) via discord_uid for championship %s",
            linked, championship_id,
        )

"""Who our drivers are, and which site account is which driver.

A driver is a SimGrid user: rows are created and refreshed from SimGrid, keyed
on its user id and never on a name. A site account (a Discord login) belongs
to the driver whose SimGrid profile has that Discord account connected; an
admin can set or clear the link by hand where SimGrid cannot tell.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Unprocessable
from app.models.bwp import BwpPoint, Driver, PenaltyClearance
from app.models.incidents import IncidentDriver
from app.models.race_result import GiveawayNameAlias, RaceResultEntry
from app.models.user import User
from app.repository import get_or_404
from app.schemas.championship import ParticipatingUser, StandingEntryOut
from app.schemas.enums import DriverIssueKind, DriverLinkSource, DriverLinkStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Drivers from SimGrid
# ---------------------------------------------------------------------------


async def driver_by_simgrid_id(db: AsyncSession, simgrid_id: int) -> Driver | None:
    """The driver of a SimGrid user. Until duplicates are cleaned up, the oldest row wins."""
    result = await db.execute(
        select(Driver).where(Driver.simgrid_driver_id == simgrid_id).order_by(Driver.created_at, Driver.id)
    )
    return result.scalars().first()


async def upsert_from_standings(db: AsyncSession, entries: list[StandingEntryOut]) -> int:
    """Create or refresh drivers from standings entries; returns how many are new.

    Matching is by SimGrid user id only. A name never identifies anyone: two
    people can share one, and one person can change theirs.
    """
    created = 0
    now = datetime.now(UTC)
    for entry in entries:
        display_name = (entry.display_name or "").strip()
        # Entries without a SimGrid user id cannot be identified.
        if not display_name or not entry.id:
            continue

        driver = await driver_by_simgrid_id(db, entry.id)
        if driver is None:
            driver = Driver(name=display_name, simgrid_driver_id=entry.id)
            db.add(driver)
            created += 1
        driver.simgrid_display_name = display_name
        if entry.country_code:
            driver.country_code = entry.country_code
        driver.synced_at = now
    await db.flush()
    return created


async def apply_participants(db: AsyncSession, participants: list[ParticipatingUser]) -> None:
    """Store the Discord and Steam ids SimGrid reports for our drivers."""
    by_simgrid_id = {p.user_id: p for p in participants}
    if not by_simgrid_id:
        return
    drivers = await db.execute(select(Driver).where(Driver.simgrid_driver_id.in_(by_simgrid_id.keys())))
    for driver in drivers.scalars():
        participant = by_simgrid_id[driver.simgrid_driver_id]
        # SimGrid is the source: a disconnected Discord account is forgotten too.
        driver.discord_uid = participant.discord_uid or None
        driver.steam64_id = participant.steam64_id or None
    await db.flush()


# ---------------------------------------------------------------------------
# Account ↔ driver
# ---------------------------------------------------------------------------


async def _account_of(db: AsyncSession, driver_id: uuid.UUID) -> User | None:
    return (await db.execute(select(User).where(User.driver_id == driver_id))).scalar_one_or_none()


def _not_decided_by_admin():
    return or_(User.driver_link_source.is_(None), User.driver_link_source != DriverLinkSource.ADMIN)


async def link_accounts(db: AsyncSession) -> int:
    """Link every account without a driver to the driver SimGrid ties to its Discord id.

    Never touches an admin's decision: neither a link made by hand nor one removed by hand.
    """
    rows = await db.execute(
        select(User, Driver)
        .join(Driver, Driver.discord_uid == User.discord_id)
        .where(User.driver_id.is_(None), _not_decided_by_admin())
        .order_by(Driver.created_at, Driver.id)
    )
    taken = set((await db.execute(select(User.driver_id).where(User.driver_id.is_not(None)))).scalars())
    linked = 0
    for user, driver in rows.all():
        if user.driver_id is not None or driver.id in taken:
            continue
        user.driver_id = driver.id
        user.driver_link_source = DriverLinkSource.SIMGRID
        taken.add(driver.id)
        linked += 1
    await db.flush()
    return linked


async def link_user(db: AsyncSession, user: User) -> DriverLinkStatus:
    """Find *user*'s driver through SimGrid and link it; says why when it cannot."""
    from app.services.simgrid import simgrid_service

    if user.driver_id is not None:
        return DriverLinkStatus.LINKED
    if user.driver_link_source == DriverLinkSource.ADMIN:
        return DriverLinkStatus.UNLINKED_BY_ADMIN

    simgrid_user_id = await simgrid_service.get_user_by_discord_id(user.discord_id)
    if not simgrid_user_id:
        return DriverLinkStatus.NO_SIMGRID_ACCOUNT
    driver = await driver_by_simgrid_id(db, simgrid_user_id)
    if driver is None:
        return DriverLinkStatus.DRIVER_NOT_SYNCED
    if await _account_of(db, driver.id) is not None:
        logger.warning("Driver %s of user %s is linked to another account", driver.id, user.id)
        return DriverLinkStatus.DRIVER_TAKEN

    user.driver_id = driver.id
    user.driver_link_source = DriverLinkSource.SIMGRID
    driver.discord_uid = user.discord_id
    await db.commit()
    logger.info("Linked user %s to driver %s via SimGrid", user.id, driver.id)
    return DriverLinkStatus.LINKED


async def link_driver_for_user(user_id: uuid.UUID) -> None:
    """Link a just-signed-in user to their driver.

    Runs after the OAuth redirect, in its own session: a SimGrid hiccup must
    never affect login.
    """
    from app.database import async_session

    try:
        async with async_session() as db:
            user = await db.get(User, user_id)
            if user is None:
                return
            status = await link_user(db, user)
            if status is not DriverLinkStatus.LINKED:
                logger.warning("User %s has no driver after login: %s", user_id, status.value)
    except Exception:
        logger.exception("Login link failed for user %s", user_id)


async def set_user_driver(db: AsyncSession, user: User, driver_id: uuid.UUID) -> None:
    """Link *user* to a driver by an admin's decision; the caller commits."""
    driver = await get_or_404(db, Driver, driver_id, detail="Driver not found.")
    holder = await _account_of(db, driver.id)
    if holder is not None and holder.id != user.id:
        raise Conflict(f"This driver is linked to the account {holder.username}.")
    user.driver_id = driver.id
    user.driver_link_source = DriverLinkSource.ADMIN


def clear_user_driver(user: User) -> None:
    """Unlink by an admin's decision. Recorded, so the sync does not link it back."""
    user.driver_id = None
    user.driver_link_source = DriverLinkSource.ADMIN


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    championships: int = 0
    failed: int = 0
    created: int = 0
    linked: int = 0


async def sync_championship(
    db: AsyncSession, championship_id: int, entries: list[StandingEntryOut]
) -> tuple[int, int]:
    """Bring drivers and links up to date with one championship; returns (created, linked)."""
    from app.services.simgrid import simgrid_service

    created = await upsert_from_standings(db, entries)
    await db.commit()

    participants = await simgrid_service.get_participating_users(championship_id)
    await apply_participants(db, participants)
    linked = await link_accounts(db)
    await db.commit()
    return created, linked


async def sync_drivers_from_standings(entries: list[StandingEntryOut], championship_id: int) -> None:
    """Background task behind ``GET /championships/{id}/standings``.

    Runs in its own session, after the response has been sent.
    """
    from app.database import async_session

    try:
        async with async_session() as db:
            created, linked = await sync_championship(db, championship_id, entries)
            if created or linked:
                logger.info(
                    "Championship %s: %d new driver(s), %d account(s) linked",
                    championship_id,
                    created,
                    linked,
                )
    except Exception:
        logger.exception("Driver sync failed for championship %s", championship_id)


async def sync_active_championships(db: AsyncSession) -> SyncResult:
    """Sync drivers from every championship shown on the site (admin action)."""
    from app.services import championships as championships_service

    result = SyncResult()
    for championship_id in await championships_service.active_ids(db):
        try:
            standings, _ = await championships_service.get_standings(championship_id)
            created, linked = await sync_championship(db, championship_id, standings.entries)
        except Exception:
            logger.exception("Driver sync failed for championship %s", championship_id)
            await db.rollback()
            result.failed += 1
            continue
        result.championships += 1
        result.created += created
        result.linked += linked
    return result


# ---------------------------------------------------------------------------
# Cleaning up rows that are not one SimGrid user's only row
# ---------------------------------------------------------------------------


@dataclass
class DriverIssue:
    kind: DriverIssueKind
    driver: Driver
    suggested_target: Driver | None = None


async def list_issues(db: AsyncSession) -> list[DriverIssue]:
    duplicated_ids = (
        select(Driver.simgrid_driver_id)
        .where(Driver.simgrid_driver_id.is_not(None))
        .group_by(Driver.simgrid_driver_id)
        .having(func.count() > 1)
    )
    duplicates = (
        (
            await db.execute(
                select(Driver)
                .where(Driver.simgrid_driver_id.in_(duplicated_ids))
                .order_by(Driver.simgrid_driver_id, Driver.created_at, Driver.id)
            )
        )
        .scalars()
        .all()
    )
    orphans = (
        (
            await db.execute(
                select(Driver).where(Driver.simgrid_driver_id.is_(None)).order_by(Driver.name, Driver.id)
            )
        )
        .scalars()
        .all()
    )

    issues: list[DriverIssue] = []
    # Among rows sharing a SimGrid id the oldest is the one to keep.
    keeper: dict[int, Driver] = {}
    for driver in duplicates:
        first = keeper.setdefault(driver.simgrid_driver_id, driver)
        issues.append(
            DriverIssue(
                DriverIssueKind.DUPLICATE_SIMGRID_ID,
                driver,
                suggested_target=None if first is driver else first,
            )
        )

    if orphans:
        names = {o.name.strip().lower() for o in orphans}
        known = await db.execute(
            select(Driver)
            .where(Driver.simgrid_driver_id.is_not(None), func.lower(Driver.name).in_(names))
            .order_by(Driver.created_at, Driver.id)
        )
        by_name: dict[str, Driver] = {}
        for driver in known.scalars():
            by_name.setdefault(driver.name.strip().lower(), driver)
        issues += [
            DriverIssue(DriverIssueKind.NO_SIMGRID_ID, o, by_name.get(o.name.strip().lower()))
            for o in orphans
        ]
    return issues


async def merge_drivers(db: AsyncSession, target_id: uuid.UUID, source_id: uuid.UUID) -> Driver:
    """Fold *source* into *target*: one person had two rows.

    Everything that points at the source moves to the target, the target
    takes over what it lacks, and the source is deleted.
    """
    if target_id == source_id:
        raise Unprocessable("A driver cannot be merged into itself.")
    target = await get_or_404(db, Driver, target_id, detail="Driver not found.")
    source = await get_or_404(db, Driver, source_id, detail="Source driver not found.")

    if (
        target.simgrid_driver_id
        and source.simgrid_driver_id
        and target.simgrid_driver_id != source.simgrid_driver_id
    ):
        raise Conflict("These are two different SimGrid users.")
    target_account = await _account_of(db, target.id)
    source_account = await _account_of(db, source.id)
    if target_account and source_account:
        raise Conflict("Both drivers are linked to an account. Unlink one of them first.")

    for model in (BwpPoint, IncidentDriver, RaceResultEntry, GiveawayNameAlias):
        await db.execute(
            update(model)
            .where(model.driver_id == source.id)
            .values(driver_id=target.id)
            .execution_options(synchronize_session=False)
        )
    cleared = set(
        (
            await db.execute(
                select(PenaltyClearance.penalty_rule_id).where(PenaltyClearance.driver_id == target.id)
            )
        ).scalars()
    )
    await db.execute(
        update(PenaltyClearance)
        .where(PenaltyClearance.driver_id == source.id, PenaltyClearance.penalty_rule_id.not_in(cleared))
        .values(driver_id=target.id)
        .execution_options(synchronize_session=False)
    )
    if source_account:
        source_account.driver_id = target.id

    for field in (
        "simgrid_driver_id",
        "simgrid_display_name",
        "country_code",
        "photo_url",
        "discord_uid",
        "steam64_id",
    ):
        if getattr(target, field) is None:
            setattr(target, field, getattr(source, field))

    # Deleted with plain statements: the ORM would cascade to the points
    # it still believes belong to the source.
    await db.flush()
    await db.execute(delete(PenaltyClearance).where(PenaltyClearance.driver_id == source_id))
    await db.execute(delete(Driver).where(Driver.id == source_id))
    await db.commit()
    db.expunge_all()
    return await db.get(Driver, target_id)

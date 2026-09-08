"""Tests for app.services.drivers.sync_drivers_from_standings.

Covers all four match paths and edge cases (empty name, duplicate key,
batch processing).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.schemas.championship import StandingEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(**kwargs) -> StandingEntry:
    defaults = {"id": 1, "position": 1, "display_name": "Driver One", "country_code": "GB"}
    return StandingEntry(**{**defaults, **kwargs})


async def _patch_and_sync(engine, entries, monkeypatch):
    """Swap app.database.async_session for the test engine, then run sync."""
    import app.database as db_module
    from app.services.drivers import sync_drivers_from_standings

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_module, "async_session", factory)
    await sync_drivers_from_standings(entries)


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_empty_display_name_is_skipped(engine, db, monkeypatch):
    """Entries whose display_name is blank/whitespace are silently ignored."""
    from app.models.bwp import Driver

    await _patch_and_sync(engine, [_entry(display_name="  ")], monkeypatch)

    result = await db.execute(select(Driver))
    assert result.scalars().all() == []


async def test_path1_updates_simgrid_display_name_and_country(engine, db, monkeypatch):
    """Path 1: existing driver matched by simgrid_driver_id gets display_name + country updated."""
    from app.models.bwp import Driver

    driver = Driver(name="Old Name", simgrid_driver_id=42, created_at=_now())
    db.add(driver)
    await db.commit()

    await _patch_and_sync(
        engine, [_entry(id=42, display_name="New Name", country_code="DE")], monkeypatch
    )

    await db.refresh(driver)
    assert driver.simgrid_display_name == "New Name"
    assert driver.country_code == "DE"


async def test_path1_canonical_name_is_unchanged(engine, db, monkeypatch):
    """Path 1: the driver's canonical name column is NOT overwritten."""
    from app.models.bwp import Driver

    driver = Driver(name="Canonical Name", simgrid_driver_id=10, created_at=_now())
    db.add(driver)
    await db.commit()

    await _patch_and_sync(
        engine, [_entry(id=10, display_name="SimGrid Name", country_code="FR")], monkeypatch
    )

    await db.refresh(driver)
    assert driver.name == "Canonical Name"


async def test_path1_empty_country_preserves_existing(engine, db, monkeypatch):
    """Path 1: an empty country_code in the entry does NOT overwrite an existing value."""
    from app.models.bwp import Driver

    driver = Driver(name="Driver FR", simgrid_driver_id=11, country_code="FR", created_at=_now())
    db.add(driver)
    await db.commit()

    await _patch_and_sync(
        engine, [_entry(id=11, display_name="Driver FR", country_code="")], monkeypatch
    )

    await db.refresh(driver)
    assert driver.country_code == "FR"


async def test_path2_links_unlinked_driver_by_name(engine, db, monkeypatch):
    """Path 2: case-insensitive name match assigns simgrid_driver_id when it was NULL."""
    from app.models.bwp import Driver

    driver = Driver(name="John Smith", simgrid_driver_id=None, created_at=_now())
    db.add(driver)
    await db.commit()

    await _patch_and_sync(
        engine, [_entry(id=99, display_name="john smith", country_code="US")], monkeypatch
    )

    await db.refresh(driver)
    assert driver.simgrid_driver_id == 99
    assert driver.simgrid_display_name == "john smith"
    assert driver.country_code == "US"


async def test_path2_skips_already_simgrid_linked_driver(engine, db, monkeypatch):
    """Path 2 won't match a driver that already has a different simgrid_driver_id.

    Falls through to path 4, which tries to INSERT a new row with the same
    canonical name and hits the unique constraint, so the row is skipped
    and the original driver is left unchanged.
    """
    from app.models.bwp import Driver

    existing = Driver(name="Alice Brown", simgrid_driver_id=5, created_at=_now())
    db.add(existing)
    await db.commit()

    await _patch_and_sync(
        engine, [_entry(id=88, display_name="Alice Brown", country_code="AU")], monkeypatch
    )

    result = await db.execute(select(Driver))
    drivers = result.scalars().all()
    # The new entry collides on the unique name — it is gracefully skipped.
    assert len(drivers) == 1, "Duplicate name should be skipped, not duplicated"
    await db.refresh(existing)
    assert existing.simgrid_driver_id == 5  # original is unchanged


async def test_path3_links_via_simgrid_display_name(engine, db, monkeypatch):
    """Path 3: match via stored simgrid_display_name when the canonical name differs."""
    from app.models.bwp import Driver

    driver = Driver(
        name="Johny",
        simgrid_display_name="John Smith",
        simgrid_driver_id=None,
        created_at=_now(),
    )
    db.add(driver)
    await db.commit()

    await _patch_and_sync(
        engine, [_entry(id=77, display_name="John Smith", country_code="CA")], monkeypatch
    )

    await db.refresh(driver)
    assert driver.simgrid_driver_id == 77
    assert driver.country_code == "CA"
    assert driver.name == "Johny"  # canonical name stays the same


async def test_path4_inserts_new_driver(engine, db, monkeypatch):
    """Path 4: no match → a new Driver row is created."""
    from app.models.bwp import Driver

    await _patch_and_sync(
        engine, [_entry(id=55, display_name="Brand New Driver", country_code="IT")], monkeypatch
    )

    result = await db.execute(select(Driver).where(Driver.simgrid_driver_id == 55))
    driver = result.scalar_one_or_none()
    assert driver is not None
    assert driver.name == "Brand New Driver"
    assert driver.country_code == "IT"


async def test_path4_duplicate_name_skipped_gracefully(engine, db, monkeypatch):
    """Path 4: unique-name IntegrityError is swallowed per row; the batch continues."""
    from app.models.bwp import Driver

    # A driver that owns the canonical name "Existing Driver".
    # It already has a simgrid_driver_id so path 2 won't match a new entry
    # with the same display_name → falls to path 4 → IntegrityError caught.
    existing = Driver(name="Existing Driver", simgrid_driver_id=1, created_at=_now())
    db.add(existing)
    await db.commit()

    entries = [
        _entry(id=100, display_name="Existing Driver", country_code="GB"),  # duplicate → skip
        _entry(id=101, display_name="Fresh Entry", country_code="NL"),       # new → insert
    ]
    await _patch_and_sync(engine, entries, monkeypatch)

    result = await db.execute(select(Driver))
    all_drivers = result.scalars().all()
    names = {d.name for d in all_drivers}

    assert "Existing Driver" in names
    assert "Fresh Entry" in names
    assert len([d for d in all_drivers if d.name == "Existing Driver"]) == 1  # no duplicate


async def test_entry_without_simgrid_id_is_skipped(engine, db, monkeypatch):
    """Entries with no user_id (id=None) must not create or match anything —
    especially not drivers whose simgrid_driver_id is NULL."""
    from app.models.bwp import Driver

    unlinked = Driver(name="No SimGrid Yet", simgrid_driver_id=None, created_at=_now())
    db.add(unlinked)
    await db.commit()

    await _patch_and_sync(
        engine, [_entry(id=None, display_name="Ghost Entry", country_code="PL")], monkeypatch
    )

    result = await db.execute(select(Driver))
    drivers = result.scalars().all()
    assert len(drivers) == 1
    await db.refresh(unlinked)
    assert unlinked.simgrid_driver_id is None
    assert unlinked.simgrid_display_name is None


async def test_path3_does_not_steal_assigned_simgrid_id(engine, db, monkeypatch):
    """A colliding display name must not reassign a driver already bound to a
    different SimGrid id — a new row is created instead."""
    from app.models.bwp import Driver

    existing = Driver(
        name="Johny",
        simgrid_display_name="John Smith",
        simgrid_driver_id=5,
        created_at=_now(),
    )
    db.add(existing)
    await db.commit()

    await _patch_and_sync(
        engine, [_entry(id=77, display_name="John Smith", country_code="CA")], monkeypatch
    )

    await db.refresh(existing)
    assert existing.simgrid_driver_id == 5  # identity NOT stolen

    result = await db.execute(select(Driver).where(Driver.simgrid_driver_id == 77))
    new_driver = result.scalar_one_or_none()
    assert new_driver is not None
    assert new_driver.name == "John Smith"


async def test_case_variant_duplicate_name_is_not_inserted(engine, db, monkeypatch):
    """The case-insensitive unique index blocks 'JOHN SMITH' next to
    'John Smith'; the entry is skipped and the batch continues."""
    from app.models.bwp import Driver

    existing = Driver(name="John Smith", simgrid_driver_id=1, created_at=_now())
    db.add(existing)
    await db.commit()

    entries = [
        _entry(id=2, display_name="JOHN SMITH", country_code="GB"),
        _entry(id=3, display_name="Other Guy", country_code="NL"),
    ]
    await _patch_and_sync(engine, entries, monkeypatch)

    result = await db.execute(select(Driver))
    names = sorted(d.name for d in result.scalars().all())
    assert names == ["John Smith", "Other Guy"]


async def test_duplicate_simgrid_ids_do_not_abort_batch(engine, db, monkeypatch):
    """Two rows sharing a simgrid_driver_id (legacy data) must not raise
    MultipleResultsFound and kill the whole sync."""
    from app.models.bwp import Driver

    db.add_all([
        Driver(name="Dup A", simgrid_driver_id=9, created_at=_now()),
        Driver(name="Dup B", simgrid_driver_id=9, created_at=_now()),
    ])
    await db.commit()

    entries = [
        _entry(id=9, display_name="Dup A", country_code="GB"),
        _entry(id=500, display_name="Survivor", country_code="SE"),
    ]
    await _patch_and_sync(engine, entries, monkeypatch)

    result = await db.execute(select(Driver).where(Driver.name == "Survivor"))
    assert result.scalar_one_or_none() is not None


async def _patch_and_link(engine, monkeypatch, user_id, discord_id, simgrid_user_id):
    """Patch the DB session + SimGrid discord lookup, then run the login link."""
    import app.database as db_module
    from app.services import simgrid as simgrid_module
    from app.services.drivers import link_driver_for_user

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_module, "async_session", factory)

    async def _fake_lookup(self, uid):
        return simgrid_user_id if uid == discord_id else None

    monkeypatch.setattr(
        type(simgrid_module.simgrid_service), "get_user_by_discord_id", _fake_lookup
    )
    await link_driver_for_user(user_id, discord_id)


async def test_login_auto_link_claims_unclaimed_driver(engine, db, monkeypatch, test_user):
    """A logged-in user whose SimGrid account has discord_uid gets linked."""
    from app.models.bwp import Driver

    driver = Driver(name="Auto Linked", simgrid_driver_id=321, created_at=_now())
    db.add(driver)
    await db.commit()

    await _patch_and_link(engine, monkeypatch, test_user.id, test_user.discord_id, 321)

    await db.refresh(driver)
    assert driver.user_id == test_user.id


async def test_login_auto_link_noop_when_user_already_linked(
    engine, db, monkeypatch, test_user
):
    from app.models.bwp import Driver

    mine = Driver(name="Already Mine", user_id=test_user.id, created_at=_now())
    other = Driver(name="Other Driver", simgrid_driver_id=321, created_at=_now())
    db.add_all([mine, other])
    await db.commit()

    await _patch_and_link(engine, monkeypatch, test_user.id, test_user.discord_id, 321)

    await db.refresh(other)
    assert other.user_id is None


async def test_login_auto_link_noop_when_simgrid_unknown(
    engine, db, monkeypatch, test_user
):
    from app.models.bwp import Driver

    driver = Driver(name="Unclaimed", simgrid_driver_id=321, created_at=_now())
    db.add(driver)
    await db.commit()

    await _patch_and_link(engine, monkeypatch, test_user.id, test_user.discord_id, None)

    await db.refresh(driver)
    assert driver.user_id is None


async def test_batch_inserts_all_new_entries(engine, db, monkeypatch):
    """All entries in a batch with no existing matches are inserted."""
    from app.models.bwp import Driver

    entries = [
        _entry(id=10, display_name="Alpha", country_code="AF"),
        _entry(id=20, display_name="Beta", country_code="BE"),
        _entry(id=30, display_name="Gamma", country_code="GR"),
    ]
    await _patch_and_sync(engine, entries, monkeypatch)

    result = await db.execute(select(Driver))
    names = {d.name for d in result.scalars().all()}
    assert names == {"Alpha", "Beta", "Gamma"}

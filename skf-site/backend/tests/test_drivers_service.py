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

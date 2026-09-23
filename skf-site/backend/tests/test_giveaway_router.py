"""End-to-end tests for the giveaway admin API.

Covers the path an admin actually walks: upload a round's results (in the
Race results tab), review the names that matched nothing, merge one, and
draw from the eligible pool.
"""

from __future__ import annotations

import pathlib
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CHAMPIONSHIP_ID = 26927


def _factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession, seed_roles):
    from app.models.user import User

    user = User(
        id=uuid.uuid4(),
        discord_id="admin-giveaway",
        username="admin",
        display_name="Admin User",
        role_id=2,
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.commit()
    result = await db.execute(
        select(User).options(joinedload(User.role)).where(User.id == user.id)
    )
    return result.scalar_one()


@pytest_asyncio.fixture
async def admin_client(engine, admin_user, simgrid_stub):
    import app.database as db_module
    from app.auth import get_current_user, get_current_user_optional
    from app.database import get_db
    from app.main import app

    factory = _factory(engine)
    original = db_module.async_session
    db_module.async_session = factory

    async def _override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_current_user_optional] = lambda: admin_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    db_module.async_session = original


async def _upload(client: AsyncClient, fixture: str, race_id: int):
    return await client.post(
        "/api/race-results/imports",
        files={"file": (fixture, (FIXTURES / fixture).read_bytes(), "text/xml")},
        data={"championshipSimgridId": str(CHAMPIONSHIP_ID), "raceSimgridId": str(race_id)},
    )


async def test_upload_parses_and_reports_the_grid(admin_client):
    resp = await _upload(admin_client, "portimao.xml", 1)

    assert resp.status_code == 201
    body = resp.json()
    assert body["raceImport"]["entryCount"] == 26
    assert body["raceImport"]["trackEvent"] == "6 Hours of Portimao"
    assert body["raceImport"]["sim"] == "lmu"
    # Nothing in the drivers table yet, so every name is unlinked.
    assert body["raceImport"]["unmatchedCount"] == 26
    assert len(body["entries"]) == 26


async def test_reuploading_a_round_replaces_it(admin_client):
    await _upload(admin_client, "portimao.xml", 1)
    await _upload(admin_client, "portimao.xml", 1)

    listed = await admin_client.get(
        "/api/giveaway/imports", params={"championshipSimgridId": CHAMPIONSHIP_ID}
    )
    # One round, counted once — not two copies inflating the round tally.
    assert len(listed.json()) == 1


async def test_rejects_a_file_that_is_not_a_race_result(admin_client):
    resp = await admin_client.post(
        "/api/race-results/imports",
        files={"file": ("notes.xml", b"<hello/>", "text/xml")},
        data={"championshipSimgridId": str(CHAMPIONSHIP_ID), "raceSimgridId": "1"},
    )
    assert resp.status_code == 400
    assert "rFactor2/LMU" in resp.json()["detail"]


async def test_eligibility_splits_the_classes(admin_client):
    await _upload(admin_client, "portimao.xml", 1)
    await _upload(admin_client, "laguna_seca.xml", 2)

    resp = await admin_client.get(
        "/api/giveaway/eligibility",
        params={
            "championshipSimgridId": CHAMPIONSHIP_ID,
            "minDistancePct": 50,
            "minRounds": 2,
        },
    )
    body = resp.json()

    assert body["importedRounds"] == 2
    assert body["carClasses"] == ["GT3", "Hyper"]

    by_class: dict[str, list[str]] = {}
    for driver in body["drivers"]:
        by_class.setdefault(driver["carClass"], []).append(driver["displayName"])

    assert sorted(by_class["Hyper"]) == [
        "Arsen Petrosian", "Max Tarasenko", "Sergiy Gaydabura", "Vladyslav Mykhailenko",
    ]
    assert len(by_class["GT3"]) == 10


async def test_eligibility_exposes_the_per_round_arithmetic(admin_client):
    """Every qualifying round must be auditable, not just counted."""
    await _upload(admin_client, "portimao.xml", 1)

    resp = await admin_client.get(
        "/api/giveaway/eligibility",
        params={"championshipSimgridId": CHAMPIONSHIP_ID, "minDistancePct": 50, "minRounds": 1},
    )
    driver = next(
        d for d in resp.json()["drivers"] if d["displayName"] == "Dmitriy Bondariev"
    )
    round_row = driver["rounds"][0]

    assert round_row["laps"] == 22
    assert round_row["classLeaderLaps"] == 40
    assert round_row["distancePct"] == 55.0
    assert round_row["qualifies"] is True
    assert round_row["roundLabel"] == "6 Hours of Portimao"


async def test_unmatched_names_are_listed_with_suggestions_only(admin_client, db):
    from app.models.bwp import Driver

    db.add(Driver(id=uuid.uuid4(), name="Maksym Tarasenko"))
    await db.commit()

    await _upload(admin_client, "laguna_seca.xml", 2)
    resp = await admin_client.get(
        "/api/giveaway/unmatched", params={"championshipSimgridId": CHAMPIONSHIP_ID}
    )
    names = {n["rawName"]: n for n in resp.json()}

    # "Max Tarasenko" did not auto-link to "Maksym Tarasenko" — it is only
    # suggested. Auto-applying the closest string is how two different drivers
    # get merged.
    assert "Max Tarasenko" in names
    assert "Maksym Tarasenko" in names["Max Tarasenko"]["suggestions"]


async def test_case_only_spelling_differences_link_automatically(admin_client, db):
    from app.models.bwp import Driver

    db.add(Driver(id=uuid.uuid4(), name="Andrii Lotochynskyi"))
    await db.commit()

    resp = await _upload(admin_client, "laguna_seca.xml", 2)
    entry = next(e for e in resp.json()["entries"] if e["rawName"] == "Andrii lotochynskyi")
    assert entry["matched"] is True


async def test_merging_a_name_joins_the_rounds(admin_client):
    """The split-identity problem the alias table exists to solve."""
    await _upload(admin_client, "portimao.xml", 1)
    await _upload(admin_client, "laguna_seca.xml", 2)

    params = {
        "championshipSimgridId": CHAMPIONSHIP_ID,
        "minDistancePct": 50,
        "minRounds": 2,
    }
    before = await admin_client.get("/api/giveaway/eligibility", params=params)
    hyper_before = [d for d in before.json()["drivers"] if d["carClass"] == "Hyper"]
    assert not any(d["displayName"] == "Jaz Whitfield" for d in hyper_before)

    # Whitfield raced only Portimao; Kenneth only shows there too. Merge a name
    # that appears in exactly one round into one that appears in the other.
    merged = await admin_client.post(
        "/api/giveaway/aliases",
        json={"normalizedAlias": "jaz whitfield", "canonicalDisplayName": "Max Tarasenko"},
    )
    assert merged.status_code == 201

    after = await admin_client.get("/api/giveaway/eligibility", params=params)
    tarasenko = next(
        d for d in after.json()["drivers"]
        if d["displayName"] == "Max Tarasenko" and d["carClass"] == "Hyper"
    )
    # Portimao (as Whitfield) + Laguna Seca (as himself) = 3 qualifying rounds,
    # because he also raced Portimao under his own name.
    assert tarasenko["qualifyingRounds"] == 3


async def test_alias_refuses_to_merge_a_name_into_itself(admin_client):
    resp = await admin_client.post(
        "/api/giveaway/aliases",
        json={"normalizedAlias": "Max Tarasenko", "canonicalDisplayName": "max tarasenko"},
    )
    assert resp.status_code == 400


async def test_deleting_an_import_removes_its_rounds(admin_client):
    created = await _upload(admin_client, "portimao.xml", 1)
    import_id = created.json()["raceImport"]["id"]

    resp = await admin_client.delete(f"/api/race-results/imports/{import_id}")
    assert resp.status_code == 204

    listed = await admin_client.get(
        "/api/giveaway/imports", params={"championshipSimgridId": CHAMPIONSHIP_ID}
    )
    assert listed.json() == []


async def test_endpoints_are_closed_to_non_admins(client):
    for path in ("/api/giveaway/imports", "/api/giveaway/eligibility", "/api/giveaway/unmatched"):
        resp = await client.get(path, params={"championshipSimgridId": CHAMPIONSHIP_ID})
        assert resp.status_code in (401, 403), path


async def test_merging_backfills_the_driver_link_on_existing_rows(admin_client, db):
    """A merge must fix rows already imported under the old spelling."""
    from app.models.bwp import Driver
    from app.models.race_result import RaceResultEntry

    db.add(Driver(id=uuid.uuid4(), name="Maksym Tarasenko"))
    await db.commit()

    await _upload(admin_client, "laguna_seca.xml", 2)

    before = await db.execute(
        select(RaceResultEntry.driver_id).where(
            RaceResultEntry.normalized_name == "max tarasenko"
        )
    )
    assert before.scalars().all() == [None]

    resp = await admin_client.post(
        "/api/giveaway/aliases",
        json={"normalizedAlias": "max tarasenko", "canonicalDisplayName": "Maksym Tarasenko"},
    )
    assert resp.status_code == 201
    assert resp.json()["driverId"] is not None

    after = await db.execute(
        select(RaceResultEntry.driver_id).where(
            RaceResultEntry.normalized_name == "max tarasenko"
        )
    )
    assert all(v is not None for v in after.scalars().all())

    # And it drops off the review list.
    unmatched = await admin_client.get(
        "/api/giveaway/unmatched", params={"championshipSimgridId": CHAMPIONSHIP_ID}
    )
    assert "Max Tarasenko" not in {n["rawName"] for n in unmatched.json()}

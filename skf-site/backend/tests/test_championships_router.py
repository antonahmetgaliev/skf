"""Tests for the SimGrid championship proxy and active-championship flags.

SimGrid is never reached: ``simgrid_stub`` serves details and races, and the
list and standings calls are stubbed here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from tests.conftest import LMU_CHAMPIONSHIP_ID


def _factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession, seed_roles):
    from app.models.user import User

    user = User(
        id=uuid.uuid4(),
        discord_id="admin-championships",
        username="admin",
        display_name="Admin User",
        role_id=2,
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.commit()
    result = await db.execute(select(User).options(joinedload(User.role)).where(User.id == user.id))
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


@pytest.fixture
def simgrid_lists(monkeypatch, simgrid_stub):
    """Stub the championship list and standings on top of ``simgrid_stub``."""
    from app.schemas.championship import ChampionshipListItem, ChampionshipStandingsData
    from app.services import simgrid as sg_mod

    state = {"fail": False, "synced": []}

    async def get_championships():
        if state["fail"]:
            raise RuntimeError("SimGrid is down")
        return [
            ChampionshipListItem(id=1, name="Active Cup"),
            ChampionshipListItem(id=2, name="Old Cup"),
        ]

    async def get_standings(championship_id):
        return ChampionshipStandingsData(entries=[], races=[]), True

    async def sync(entries, championship_id):
        state["synced"].append(championship_id)

    monkeypatch.setattr(sg_mod.simgrid_service, "get_championships", get_championships)
    monkeypatch.setattr(sg_mod.simgrid_service, "get_standings", get_standings)
    monkeypatch.setattr("app.api.v1.championships.sync_drivers_from_standings", sync)
    return state


async def test_active_championships_put_is_idempotent(admin_client):
    first = await admin_client.put("/api/v1/active-championships/1")
    assert first.status_code == 201
    assert first.headers["location"] == "/api/v1/active-championships/1"
    assert first.json()["simgridId"] == 1

    again = await admin_client.put("/api/v1/active-championships/1")
    assert again.status_code == 200
    assert again.json()["simgridId"] == 1

    assert (await admin_client.get("/api/v1/active-championships")).json() == [1]

    resp = await admin_client.delete("/api/v1/active-championships/1")
    assert resp.status_code == 204
    assert (await admin_client.get("/api/v1/active-championships")).json() == []


async def test_active_championships_are_admin_only_to_change(client):
    assert (await client.get("/api/v1/active-championships")).status_code == 200
    assert (await client.put("/api/v1/active-championships/1")).status_code in (401, 403)
    assert (await client.delete("/api/v1/active-championships/1")).status_code in (401, 403)


async def test_admins_see_every_championship_inactive_ones_completed(admin_client, simgrid_lists):
    await admin_client.put("/api/v1/active-championships/1")

    body = (await admin_client.get("/api/v1/championships")).json()
    assert [(c["id"], c["eventCompleted"]) for c in body] == [(1, False), (2, True)]


async def test_the_public_sees_only_active_championships(client, db, simgrid_lists):
    from app.models.active_championship import ActiveChampionship

    db.add(ActiveChampionship(simgrid_id=1))
    await db.commit()

    body = (await client.get("/api/v1/championships")).json()
    assert [c["id"] for c in body] == [1]


async def test_simgrid_outage_is_a_502_problem(client, simgrid_lists):
    simgrid_lists["fail"] = True
    resp = await client.get("/api/v1/championships")
    assert resp.status_code == 502
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["detail"] == "Failed to fetch championships from SimGrid."


async def test_championship_details_and_races(admin_client, simgrid_stub):
    simgrid_stub.races[LMU_CHAMPIONSHIP_ID] = [
        {"id": 2, "race_name": "Spa", "starts_at": "2026-09-19T18:00:00Z"},
        {"id": 1, "display_name": "Laguna Seca", "starts_at": "2026-09-12T18:00:00Z",
         "track": {"name": "Laguna Seca"}},
    ]

    details = await admin_client.get(f"/api/v1/championships/{LMU_CHAMPIONSHIP_ID}")
    assert details.status_code == 200
    assert details.json()["gameName"] == "Le Mans Ultimate"

    races = (await admin_client.get(f"/api/v1/championships/{LMU_CHAMPIONSHIP_ID}/races")).json()
    assert [(r["id"], r["displayName"]) for r in races] == [(1, "Laguna Seca"), (2, "Spa")]
    assert races[0]["track"] == "Laguna Seca"


async def test_unknown_championship_is_a_502(client):
    # Without the stub every SimGrid lookup fails (see conftest).
    resp = await client.get("/api/v1/championships/123")
    assert resp.status_code == 502


async def test_live_standings_sync_drivers(admin_client, simgrid_lists):
    resp = await admin_client.get(f"/api/v1/championships/{LMU_CHAMPIONSHIP_ID}/standings")
    assert resp.status_code == 200
    assert resp.json() == {"entries": [], "races": []}
    assert simgrid_lists["synced"] == [LMU_CHAMPIONSHIP_ID]


async def test_rounds_are_admin_only(client):
    resp = await client.get(f"/api/v1/championships/{LMU_CHAMPIONSHIP_ID}/rounds")
    assert resp.status_code in (401, 403)


async def test_old_paths_are_gone(admin_client):
    assert (await admin_client.get("/api/championships/active")).status_code == 404
    assert (await admin_client.get("/api/giveaway/aliases")).status_code == 404

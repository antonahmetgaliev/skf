"""Tests for the reworked incident system (N-driver, per-driver resolution)."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("INCIDENT_API_TOKEN", "test-token-secret")
os.environ.setdefault("YOUTUBE_API_KEY", "fake")
os.environ.setdefault("YOUTUBE_CHANNEL_ID", "fake")

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import _make_engine, _factory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine():
    _engine, tables = _make_engine()
    async with _engine.begin() as conn:
        await conn.run_sync(lambda c: [t.create(c, checkfirst=True) for t in tables])
    yield _engine
    await _engine.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    async with _factory(engine)() as session:
        yield session


@pytest_asyncio.fixture
async def seed_roles(db: AsyncSession):
    from app.models.user import Role
    db.add_all([
        Role(id=1, name="driver"),
        Role(id=2, name="admin"),
        Role(id=3, name="super_admin"),
        Role(id=4, name="racing_judge"),
    ])
    await db.commit()


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession, seed_roles):
    from app.models.user import User
    u = User(
        id=uuid.uuid4(),
        discord_id="admin001",
        username="admin",
        display_name="Admin User",
        role_id=2,
        created_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    result = await db.execute(
        select(User).options(joinedload(User.role)).where(User.id == u.id)
    )
    return result.scalar_one()


@pytest_asyncio.fixture
async def judge_user(db: AsyncSession, seed_roles):
    from app.models.user import User
    u = User(
        id=uuid.uuid4(),
        discord_id="judge001",
        username="judge",
        display_name="Judge User",
        role_id=4,
        created_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()
    result = await db.execute(
        select(User).options(joinedload(User.role)).where(User.id == u.id)
    )
    return result.scalar_one()


def _make_client(engine, user=None):
    """Build an AsyncClient, optionally injecting *user* as the current user.

    Returns a context-manager-compatible AsyncClient.
    IMPORTANT: Caller is responsible for clearing dependency_overrides after.
    """
    import app.database as db_module
    from app.database import get_db
    from app.main import app

    factory = _factory(engine)

    async def _override_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    db_module.async_session = factory

    if user is not None:
        from app.auth import get_current_user, get_current_user_optional
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_current_user_optional] = lambda: user

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _set_auth_user(user):
    """Swap the currently-overridden auth user on the shared app."""
    from app.auth import get_current_user, get_current_user_optional
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_user_optional] = lambda: user


@pytest_asyncio.fixture
async def client(engine):
    """Unauthenticated client."""
    from app.main import app
    async with _make_client(engine) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_client(engine, admin_user):
    from app.main import app
    async with _make_client(engine, admin_user) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def judge_client(engine, judge_user):
    from app.main import app
    async with _make_client(engine, judge_user) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def shared_client(engine, admin_user, judge_user):
    """A single client that can switch between admin and judge auth."""
    from app.main import app
    async with _make_client(engine, admin_user) as ac:
        ac._admin_user = admin_user
        ac._judge_user = judge_user
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INGEST_URL = "/api/incidents/ingest"

async def _coro(value):
    """Wrap a value in a coroutine (for monkeypatching async methods)."""
    return value

BATCH_PAYLOAD = {
    "raceId": 142899,
    "championshipId": 20697,
    "incidents": [
        {
            "sessionName": "RACE",
            "time": "0:05:51",
            "drivers": ["Serhii Kachan", "Maksym Bunich", "Oleksandr Dovmat"],
        },
        {
            "sessionName": "RACE",
            "time": "0:33:22",
            "drivers": ["Anton Dorokhin", "Oleksii Lissov"],
        },
    ],
}


# =====================================================================
# Token auth
# =====================================================================

class TestTokenAuth:
    @pytest.mark.anyio
    async def test_ingest_no_token(self, client: AsyncClient):
        resp = await client.post(INGEST_URL, json=BATCH_PAYLOAD)
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_ingest_bad_token(self, client: AsyncClient):
        resp = await client.post(
            INGEST_URL,
            json=BATCH_PAYLOAD,
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_ingest_valid_token_no_window(self, client: AsyncClient, monkeypatch):
        """Auth passes, auto-creates window → 201."""
        from app.services import simgrid as sg_mod
        monkeypatch.setattr(sg_mod.simgrid_service, "get_race_name", lambda _: _coro("Test Race"))
        resp = await client.post(
            INGEST_URL,
            json=BATCH_PAYLOAD,
            headers={"Authorization": "Bearer test-token-secret"},
        )
        assert resp.status_code == 201


# =====================================================================
# Batch ingestion
# =====================================================================

class TestBatchIngestion:

    INGEST_HEADERS = {"Authorization": "Bearer test-token-secret"}

    @pytest.mark.anyio
    async def test_creates_window_and_incidents(self, client: AsyncClient, monkeypatch):
        from app.services import simgrid as sg_mod
        monkeypatch.setattr(sg_mod.simgrid_service, "get_race_name", lambda _: _coro("Ignition League - Round 1"))
        resp = await client.post(
            INGEST_URL,
            json=BATCH_PAYLOAD,
            headers=self.INGEST_HEADERS,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["raceName"] == "Ignition League - Round 1"
        assert data["raceId"] == 142899
        assert data["championshipId"] == 20697
        assert len(data["incidents"]) == 2
        # First incident has 3 drivers
        inc0 = data["incidents"][0]
        assert len(inc0["drivers"]) == 3
        assert inc0["drivers"][0]["driverName"] == "Serhii Kachan"
        assert inc0["sessionName"] == "RACE"
        assert inc0["time"] == "0:05:51"
        # Second incident has 2 drivers
        inc1 = data["incidents"][1]
        assert len(inc1["drivers"]) == 2

    @pytest.mark.anyio
    async def test_reuses_existing_window(self, client: AsyncClient, monkeypatch):
        from app.services import simgrid as sg_mod
        monkeypatch.setattr(sg_mod.simgrid_service, "get_race_name", lambda _: _coro("Ignition League - Round 1"))
        resp1 = await client.post(
            INGEST_URL, json=BATCH_PAYLOAD, headers=self.INGEST_HEADERS
        )
        assert resp1.status_code == 201
        window_id_1 = resp1.json()["id"]

        resp2 = await client.post(
            INGEST_URL, json=BATCH_PAYLOAD, headers=self.INGEST_HEADERS
        )
        assert resp2.status_code == 201
        window_id_2 = resp2.json()["id"]
        assert window_id_1 == window_id_2
        # Should now have 4 incidents (2 + 2)
        assert len(resp2.json()["incidents"]) == 4

    @pytest.mark.anyio
    async def test_driver_matching(
        self, client: AsyncClient, db: AsyncSession, monkeypatch
    ):
        """When a BWP Driver exists with the same name, the incident_driver should link to it."""
        from app.services import simgrid as sg_mod
        monkeypatch.setattr(sg_mod.simgrid_service, "get_race_name", lambda _: _coro("Test Race"))
        from app.models.bwp import Driver
        drv = Driver(name="Serhii Kachan")
        db.add(drv)
        await db.commit()
        await db.refresh(drv)

        resp = await client.post(
            INGEST_URL, json=BATCH_PAYLOAD, headers=self.INGEST_HEADERS
        )
        assert resp.status_code == 201
        inc0 = resp.json()["incidents"][0]
        matched = [d for d in inc0["drivers"] if d["driverName"] == "Serhii Kachan"]
        assert matched[0]["driverId"] == str(drv.id)


# =====================================================================
# Manual file incident
# =====================================================================

class TestFileIncident:
    @pytest.mark.anyio
    async def test_file_incident_creates_incident(self, admin_client: AsyncClient):
        # First create a window
        w_resp = await admin_client.post(
            "/api/incidents/windows",
            json={"raceName": "Spa GP", "intervalHours": 48},
        )
        assert w_resp.status_code == 201
        window_id = w_resp.json()["id"]

        # File an incident with 3 drivers
        resp = await admin_client.post(
            f"/api/incidents/windows/{window_id}/incidents",
            json={
                "sessionName": "QUALIFYING",
                "time": "0:12:00",
                "description": "Contact in Eau Rouge",
                "drivers": ["Driver A", "Driver B", "Driver C"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["drivers"]) == 3
        assert data["sessionName"] == "QUALIFYING"
        assert data["description"] == "Contact in Eau Rouge"

    @pytest.mark.anyio
    async def test_file_incident_closed_window(self, admin_client: AsyncClient):
        w_resp = await admin_client.post(
            "/api/incidents/windows",
            json={"raceName": "Closed Race", "intervalHours": 1},
        )
        window_id = w_resp.json()["id"]
        # Close the window
        await admin_client.patch(
            f"/api/incidents/windows/{window_id}",
            json={"isManuallyClosed": True},
        )
        # Try filing — should fail
        resp = await admin_client.post(
            f"/api/incidents/windows/{window_id}/incidents",
            json={"drivers": ["Driver A"]},
        )
        assert resp.status_code == 409


# =====================================================================
# Per-driver resolve
# =====================================================================

class TestResolveDriver:
    @pytest.mark.anyio
    async def test_resolve_driver(self, shared_client: AsyncClient):
        ac = shared_client
        # Create window as admin
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(
            "/api/incidents/windows",
            json={"raceName": "Resolve Test", "intervalHours": 48},
        )
        assert w_resp.status_code == 201
        window_id = w_resp.json()["id"]
        await ac.post(
            f"/api/incidents/windows/{window_id}/incidents",
            json={"drivers": ["Driver A", "Driver B"]},
        )
        # Get window to find driver IDs
        w = await ac.get(f"/api/incidents/windows/{window_id}")
        driver_id = w.json()["incidents"][0]["drivers"][0]["id"]

        # Judge resolves driver
        _set_auth_user(ac._judge_user)
        resp = await ac.patch(
            f"/api/incidents/drivers/{driver_id}/resolve",
            json={"verdict": "5s Time Penalty", "bwpPoints": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["resolution"]["verdict"] == "5s Time Penalty"
        assert data["resolution"]["bwpPoints"] == 2
        assert data["resolution"]["bwpApplied"] is False

    @pytest.mark.anyio
    async def test_resolve_updates_incident_status(self, shared_client: AsyncClient):
        """When all drivers in an incident are resolved, incident status → resolved."""
        ac = shared_client
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(
            "/api/incidents/windows",
            json={"raceName": "Status Test", "intervalHours": 48},
        )
        assert w_resp.status_code == 201
        window_id = w_resp.json()["id"]
        await ac.post(
            f"/api/incidents/windows/{window_id}/incidents",
            json={"drivers": ["D1", "D2"]},
        )
        w = await ac.get(f"/api/incidents/windows/{window_id}")
        incident = w.json()["incidents"][0]
        d1_id = incident["drivers"][0]["id"]
        d2_id = incident["drivers"][1]["id"]

        # Resolve first driver as judge — incident still open
        _set_auth_user(ac._judge_user)
        await ac.patch(
            f"/api/incidents/drivers/{d1_id}/resolve",
            json={"verdict": "Warning"},
        )
        _set_auth_user(ac._admin_user)
        w = await ac.get(f"/api/incidents/windows/{window_id}")
        assert w.json()["incidents"][0]["status"] == "open"

        # Resolve second driver — incident becomes resolved
        _set_auth_user(ac._judge_user)
        await ac.patch(
            f"/api/incidents/drivers/{d2_id}/resolve",
            json={"verdict": "NFA"},
        )
        _set_auth_user(ac._admin_user)
        w = await ac.get(f"/api/incidents/windows/{window_id}")
        assert w.json()["incidents"][0]["status"] == "resolved"


# =====================================================================
# BWP apply / discard
# =====================================================================

class TestBwpApplyDiscard:
    @pytest.mark.anyio
    async def test_apply_bwp_creates_bwp_point(
        self, shared_client: AsyncClient, db: AsyncSession
    ):
        from app.models.bwp import Driver, BwpPoint
        ac = shared_client

        # Create a BWP driver to link
        drv = Driver(name="Apply Target")
        db.add(drv)
        await db.commit()
        await db.refresh(drv)

        # Window + incident as admin
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(
            "/api/incidents/windows",
            json={"raceName": "BWP Test", "intervalHours": 48},
        )
        assert w_resp.status_code == 201
        window_id = w_resp.json()["id"]
        await ac.post(
            f"/api/incidents/windows/{window_id}/incidents",
            json={"drivers": ["Apply Target"]},
        )
        w = await ac.get(f"/api/incidents/windows/{window_id}")
        driver_entry = w.json()["incidents"][0]["drivers"][0]
        driver_entry_id = driver_entry["id"]
        # Should have matched BWP driver
        assert driver_entry["driverId"] == str(drv.id)

        # Judge resolves with BWP
        _set_auth_user(ac._judge_user)
        await ac.patch(
            f"/api/incidents/drivers/{driver_entry_id}/resolve",
            json={"verdict": "Drive Through", "bwpPoints": 3},
        )

        # Admin applies BWP
        _set_auth_user(ac._admin_user)
        resp = await ac.patch(
            f"/api/incidents/drivers/{driver_entry_id}/apply-bwp",
        )
        assert resp.status_code == 200
        assert resp.json()["resolution"]["bwpApplied"] is True

        # Verify BwpPoint was created
        result = await db.execute(
            select(BwpPoint).where(BwpPoint.driver_id == drv.id)
        )
        bp = result.scalar_one_or_none()
        assert bp is not None
        assert bp.points == 3

    @pytest.mark.anyio
    async def test_apply_bwp_no_resolution(self, admin_client: AsyncClient):
        """Apply BWP before resolution → 409."""
        w_resp = await admin_client.post(
            "/api/incidents/windows",
            json={"raceName": "No Resolve", "intervalHours": 48},
        )
        window_id = w_resp.json()["id"]
        await admin_client.post(
            f"/api/incidents/windows/{window_id}/incidents",
            json={"drivers": ["Unresolved"]},
        )
        w = await admin_client.get(f"/api/incidents/windows/{window_id}")
        driver_id = w.json()["incidents"][0]["drivers"][0]["id"]

        resp = await admin_client.patch(f"/api/incidents/drivers/{driver_id}/apply-bwp")
        assert resp.status_code == 409

    @pytest.mark.anyio
    async def test_discard_bwp(self, shared_client: AsyncClient):
        ac = shared_client
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(
            "/api/incidents/windows",
            json={"raceName": "Discard Test", "intervalHours": 48},
        )
        assert w_resp.status_code == 201
        window_id = w_resp.json()["id"]
        await ac.post(
            f"/api/incidents/windows/{window_id}/incidents",
            json={"drivers": ["Discard Target"]},
        )
        w = await ac.get(f"/api/incidents/windows/{window_id}")
        driver_id = w.json()["incidents"][0]["drivers"][0]["id"]

        # Judge resolves
        _set_auth_user(ac._judge_user)
        await ac.patch(
            f"/api/incidents/drivers/{driver_id}/resolve",
            json={"verdict": "Warning", "bwpPoints": 1},
        )

        # Admin discards
        _set_auth_user(ac._admin_user)
        resp = await ac.patch(
            f"/api/incidents/drivers/{driver_id}/discard",
        )
        assert resp.status_code == 200
        res = resp.json()["resolution"]
        assert res["bwpPoints"] is None
        assert res["bwpApplied"] is False


# =====================================================================
# Window CRUD (basic smoke tests — existing logic mostly unchanged)
# =====================================================================

class TestWindowCrud:
    @pytest.mark.anyio
    async def test_list_windows(self, admin_client: AsyncClient):
        resp = await admin_client.get("/api/incidents/windows")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.anyio
    async def test_create_delete_window(self, admin_client: AsyncClient):
        resp = await admin_client.post(
            "/api/incidents/windows",
            json={"raceName": "Test Create", "intervalHours": 24},
        )
        assert resp.status_code == 201
        wid = resp.json()["id"]

        del_resp = await admin_client.delete(f"/api/incidents/windows/{wid}")
        assert del_resp.status_code == 204


# =====================================================================
# Verdict rules CRUD
# =====================================================================

RULES_URL = "/api/incidents/verdict-rules"


class TestVerdictRules:
    @pytest.mark.anyio
    async def test_list_verdict_rules(self, admin_client: AsyncClient):
        resp = await admin_client.get(RULES_URL)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.anyio
    async def test_create_verdict_rule(self, admin_client: AsyncClient):
        resp = await admin_client.post(
            RULES_URL,
            json={"verdict": "New Penalty", "defaultBwp": 5},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["verdict"] == "New Penalty"
        assert data["defaultBwp"] == 5
        assert data["sortOrder"] >= 1

    @pytest.mark.anyio
    async def test_update_verdict_rule(self, admin_client: AsyncClient):
        # Create
        create_resp = await admin_client.post(
            RULES_URL,
            json={"verdict": "Old Name", "defaultBwp": 1},
        )
        rule_id = create_resp.json()["id"]

        # Update
        resp = await admin_client.patch(
            f"{RULES_URL}/{rule_id}",
            json={"verdict": "Updated Name", "defaultBwp": 3},
        )
        assert resp.status_code == 200
        assert resp.json()["verdict"] == "Updated Name"
        assert resp.json()["defaultBwp"] == 3

    @pytest.mark.anyio
    async def test_delete_verdict_rule(self, admin_client: AsyncClient):
        create_resp = await admin_client.post(
            RULES_URL,
            json={"verdict": "To Delete", "defaultBwp": 0},
        )
        rule_id = create_resp.json()["id"]

        del_resp = await admin_client.delete(f"{RULES_URL}/{rule_id}")
        assert del_resp.status_code == 204

        # Verify it's gone
        get_resp = await admin_client.get(RULES_URL)
        ids = [r["id"] for r in get_resp.json()]
        assert rule_id not in ids

    @pytest.mark.anyio
    async def test_create_requires_admin(self, judge_client: AsyncClient):
        resp = await judge_client.post(
            RULES_URL,
            json={"verdict": "Unauthorized", "defaultBwp": 0},
        )
        assert resp.status_code == 403


# =====================================================================
# Bulk resolve (one button per incident)
# =====================================================================

class TestBulkResolve:
    @pytest.mark.anyio
    async def test_bulk_resolve_all_drivers(self, shared_client: AsyncClient):
        ac = shared_client
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(
            "/api/incidents/windows",
            json={"raceName": "Bulk Test", "intervalHours": 48},
        )
        assert w_resp.status_code == 201
        window_id = w_resp.json()["id"]
        await ac.post(
            f"/api/incidents/windows/{window_id}/incidents",
            json={"drivers": ["D1", "D2", "D3"]},
        )
        w = await ac.get(f"/api/incidents/windows/{window_id}")
        inc = w.json()["incidents"][0]
        incident_id = inc["id"]
        drivers = inc["drivers"]

        # Judge bulk resolves all three drivers at once
        _set_auth_user(ac._judge_user)
        resp = await ac.patch(
            f"/api/incidents/{incident_id}/resolve",
            json={
                "description": "D1 caused a collision, D2 and D3 are victims",
                "drivers": [
                    {"incidentDriverId": drivers[0]["id"], "verdict": "TP +5s", "bwpPoints": 2},
                    {"incidentDriverId": drivers[1]["id"], "verdict": "NFA", "bwpPoints": 0},
                    {"incidentDriverId": drivers[2]["id"], "verdict": "NFA", "bwpPoints": 0},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"
        assert len(data["drivers"]) == 3
        # All have resolutions
        for d in data["drivers"]:
            assert d["resolution"] is not None
            assert d["resolution"]["description"] == "D1 caused a collision, D2 and D3 are victims"
        # First driver got TP +5s
        assert data["drivers"][0]["resolution"]["verdict"] == "TP +5s"
        assert data["drivers"][0]["resolution"]["bwpPoints"] == 2

    @pytest.mark.anyio
    async def test_bulk_resolve_partial_update(self, shared_client: AsyncClient):
        """Bulk resolve can update already-resolved drivers."""
        ac = shared_client
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(
            "/api/incidents/windows",
            json={"raceName": "Partial Update", "intervalHours": 48},
        )
        window_id = w_resp.json()["id"]
        await ac.post(
            f"/api/incidents/windows/{window_id}/incidents",
            json={"drivers": ["D1"]},
        )
        w = await ac.get(f"/api/incidents/windows/{window_id}")
        inc = w.json()["incidents"][0]
        drv_id = inc["drivers"][0]["id"]

        # First resolve
        _set_auth_user(ac._judge_user)
        await ac.patch(
            f"/api/incidents/{inc['id']}/resolve",
            json={"drivers": [{"incidentDriverId": drv_id, "verdict": "Warning"}]},
        )

        # Update with new verdict + description
        resp = await ac.patch(
            f"/api/incidents/{inc['id']}/resolve",
            json={
                "description": "Changed after review",
                "drivers": [{"incidentDriverId": drv_id, "verdict": "TP +5s", "bwpPoints": 2}],
            },
        )
        assert resp.status_code == 200
        res = resp.json()["drivers"][0]["resolution"]
        assert res["verdict"] == "TP +5s"
        assert res["bwpPoints"] == 2
        assert res["description"] == "Changed after review"


# =====================================================================
# Description presets CRUD
# =====================================================================

DESC_URL = "/api/incidents/description-presets"


class TestDescriptionPresets:
    @pytest.mark.anyio
    async def test_list_description_presets(self, admin_client: AsyncClient):
        resp = await admin_client.get(DESC_URL)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.anyio
    async def test_create_description_preset(self, admin_client: AsyncClient):
        resp = await admin_client.post(
            DESC_URL,
            json={"text": "Test description"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["text"] == "Test description"
        assert data["sortOrder"] >= 1

    @pytest.mark.anyio
    async def test_update_description_preset(self, admin_client: AsyncClient):
        create_resp = await admin_client.post(
            DESC_URL,
            json={"text": "Old text"},
        )
        preset_id = create_resp.json()["id"]

        resp = await admin_client.patch(
            f"{DESC_URL}/{preset_id}",
            json={"text": "Updated text"},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "Updated text"

    @pytest.mark.anyio
    async def test_delete_description_preset(self, admin_client: AsyncClient):
        create_resp = await admin_client.post(
            DESC_URL,
            json={"text": "To Delete"},
        )
        preset_id = create_resp.json()["id"]

        del_resp = await admin_client.delete(f"{DESC_URL}/{preset_id}")
        assert del_resp.status_code == 204

        get_resp = await admin_client.get(DESC_URL)
        ids = [p["id"] for p in get_resp.json()]
        assert preset_id not in ids

    @pytest.mark.anyio
    async def test_create_requires_admin(self, judge_client: AsyncClient):
        resp = await judge_client.post(
            DESC_URL,
            json={"text": "Unauthorized"},
        )
        assert resp.status_code == 403

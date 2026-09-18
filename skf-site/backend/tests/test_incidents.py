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
        assert inc0["source"] == "ingested"
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

        # File an incident with lap and corner
        resp = await admin_client.post(
            f"/api/incidents/windows/{window_id}/incidents",
            json={
                "lap": "5",
                "corner": "Eau Rouge",
                "description": "Contact in Eau Rouge",
                "drivers": ["Driver A", "Driver B", "Driver C"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["drivers"]) == 3
        assert data["lap"] == "5"
        assert data["corner"] == "Eau Rouge"
        assert data["description"] == "Contact in Eau Rouge"
        assert data["source"] == "filed"

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

    @pytest.mark.anyio
    async def test_file_incident_unauthenticated(self, shared_client: AsyncClient):
        ac = shared_client
        # Admin creates a window
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(
            "/api/incidents/windows",
            json={"raceName": "Anon Filing", "intervalHours": 48},
        )
        window_id = w_resp.json()["id"]

        # Clear auth to simulate unauthenticated user
        from app.auth import get_current_user, get_current_user_optional
        from app.main import app
        app.dependency_overrides[get_current_user] = lambda: (_ for _ in ()).throw(
            __import__('fastapi').HTTPException(status_code=401)
        )
        app.dependency_overrides[get_current_user_optional] = lambda: None

        # Unauthenticated user files an incident
        resp = await ac.post(
            f"/api/incidents/windows/{window_id}/incidents",
            json={
                "lap": "3",
                "corner": "Turn 1",
                "drivers": ["Driver X", "Driver Y"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["reporterUserId"] is None
        assert data["source"] == "filed"
        assert len(data["drivers"]) == 2
        assert data["lap"] == "3"

        # Restore admin auth for subsequent tests
        _set_auth_user(ac._admin_user)


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
# Publishing issues BWP
# =====================================================================

async def _resolved_window(ac: AsyncClient, name: str, rows: list[tuple[str, str, int]]):
    """Window + one incident per row, each resolved with the given verdict/points.

    rows: (driver_name, verdict, bwp_points)
    """
    _set_auth_user(ac._admin_user)
    w_resp = await ac.post(
        "/api/incidents/windows", json={"raceName": name, "intervalHours": 48}
    )
    window_id = w_resp.json()["id"]
    for driver_name, _verdict, _pts in rows:
        await ac.post(
            f"/api/incidents/windows/{window_id}/incidents",
            json={"drivers": [driver_name]},
        )

    w = await ac.get(f"/api/incidents/windows/{window_id}")
    incidents = w.json()["incidents"]

    _set_auth_user(ac._judge_user)
    for inc, (_name, verdict, pts) in zip(incidents, rows):
        await ac.patch(
            f"/api/incidents/{inc['id']}/resolve",
            json={
                "drivers": [
                    {
                        "incidentDriverId": inc["drivers"][0]["id"],
                        "verdict": verdict,
                        "bwpPoints": pts,
                    }
                ]
            },
        )
    return window_id


class TestPublishAppliesBwp:
    """BWP reaches the licence when the window is published, not by hand."""

    @pytest.mark.anyio
    async def test_publish_all_creates_bwp_points(
        self, shared_client: AsyncClient, db: AsyncSession
    ):
        from app.models.bwp import Driver, BwpPoint

        db.add_all([
            Driver(id=uuid.uuid4(), name="Penalised One"),
            Driver(id=uuid.uuid4(), name="Penalised Two"),
            Driver(id=uuid.uuid4(), name="Innocent"),
        ])
        await db.commit()

        ac = shared_client
        window_id = await _resolved_window(ac, "Issue BWP", [
            ("Penalised One", "TP +5s", 2),
            ("Penalised Two", "DT", 6),
            ("Innocent", "NFA", 0),
        ])

        _set_auth_user(ac._judge_user)
        resp = await ac.post(f"/api/incidents/windows/{window_id}/publish-all")
        assert resp.status_code == 200

        points = (await db.execute(select(BwpPoint))).scalars().all()
        assert sorted(p.points for p in points) == [2, 6]
        for p in points:
            assert (p.expires_on - p.issued_on).days == 90

        for inc in resp.json()["incidents"]:
            assert inc["isPublished"] is True

    @pytest.mark.anyio
    async def test_publish_all_is_idempotent(
        self, shared_client: AsyncClient, db: AsyncSession
    ):
        """Republishing a window must not double anyone's penalty."""
        from app.models.bwp import Driver, BwpPoint

        db.add(Driver(id=uuid.uuid4(), name="Twice Published"))
        await db.commit()

        ac = shared_client
        window_id = await _resolved_window(
            ac, "Twice", [("Twice Published", "TP +30s", 5)]
        )

        _set_auth_user(ac._judge_user)
        await ac.post(f"/api/incidents/windows/{window_id}/publish-all")
        await ac.post(f"/api/incidents/windows/{window_id}/publish-all")

        points = (await db.execute(select(BwpPoint))).scalars().all()
        assert len(points) == 1
        assert points[0].points == 5

    @pytest.mark.anyio
    async def test_publish_links_driver_by_name(
        self, shared_client: AsyncClient, db: AsyncSession
    ):
        """A driver created after the incident was filed still gets matched."""
        from app.models.bwp import Driver, BwpPoint
        from app.models.incidents import IncidentDriver

        ac = shared_client
        window_id = await _resolved_window(ac, "Late Driver", [("Late Arrival", "DT", 6)])

        # Nothing to link against at filing time.
        entries = (await db.execute(select(IncidentDriver))).scalars().all()
        assert all(e.driver_id is None for e in entries)

        db.add(Driver(id=uuid.uuid4(), name="late arrival"))  # case-insensitive match
        await db.commit()

        _set_auth_user(ac._judge_user)
        await ac.post(f"/api/incidents/windows/{window_id}/publish-all")

        points = (await db.execute(select(BwpPoint))).scalars().all()
        assert len(points) == 1
        assert points[0].points == 6


class TestUnlinkedDriverBwp:
    """The silent-loss bug: a penalty must never be marked applied with no point."""

    @pytest.mark.anyio
    async def test_unlinked_driver_is_not_marked_applied(
        self, shared_client: AsyncClient, db: AsyncSession
    ):
        from app.models.bwp import BwpPoint
        from app.models.incidents import IncidentResolution

        ac = shared_client
        window_id = await _resolved_window(ac, "Unlinked", [("Nobody Knows Me", "DT", 6)])

        _set_auth_user(ac._judge_user)
        resp = await ac.post(f"/api/incidents/windows/{window_id}/publish-all")
        assert resp.status_code == 200

        assert (await db.execute(select(BwpPoint))).scalars().all() == []
        resolutions = (await db.execute(select(IncidentResolution))).scalars().all()
        assert len(resolutions) == 1
        # The penalty is still owed, not silently written off.
        assert resolutions[0].bwp_applied is False
        assert resolutions[0].bwp_points == 6

    @pytest.mark.anyio
    async def test_publish_reports_unlinked_count(self, shared_client: AsyncClient):
        ac = shared_client
        window_id = await _resolved_window(ac, "Report", [("Ghost Driver", "DT", 6)])

        _set_auth_user(ac._judge_user)
        resp = await ac.post(f"/api/incidents/windows/{window_id}/publish-all")
        assert resp.status_code == 200
        assert resp.json()["unlinkedCount"] == 1

    @pytest.mark.anyio
    async def test_link_then_republish_issues_the_point(
        self, shared_client: AsyncClient, db: AsyncSession
    ):
        from app.models.bwp import Driver, BwpPoint
        from app.models.incidents import IncidentDriver

        ac = shared_client
        window_id = await _resolved_window(ac, "Link Me", [("Mystery Name", "TP +30s", 5)])

        _set_auth_user(ac._judge_user)
        await ac.post(f"/api/incidents/windows/{window_id}/publish-all")
        assert (await db.execute(select(BwpPoint))).scalars().all() == []

        driver_id = uuid.uuid4()
        db.add(Driver(id=driver_id, name="Actual Driver"))
        await db.commit()

        entry = (await db.execute(select(IncidentDriver))).scalars().first()
        link = await ac.patch(
            f"/api/incidents/drivers/{entry.id}/link",
            json={"driverId": str(driver_id)},
        )
        assert link.status_code == 200

        resp = await ac.post(f"/api/incidents/windows/{window_id}/publish-all")
        assert resp.json()["unlinkedCount"] == 0

        points = (await db.execute(select(BwpPoint))).scalars().all()
        assert len(points) == 1
        assert points[0].points == 5
        assert points[0].driver_id == driver_id

    @pytest.mark.anyio
    async def test_link_requires_judge(self, client: AsyncClient):
        resp = await client.patch(
            f"/api/incidents/drivers/{uuid.uuid4()}/link",
            json={"driverId": str(uuid.uuid4())},
        )
        assert resp.status_code in (401, 403)


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
    async def test_create_allowed_for_judge(self, judge_client: AsyncClient):
        resp = await judge_client.post(
            RULES_URL,
            json={"verdict": "Judge Created", "defaultBwp": 0},
        )
        assert resp.status_code == 201

    @pytest.mark.anyio
    async def test_create_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            RULES_URL,
            json={"verdict": "Unauthorized", "defaultBwp": 0},
        )
        assert resp.status_code in (401, 403)


# =====================================================================
# Default verdict rule (is_default)
# =====================================================================

class TestVerdictRuleDefault:
    """Exactly one rule may be the default, and the DB itself enforces it."""

    @pytest.mark.anyio
    async def test_create_rule_with_is_default_demotes_previous(
        self, admin_client: AsyncClient
    ):
        first = await admin_client.post(
            RULES_URL, json={"verdict": "First Default", "defaultBwp": 0, "isDefault": True}
        )
        assert first.status_code == 201
        assert first.json()["isDefault"] is True

        second = await admin_client.post(
            RULES_URL, json={"verdict": "Second Default", "defaultBwp": 0, "isDefault": True}
        )
        assert second.status_code == 201
        assert second.json()["isDefault"] is True

        rules = (await admin_client.get(RULES_URL)).json()
        defaults = [r for r in rules if r["isDefault"]]
        assert len(defaults) == 1
        assert defaults[0]["verdict"] == "Second Default"

    @pytest.mark.anyio
    async def test_patch_is_default_true_moves_default(self, admin_client: AsyncClient):
        a = (await admin_client.post(
            RULES_URL, json={"verdict": "Rule A", "defaultBwp": 0, "isDefault": True}
        )).json()
        b = (await admin_client.post(
            RULES_URL, json={"verdict": "Rule B", "defaultBwp": 2}
        )).json()

        resp = await admin_client.patch(f"{RULES_URL}/{b['id']}", json={"isDefault": True})
        assert resp.status_code == 200
        assert resp.json()["isDefault"] is True

        rules = {r["id"]: r for r in (await admin_client.get(RULES_URL)).json()}
        assert rules[a["id"]]["isDefault"] is False
        assert rules[b["id"]]["isDefault"] is True

    @pytest.mark.anyio
    async def test_patch_is_default_false_rejected(self, admin_client: AsyncClient):
        """Demoting directly would leave the league with no default at all."""
        rule = (await admin_client.post(
            RULES_URL, json={"verdict": "Sole Default", "defaultBwp": 0, "isDefault": True}
        )).json()

        resp = await admin_client.patch(f"{RULES_URL}/{rule['id']}", json={"isDefault": False})
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_delete_default_rule_conflicts(self, admin_client: AsyncClient):
        rule = (await admin_client.post(
            RULES_URL, json={"verdict": "Protected", "defaultBwp": 0, "isDefault": True}
        )).json()

        resp = await admin_client.delete(f"{RULES_URL}/{rule['id']}")
        assert resp.status_code == 409

    @pytest.mark.anyio
    async def test_two_defaults_rejected_at_db_level(self, db: AsyncSession):
        """Proves the partial unique index, not just the router logic."""
        from sqlalchemy.exc import IntegrityError
        from app.models.incidents import VerdictRule

        db.add(VerdictRule(verdict="DB One", default_bwp=0, sort_order=1, is_default=True))
        await db.commit()

        db.add(VerdictRule(verdict="DB Two", default_bwp=0, sort_order=2, is_default=True))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    @pytest.mark.anyio
    async def test_reorder_rules(self, admin_client: AsyncClient):
        a = (await admin_client.post(RULES_URL, json={"verdict": "Ord A", "defaultBwp": 0})).json()
        b = (await admin_client.post(RULES_URL, json={"verdict": "Ord B", "defaultBwp": 0})).json()
        c = (await admin_client.post(RULES_URL, json={"verdict": "Ord C", "defaultBwp": 0})).json()

        resp = await admin_client.put(
            f"{RULES_URL}/order", json={"ids": [c["id"], a["id"], b["id"]]}
        )
        assert resp.status_code == 200

        rules = (await admin_client.get(RULES_URL)).json()
        verdicts = [r["verdict"] for r in rules if r["verdict"].startswith("Ord ")]
        assert verdicts == ["Ord C", "Ord A", "Ord B"]

    @pytest.mark.anyio
    async def test_reorder_requires_judge(self, client: AsyncClient):
        resp = await client.put(f"{RULES_URL}/order", json={"ids": []})
        assert resp.status_code in (401, 403)



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
        # All drivers share the same description
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
# Bulk resolve falls back to the default verdict rule
# =====================================================================

async def _window_with_drivers(ac: AsyncClient, name: str, drivers: list[str]):
    """Create a window + one filed incident; return (window_id, incident_id, drivers)."""
    _set_auth_user(ac._admin_user)
    w_resp = await ac.post(
        "/api/incidents/windows", json={"raceName": name, "intervalHours": 48}
    )
    window_id = w_resp.json()["id"]
    await ac.post(
        f"/api/incidents/windows/{window_id}/incidents", json={"drivers": drivers}
    )
    w = await ac.get(f"/api/incidents/windows/{window_id}")
    inc = w.json()["incidents"][0]
    return window_id, inc["id"], inc["drivers"]


class TestBulkResolveDefaults:
    """A steward names the exceptions; the server fills in the innocents."""

    @pytest.mark.anyio
    async def test_omitted_verdict_uses_default_rule(self, shared_client: AsyncClient):
        ac = shared_client
        _set_auth_user(ac._admin_user)
        await ac.post(RULES_URL, json={"verdict": "NFA", "defaultBwp": 0, "isDefault": True})

        _, incident_id, drivers = await _window_with_drivers(
            ac, "Five Car Pileup", ["D1", "D2", "D3", "D4", "D5"]
        )

        _set_auth_user(ac._judge_user)
        resp = await ac.patch(
            f"/api/incidents/{incident_id}/resolve",
            json={
                "drivers": [
                    {"incidentDriverId": drivers[0]["id"], "verdict": "TP +10s", "bwpPoints": 2},
                    {"incidentDriverId": drivers[1]["id"]},
                    {"incidentDriverId": drivers[2]["id"]},
                    {"incidentDriverId": drivers[3]["id"]},
                    {"incidentDriverId": drivers[4]["id"]},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"
        assert data["drivers"][0]["resolution"]["verdict"] == "TP +10s"
        assert data["drivers"][0]["resolution"]["bwpPoints"] == 2
        for d in data["drivers"][1:]:
            assert d["resolution"]["verdict"] == "NFA"
            assert d["resolution"]["bwpPoints"] == 0

    @pytest.mark.anyio
    async def test_omitted_verdict_without_default_rule_409(self, shared_client: AsyncClient):
        ac = shared_client
        _, incident_id, drivers = await _window_with_drivers(ac, "No Default", ["D1"])

        _set_auth_user(ac._judge_user)
        resp = await ac.patch(
            f"/api/incidents/{incident_id}/resolve",
            json={"drivers": [{"incidentDriverId": drivers[0]["id"]}]},
        )
        assert resp.status_code == 409

    @pytest.mark.anyio
    async def test_stored_verdict_is_text_not_reference(self, shared_client: AsyncClient):
        """Renaming a rule must not rewrite verdicts already handed down."""
        ac = shared_client
        _set_auth_user(ac._admin_user)
        rule = (await ac.post(
            RULES_URL, json={"verdict": "NFA", "defaultBwp": 0, "isDefault": True}
        )).json()

        window_id, incident_id, drivers = await _window_with_drivers(
            ac, "Rename Later", ["D1"]
        )

        _set_auth_user(ac._judge_user)
        await ac.patch(
            f"/api/incidents/{incident_id}/resolve",
            json={"drivers": [{"incidentDriverId": drivers[0]["id"]}]},
        )

        _set_auth_user(ac._admin_user)
        await ac.patch(f"{RULES_URL}/{rule['id']}", json={"verdict": "No Further Action"})

        resp = await ac.get(f"/api/incidents/windows/{window_id}")
        inc = next(i for i in resp.json()["incidents"] if i["id"] == incident_id)
        assert inc["drivers"][0]["resolution"]["verdict"] == "NFA"

    @pytest.mark.anyio
    async def test_partial_payload_does_not_wipe_description(
        self, shared_client: AsyncClient
    ):
        """Saving one driver must not blank the decision text for the incident."""
        ac = shared_client
        _set_auth_user(ac._admin_user)
        await ac.post(RULES_URL, json={"verdict": "NFA", "defaultBwp": 0, "isDefault": True})

        _, incident_id, drivers = await _window_with_drivers(ac, "Keep Desc", ["D1", "D2"])

        _set_auth_user(ac._judge_user)
        await ac.patch(
            f"/api/incidents/{incident_id}/resolve",
            json={
                "description": "Causing a collision",
                "drivers": [
                    {"incidentDriverId": drivers[0]["id"], "verdict": "DT", "bwpPoints": 6},
                    {"incidentDriverId": drivers[1]["id"]},
                ],
            },
        )

        # Second save omits description entirely — it must survive.
        resp = await ac.patch(
            f"/api/incidents/{incident_id}/resolve",
            json={
                "drivers": [
                    {"incidentDriverId": drivers[0]["id"], "verdict": "TP +30s", "bwpPoints": 5},
                ],
            },
        )
        assert resp.status_code == 200
        target = next(d for d in resp.json()["drivers"] if d["id"] == drivers[0]["id"])
        assert target["resolution"]["verdict"] == "TP +30s"
        assert target["resolution"]["description"] == "Causing a collision"


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
    async def test_create_allowed_for_judge(self, judge_client: AsyncClient):
        resp = await judge_client.post(
            DESC_URL,
            json={"text": "Judge Created"},
        )
        assert resp.status_code == 201

    @pytest.mark.anyio
    async def test_create_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            DESC_URL,
            json={"text": "Unauthorized"},
        )
        assert resp.status_code in (401, 403)


# =====================================================================
# Publish / hide incidents
# =====================================================================

WINDOWS_URL = "/api/incidents/windows"


class TestPublishWindow:
    @pytest.mark.anyio
    async def test_unpublished_verdicts_hidden_from_public(self, shared_client: AsyncClient):
        """Unpublished incidents stay visible; only their verdicts are withheld."""
        ac = shared_client
        _set_auth_user(ac._admin_user)
        await ac.post(WINDOWS_URL, json={"raceName": "Pub Test", "intervalHours": 48})

        from app.main import app
        from app.auth import require_api_token
        app.dependency_overrides[require_api_token] = lambda: None
        resp = await ac.post(
            "/api/incidents/ingest",
            json={
                "raceId": 9999,
                "championshipId": 1,
                "incidents": [
                    {"time": "00:05:00", "drivers": ["Driver A", "Driver B"]},
                ],
            },
        )
        del app.dependency_overrides[require_api_token]
        assert resp.status_code == 201
        window_id = resp.json()["id"]
        inc = resp.json()["incidents"][0]
        assert inc["isPublished"] is False
        drivers = inc["drivers"]

        _set_auth_user(ac._judge_user)
        await ac.post(RULES_URL, json={"verdict": "NFA", "defaultBwp": 0, "isDefault": True})
        await ac.patch(
            f"/api/incidents/{inc['id']}/resolve",
            json={"drivers": [{"incidentDriverId": d["id"]} for d in drivers]},
        )

        # Public sees the incident but no verdicts.
        from app.auth import get_current_user, get_current_user_optional
        app.dependency_overrides[get_current_user] = lambda: None
        app.dependency_overrides[get_current_user_optional] = lambda: None
        pub = await ac.get(f"{WINDOWS_URL}/{window_id}")
        assert pub.status_code == 200
        assert len(pub.json()["incidents"]) == 1
        assert all(d["resolution"] is None for d in pub.json()["incidents"][0]["drivers"])

        # A judge sees them.
        _set_auth_user(ac._judge_user)
        judge = await ac.get(f"{WINDOWS_URL}/{window_id}")
        assert all(d["resolution"] is not None for d in judge.json()["incidents"][0]["drivers"])

        # Publishing the window reveals them to everyone.
        assert (await ac.post(f"{WINDOWS_URL}/{window_id}/publish-all")).status_code == 200
        app.dependency_overrides[get_current_user] = lambda: None
        app.dependency_overrides[get_current_user_optional] = lambda: None
        after = await ac.get(f"{WINDOWS_URL}/{window_id}")
        assert all(d["resolution"] is not None for d in after.json()["incidents"][0]["drivers"])

        _set_auth_user(ac._admin_user)

    @pytest.mark.anyio
    async def test_filed_incidents_start_unpublished(self, shared_client: AsyncClient):
        """Everything starts hidden, so one banner can speak for the whole round."""
        ac = shared_client
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(WINDOWS_URL, json={"raceName": "Filed Pub", "intervalHours": 48})
        window_id = w_resp.json()["id"]
        inc_resp = await ac.post(
            f"{WINDOWS_URL}/{window_id}/incidents",
            json={"drivers": ["Driver X", "Driver Y"]},
        )
        assert inc_resp.status_code == 201
        assert inc_resp.json()["isPublished"] is False

    @pytest.mark.anyio
    async def test_publish_all_requires_judge(self, client: AsyncClient):
        resp = await client.post(f"{WINDOWS_URL}/{uuid.uuid4()}/publish-all")
        assert resp.status_code in (401, 403)

    @pytest.mark.anyio
    async def test_publish_empty_window_conflicts(self, shared_client: AsyncClient):
        ac = shared_client
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(WINDOWS_URL, json={"raceName": "Empty", "intervalHours": 48})
        window_id = w_resp.json()["id"]
        _set_auth_user(ac._judge_user)
        resp = await ac.post(f"{WINDOWS_URL}/{window_id}/publish-all")
        assert resp.status_code == 409
        _set_auth_user(ac._admin_user)


# =====================================================================
# Duplicate incident
# =====================================================================

class TestDuplicateIncident:
    @pytest.mark.anyio
    async def test_duplicate_creates_new_incident(self, shared_client: AsyncClient):
        ac = shared_client
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(WINDOWS_URL, json={"raceName": "Dup Test", "intervalHours": 48})
        window_id = w_resp.json()["id"]
        inc_resp = await ac.post(
            f"{WINDOWS_URL}/{window_id}/incidents",
            json={"drivers": ["Alpha", "Beta"], "time": "00:10:00"},
        )
        inc_id = inc_resp.json()["id"]

        _set_auth_user(ac._judge_user)
        dup = await ac.post(f"/api/incidents/{inc_id}/duplicate")
        assert dup.status_code == 201
        dup_data = dup.json()
        assert dup_data["id"] != inc_id
        assert dup_data["windowId"] == window_id
        driver_names = [d["driverName"] for d in dup_data["drivers"]]
        assert "Alpha" in driver_names
        assert "Beta" in driver_names

    @pytest.mark.anyio
    async def test_duplicate_requires_judge(self, shared_client: AsyncClient):
        ac = shared_client
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(WINDOWS_URL, json={"raceName": "Dup Auth", "intervalHours": 48})
        window_id = w_resp.json()["id"]
        inc_resp = await ac.post(
            f"{WINDOWS_URL}/{window_id}/incidents",
            json={"drivers": ["D1"]},
        )
        inc_id = inc_resp.json()["id"]

        # Temporarily set no auth
        from app.auth import get_current_user, get_current_user_optional
        from app.main import app
        from fastapi import HTTPException as FHE, status as fs
        app.dependency_overrides[get_current_user] = lambda: (_ for _ in ()).throw(FHE(status_code=fs.HTTP_401_UNAUTHORIZED, detail="Not authenticated."))
        app.dependency_overrides[get_current_user_optional] = lambda: None
        resp = await ac.post(f"/api/incidents/{inc_id}/duplicate")
        assert resp.status_code in (401, 403)
        # Restore
        _set_auth_user(ac._admin_user)


# =====================================================================
# Add / remove driver from incident
# =====================================================================

class TestAddRemoveDriver:
    @pytest.mark.anyio
    async def test_add_driver(self, shared_client: AsyncClient):
        ac = shared_client
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(WINDOWS_URL, json={"raceName": "AddDrv Test", "intervalHours": 48})
        window_id = w_resp.json()["id"]
        inc_resp = await ac.post(
            f"{WINDOWS_URL}/{window_id}/incidents",
            json={"drivers": ["D1", "D2"]},
        )
        inc_id = inc_resp.json()["id"]

        _set_auth_user(ac._judge_user)
        add_resp = await ac.post(
            f"/api/incidents/{inc_id}/drivers",
            json={"driverName": "D3"},
        )
        assert add_resp.status_code == 201
        driver_names = [d["driverName"] for d in add_resp.json()["drivers"]]
        assert "D3" in driver_names
        assert len(driver_names) == 3

    @pytest.mark.anyio
    async def test_remove_driver(self, shared_client: AsyncClient):
        ac = shared_client
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(WINDOWS_URL, json={"raceName": "RemDrv Test", "intervalHours": 48})
        window_id = w_resp.json()["id"]
        inc_resp = await ac.post(
            f"{WINDOWS_URL}/{window_id}/incidents",
            json={"drivers": ["D1", "D2", "D3"]},
        )
        inc_id = inc_resp.json()["id"]
        drv_id = inc_resp.json()["drivers"][2]["id"]  # D3

        _set_auth_user(ac._judge_user)
        del_resp = await ac.delete(f"/api/incidents/drivers/{drv_id}")
        assert del_resp.status_code == 204

        # Verify only 2 drivers remain
        w = await ac.get(f"{WINDOWS_URL}/{window_id}")
        inc = next(i for i in w.json()["incidents"] if i["id"] == inc_id)
        assert len(inc["drivers"]) == 2

    @pytest.mark.anyio
    async def test_add_driver_requires_judge(self, shared_client: AsyncClient):
        ac = shared_client
        _set_auth_user(ac._admin_user)
        w_resp = await ac.post(WINDOWS_URL, json={"raceName": "Auth Test", "intervalHours": 48})
        window_id = w_resp.json()["id"]
        inc_resp = await ac.post(
            f"{WINDOWS_URL}/{window_id}/incidents",
            json={"drivers": ["D1"]},
        )
        inc_id = inc_resp.json()["id"]

        from app.auth import get_current_user, get_current_user_optional
        from app.main import app
        from fastapi import HTTPException as FHE, status as fs
        app.dependency_overrides[get_current_user] = lambda: (_ for _ in ()).throw(FHE(status_code=fs.HTTP_401_UNAUTHORIZED, detail="Not authenticated."))
        app.dependency_overrides[get_current_user_optional] = lambda: None
        resp = await ac.post(f"/api/incidents/{inc_id}/drivers", json={"driverName": "D2"})
        assert resp.status_code in (401, 403)
        _set_auth_user(ac._admin_user)

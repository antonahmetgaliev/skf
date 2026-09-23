"""End-to-end tests for the race-results admin API.

One upload per round feeds the giveaway and the round's Auto incidents; the
file type follows the championship's SimGrid game.
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

from tests.conftest import IRACING_CHAMPIONSHIP_ID, LMU_CHAMPIONSHIP_ID

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LMU_FILE = "laguna_seca_incidents.xml"
IR_FILE = "iracing_gt4_r3.bin"


def _factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession, seed_roles):
    from app.models.user import User

    user = User(
        id=uuid.uuid4(),
        discord_id="admin-race-results",
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


@pytest.fixture
def bucket(monkeypatch):
    """An in-memory stand-in for the S3 bucket."""
    from app.services import file_storage

    objects: dict[str, bytes] = {}

    async def put(key, data, content_type):
        objects[key] = data
        return True

    async def get(key):
        return objects[key]

    async def delete(key):
        objects.pop(key, None)

    monkeypatch.setattr(file_storage, "is_enabled", lambda: True)
    monkeypatch.setattr(file_storage, "put", put)
    monkeypatch.setattr(file_storage, "get", get)
    monkeypatch.setattr(file_storage, "delete", delete)
    return objects


async def _upload(
    client: AsyncClient,
    fixture: str,
    race_id: int,
    championship_id: int = LMU_CHAMPIONSHIP_ID,
    **extra,
):
    return await client.post(
        "/api/race-results/imports",
        files={"file": (fixture, (FIXTURES / fixture).read_bytes(), "application/octet-stream")},
        data={
            "championshipSimgridId": str(championship_id),
            "raceSimgridId": str(race_id),
            **{k: str(v) for k, v in extra.items()},
        },
    )


async def _window(client: AsyncClient, window_id: str) -> dict:
    resp = await client.get(f"/api/incidents/windows/{window_id}")
    assert resp.status_code == 200
    return resp.json()


async def test_lmu_upload_creates_the_rounds_auto_incidents(admin_client):
    resp = await _upload(admin_client, LMU_FILE, 101)

    assert resp.status_code == 201
    body = resp.json()
    assert body["raceImport"]["sim"] == "lmu"
    assert body["raceImport"]["contactsCount"] == 55
    assert body["incidentsCreated"] == 55

    window = await _window(admin_client, body["windowId"])
    assert window["raceId"] == 101
    assert window["championshipId"] == LMU_CHAMPIONSHIP_ID
    assert window["championshipName"] == f"Championship {LMU_CHAMPIONSHIP_ID}"
    assert window["raceName"] == "Round 101"
    assert len(window["incidents"]) == 55
    assert {i["source"] for i in window["incidents"]} == {"ingested"}


async def test_iracing_upload_parses_the_bin(admin_client):
    resp = await _upload(admin_client, IR_FILE, 201, IRACING_CHAMPIONSHIP_ID)

    assert resp.status_code == 201
    body = resp.json()
    assert body["raceImport"]["sim"] == "iracing"
    assert body["raceImport"]["entryCount"] > 0
    assert body["incidentsCreated"] == 4

    window = await _window(admin_client, body["windowId"])
    assert all(i["lap"] for i in window["incidents"])
    assert all(len(i["drivers"]) >= 2 for i in window["incidents"])


async def test_the_championship_decides_the_file_type(admin_client):
    resp = await _upload(admin_client, LMU_FILE, 201, IRACING_CHAMPIONSHIP_ID)
    assert resp.status_code == 400
    assert ".bin" in resp.json()["detail"]

    resp = await _upload(admin_client, IR_FILE, 101)
    assert resp.status_code == 400
    assert ".xml" in resp.json()["detail"]


async def test_unsupported_games_are_refused(admin_client, simgrid_stub):
    simgrid_stub.games[999] = "F1 2024"
    resp = await _upload(admin_client, LMU_FILE, 1, 999)
    assert resp.status_code == 422


async def test_reupload_keeps_resolved_incidents_and_adds_no_duplicates(admin_client, db):
    from app.models.incidents import Incident, IncidentResolution

    first = await _upload(admin_client, IR_FILE, 201, IRACING_CHAMPIONSHIP_ID)
    window_id = first.json()["windowId"]
    window = await _window(admin_client, window_id)
    resolved = window["incidents"][0]
    db.add(
        IncidentResolution(
            incident_driver_id=uuid.UUID(resolved["drivers"][0]["id"]),
            verdict="Racing Incident",
        )
    )
    await db.commit()

    second = await _upload(admin_client, IR_FILE, 201, IRACING_CHAMPIONSHIP_ID)
    assert second.status_code == 201
    body = second.json()
    assert body["windowId"] == window_id
    assert body["incidentsKept"] == 1
    assert body["incidentsCreated"] == 3

    window = await _window(admin_client, window_id)
    assert len(window["incidents"]) == 4
    assert resolved["id"] in {i["id"] for i in window["incidents"]}

    # Every Auto incident now belongs to the new upload.
    rows = await db.execute(select(Incident.import_id).where(Incident.window_id == uuid.UUID(window_id)))
    assert set(rows.scalars().all()) == {uuid.UUID(body["raceImport"]["id"])}


async def test_incidents_from_the_legacy_ingest_are_not_duplicated(admin_client, monkeypatch):
    monkeypatch.setenv("INCIDENT_API_TOKEN", "legacy-token")
    ir = (await _upload(admin_client, IR_FILE, 201, IRACING_CHAMPIONSHIP_ID)).json()
    window = await _window(admin_client, ir["windowId"])
    await admin_client.delete(f"/api/race-results/imports/{ir['raceImport']['id']}")

    # Same round sent by the desktop tool into a fresh race id.
    legacy = await admin_client.post(
        "/api/incidents/ingest",
        json={
            "raceId": 202,
            "championshipId": IRACING_CHAMPIONSHIP_ID,
            "incidents": [
                {"sessionName": i["sessionName"], "time": i["time"], "drivers": [d["driverName"] for d in i["drivers"]]}
                for i in window["incidents"][:2]
            ],
        },
        headers={"Authorization": "Bearer legacy-token"},
    )
    assert legacy.status_code == 201

    resp = await _upload(admin_client, IR_FILE, 202, IRACING_CHAMPIONSHIP_ID)
    assert resp.json()["incidentsCreated"] == 2
    assert len((await _window(admin_client, legacy.json()["id"]))["incidents"]) == 4


async def test_upload_can_skip_incidents(admin_client):
    resp = await _upload(admin_client, LMU_FILE, 101, createIncidents="false")
    assert resp.status_code == 201
    assert resp.json()["windowId"] is None
    assert (await admin_client.get("/api/incidents/windows")).json() == []


async def test_rounds_show_upload_and_window(admin_client, simgrid_stub):
    simgrid_stub.races[LMU_CHAMPIONSHIP_ID] = [
        {"id": 101, "display_name": "Laguna Seca", "starts_at": "2026-09-12T18:00:00Z", "ended": True},
        {"id": 102, "display_name": "Spa", "starts_at": "2026-09-19T18:00:00Z", "ended": False},
    ]
    await _upload(admin_client, LMU_FILE, 101)

    resp = await admin_client.get(
        "/api/race-results/rounds", params={"championshipSimgridId": LMU_CHAMPIONSHIP_ID}
    )
    body = resp.json()
    assert body["sim"] == "lmu"
    assert body["gameName"] == "Le Mans Ultimate"
    assert body["storageEnabled"] is False
    laguna, spa = body["rounds"]
    assert laguna["raceImport"]["entryCount"] == 17
    assert laguna["raceImport"]["hasFile"] is False
    assert laguna["window"]["incidentsCount"] == 55
    assert spa["raceImport"] is None and spa["window"] is None


async def test_original_file_is_kept_downloadable_and_reparsable(admin_client, bucket):
    created = (await _upload(admin_client, IR_FILE, 201, IRACING_CHAMPIONSHIP_ID)).json()
    import_id = created["raceImport"]["id"]
    assert created["raceImport"]["hasFile"] is True
    assert list(bucket) == [f"race-results/{IRACING_CHAMPIONSHIP_ID}/201/{import_id}.bin"]

    download = await admin_client.get(f"/api/race-results/imports/{import_id}/file")
    assert download.status_code == 200
    assert download.content == (FIXTURES / IR_FILE).read_bytes()
    assert IR_FILE in download.headers["content-disposition"]

    reparsed = await admin_client.post(f"/api/race-results/imports/{import_id}/reparse")
    assert reparsed.status_code == 200
    new_id = reparsed.json()["raceImport"]["id"]
    # The replaced upload's object goes, the new one stays.
    assert list(bucket) == [f"race-results/{IRACING_CHAMPIONSHIP_ID}/201/{new_id}.bin"]

    await admin_client.delete(f"/api/race-results/imports/{new_id}")
    assert bucket == {}


async def test_without_storage_there_is_nothing_to_download(admin_client):
    import_id = (await _upload(admin_client, LMU_FILE, 101)).json()["raceImport"]["id"]
    assert (await admin_client.get(f"/api/race-results/imports/{import_id}/file")).status_code == 404
    assert (await admin_client.post(f"/api/race-results/imports/{import_id}/reparse")).status_code == 409


async def test_deleting_an_import_keeps_its_incidents(admin_client):
    created = (await _upload(admin_client, LMU_FILE, 101)).json()
    resp = await admin_client.delete(f"/api/race-results/imports/{created['raceImport']['id']}")
    assert resp.status_code == 204
    assert len((await _window(admin_client, created["windowId"]))["incidents"]) == 55


async def test_championship_links_to_its_incident_windows(admin_client):
    lmu = (await _upload(admin_client, LMU_FILE, 101)).json()
    await _upload(admin_client, IR_FILE, 201, IRACING_CHAMPIONSHIP_ID)

    resp = await admin_client.get(f"/api/championships/{LMU_CHAMPIONSHIP_ID}/incident-windows")
    assert resp.json() == [
        {"raceId": 101, "windowId": lmu["windowId"], "isOpen": True, "incidentsCount": 55}
    ]

    windows = await admin_client.get(
        "/api/incidents/windows", params={"championshipId": LMU_CHAMPIONSHIP_ID}
    )
    assert [w["id"] for w in windows.json()] == [lmu["windowId"]]


async def test_a_round_gets_only_one_window(admin_client):
    await _upload(admin_client, LMU_FILE, 101)
    resp = await admin_client.post(
        "/api/incidents/windows",
        json={"raceId": 101, "raceName": "Duplicate", "intervalHours": 24},
    )
    assert resp.status_code == 409


async def test_endpoints_are_closed_to_non_admins(client):
    resp = await client.get(
        "/api/race-results/rounds", params={"championshipSimgridId": LMU_CHAMPIONSHIP_ID}
    )
    assert resp.status_code in (401, 403)
    resp = await client.post("/api/race-results/imports")
    assert resp.status_code in (401, 403, 422)


async def test_window_list_fills_in_missing_championship_names(admin_client, db):
    """Windows from the legacy ingest API had only the championship id."""
    from datetime import timedelta

    from app.models.incidents import IncidentWindow

    now = datetime.now(timezone.utc)
    db.add(
        IncidentWindow(
            championship_id=LMU_CHAMPIONSHIP_ID,
            race_id=301,
            race_name="Round 1",
            opened_at=now,
            closes_at=now + timedelta(hours=24),
        )
    )
    await db.commit()

    windows = (await admin_client.get("/api/incidents/windows")).json()
    assert [w["championshipName"] for w in windows] == [f"Championship {LMU_CHAMPIONSHIP_ID}"]

    stored = await db.execute(select(IncidentWindow.championship_name))
    assert stored.scalars().all() == [f"Championship {LMU_CHAMPIONSHIP_ID}"]

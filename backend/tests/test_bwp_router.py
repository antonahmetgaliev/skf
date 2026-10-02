from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("YOUTUBE_API_KEY", "fake")
os.environ.setdefault("YOUTUBE_CHANNEL_ID", "fake")

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from tests.conftest import _factory


def _now() -> datetime:
    return datetime.now(UTC)


@pytest_asyncio.fixture
async def seed_roles(db: AsyncSession):
    from app.models.user import Role

    db.add_all(
        [
            Role(id=1, name="driver"),
            Role(id=2, name="admin"),
            Role(id=3, name="super_admin"),
            Role(id=4, name="racing_judge"),
        ]
    )
    await db.commit()


async def _create_user(db: AsyncSession, role_id: int, name: str):
    from app.models.user import User

    user = User(
        id=uuid.uuid4(),
        discord_id=f"{name}-discord",
        username=name,
        display_name=name,
        role_id=role_id,
        created_at=_now(),
    )
    db.add(user)
    await db.commit()

    result = await db.execute(select(User).options(joinedload(User.role)).where(User.id == user.id))
    return result.scalar_one()


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession, seed_roles):
    return await _create_user(db, 2, "admin-user")


@pytest_asyncio.fixture
async def judge_user(db: AsyncSession, seed_roles):
    return await _create_user(db, 4, "judge-user")


@pytest_asyncio.fixture
async def driver_user(db: AsyncSession, seed_roles):
    return await _create_user(db, 1, "driver-user")


def _set_auth_user(user):
    from app.auth import get_current_user, get_current_user_optional
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_user_optional] = lambda: user


@pytest_asyncio.fixture
async def shared_client(engine, admin_user, judge_user, driver_user):
    import app.database as db_module
    from app.database import get_db
    from app.main import app

    factory = _factory(engine)
    original = db_module.async_session
    db_module.async_session = factory

    async def _override_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    _set_auth_user(admin_user)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac._admin_user = admin_user
        ac._judge_user = judge_user
        ac._driver_user = driver_user
        yield ac

    app.dependency_overrides.clear()
    db_module.async_session = original


async def _create_driver(db: AsyncSession, name: str, **fields):
    from app.models.bwp import Driver

    driver = Driver(name=name, created_at=_now(), **fields)
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return driver


class TestBwpDriverRename:
    async def test_admin_can_rename_driver(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Alex Ivanov8")

        _set_auth_user(shared_client._admin_user)
        resp = await shared_client.patch(
            f"/api/v1/drivers/{driver.id}",
            json={"name": "Alex Ivanov"},
        )

        assert resp.status_code == 200
        assert resp.json()["name"] == "Alex Ivanov"

    async def test_judge_can_rename_driver(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Driver Old")

        _set_auth_user(shared_client._judge_user)
        resp = await shared_client.patch(
            f"/api/v1/drivers/{driver.id}",
            json={"name": "Driver New"},
        )

        assert resp.status_code == 200
        assert resp.json()["name"] == "Driver New"

    async def test_driver_cannot_rename_driver(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Readonly Name")

        _set_auth_user(shared_client._driver_user)
        resp = await shared_client.patch(
            f"/api/v1/drivers/{driver.id}",
            json={"name": "Should Fail"},
        )

        assert resp.status_code == 403

    async def test_rename_conflict_returns_409(self, shared_client: AsyncClient, db: AsyncSession):
        first = await _create_driver(db, "Alpha")
        await _create_driver(db, "Bravo")

        _set_auth_user(shared_client._judge_user)
        resp = await shared_client.patch(
            f"/api/v1/drivers/{first.id}",
            json={"name": "Bravo"},
        )

        assert resp.status_code == 409
        assert resp.json()["detail"] == "Driver name already exists."

    async def test_rename_unknown_driver_returns_404(self, shared_client: AsyncClient):
        _set_auth_user(shared_client._admin_user)
        resp = await shared_client.patch(
            f"/api/v1/drivers/{uuid.uuid4()}",
            json={"name": "Nobody"},
        )

        assert resp.status_code == 404

    async def test_patch_changes_only_what_is_sent(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Linked Driver", simgrid_driver_id=42)
        _set_auth_user(shared_client._admin_user)

        linked = await shared_client.patch(f"/api/v1/drivers/{driver.id}", json={"simgridDriverId": 43})
        assert (linked.json()["name"], linked.json()["simgridDriverId"]) == ("Linked Driver", 43)

        renamed = await shared_client.patch(f"/api/v1/drivers/{driver.id}", json={"name": "Renamed"})
        assert (renamed.json()["name"], renamed.json()["simgridDriverId"]) == ("Renamed", 43)

    async def test_null_simgrid_id_unlinks_but_null_name_is_rejected(
        self, shared_client: AsyncClient, db: AsyncSession
    ):
        driver = await _create_driver(db, "Unlink Me", simgrid_driver_id=42)
        _set_auth_user(shared_client._admin_user)

        unlinked = await shared_client.patch(f"/api/v1/drivers/{driver.id}", json={"simgridDriverId": None})
        assert unlinked.status_code == 200
        assert unlinked.json()["simgridDriverId"] is None

        resp = await shared_client.patch(f"/api/v1/drivers/{driver.id}", json={"name": None})
        assert resp.status_code == 422


class TestDriverList:
    async def test_public_list_hides_account(self, shared_client: AsyncClient, db: AsyncSession):
        await _create_driver(db, "Linked Racer", user_id=uuid.uuid4())

        _set_auth_user(shared_client._driver_user)
        resp = await shared_client.get("/api/v1/drivers")

        assert resp.status_code == 200
        body = resp.json()
        assert [d["name"] for d in body] == ["Linked Racer"]
        assert "userId" not in body[0]

    async def test_include_account_for_judge(self, shared_client: AsyncClient, db: AsyncSession):
        linked = uuid.uuid4()
        await _create_driver(db, "Linked Racer", user_id=linked)

        _set_auth_user(shared_client._judge_user)
        resp = await shared_client.get("/api/v1/drivers", params={"include": "account"})

        assert resp.status_code == 200
        assert resp.json()[0]["userId"] == str(linked)

    async def test_include_account_forbidden_for_driver(self, shared_client: AsyncClient):
        _set_auth_user(shared_client._driver_user)
        resp = await shared_client.get("/api/v1/drivers", params={"include": "account"})
        assert resp.status_code == 403

    async def test_include_account_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/v1/drivers", params={"include": "account"})
        assert resp.status_code == 401

    async def test_unknown_include_rejected(self, client: AsyncClient):
        resp = await client.get("/api/v1/drivers", params={"include": "secrets"})
        assert resp.status_code == 422

    async def test_filter_by_simgrid_id(self, shared_client: AsyncClient, db: AsyncSession):
        await _create_driver(db, "With SimGrid", simgrid_driver_id=42)
        await _create_driver(db, "Other", simgrid_driver_id=43)
        await _create_driver(db, "Without SimGrid")

        resp = await shared_client.get("/api/v1/drivers", params={"simgridId": 42})

        assert resp.status_code == 200
        assert [d["name"] for d in resp.json()] == ["With SimGrid"]
        assert resp.headers["X-Total-Count"] == "1"

    async def test_pagination_headers(self, shared_client: AsyncClient, db: AsyncSession):
        for name in ("A", "B", "C"):
            await _create_driver(db, name)

        resp = await shared_client.get("/api/v1/drivers", params={"limit": 2})

        assert resp.status_code == 200
        assert [d["name"] for d in resp.json()] == ["A", "B"]
        assert resp.headers["X-Total-Count"] == "3"
        assert 'rel="next"' in resp.headers["Link"]

    async def test_get_driver_by_uuid(self, client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Public Star", simgrid_driver_id=777, country_code="ES")

        resp = await client.get(f"/api/v1/drivers/{driver.id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["simgridDriverId"] == 777
        assert body["countryCode"] == "ES"
        assert "userId" not in body

    async def test_get_driver_simgrid_path_is_gone(self, client: AsyncClient, db: AsyncSession):
        await _create_driver(db, "Numeric", simgrid_driver_id=555)
        assert (await client.get("/api/v1/drivers/555")).status_code == 422

    async def test_get_driver_404(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/drivers/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Driver not found."


class TestDriverCrud:
    async def test_admin_creates_driver(self, shared_client: AsyncClient):
        _set_auth_user(shared_client._admin_user)
        resp = await shared_client.post("/api/v1/drivers", json={"name": "  Fresh  "})

        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Fresh"
        assert resp.headers["Location"] == f"/api/v1/drivers/{body['id']}"

    async def test_duplicate_name_conflicts(self, shared_client: AsyncClient, db: AsyncSession):
        await _create_driver(db, "Taken")
        _set_auth_user(shared_client._admin_user)
        resp = await shared_client.post("/api/v1/drivers", json={"name": "taken"})
        assert resp.status_code == 409

    async def test_judge_cannot_create_or_delete(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Keep")
        _set_auth_user(shared_client._judge_user)
        assert (await shared_client.post("/api/v1/drivers", json={"name": "X"})).status_code == 403
        assert (await shared_client.delete(f"/api/v1/drivers/{driver.id}")).status_code == 403

    async def test_admin_deletes_driver(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Gone")
        _set_auth_user(shared_client._admin_user)
        assert (await shared_client.delete(f"/api/v1/drivers/{driver.id}")).status_code == 204
        assert (await shared_client.get(f"/api/v1/drivers/{driver.id}")).status_code == 404


class TestBwpPoints:
    async def _add(self, ac: AsyncClient, driver_id, points=3, expires_in=90):
        today = date.today()
        return await ac.post(
            f"/api/v1/drivers/{driver_id}/bwp-points",
            json={
                "points": points,
                "issuedOn": today.isoformat(),
                "expiresOn": (today + timedelta(days=expires_in)).isoformat(),
            },
        )

    async def test_add_expire_delete_point(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Pointy")
        _set_auth_user(shared_client._admin_user)

        resp = await self._add(shared_client, driver.id)
        assert resp.status_code == 201
        point = resp.json()
        assert resp.headers["Location"] == f"/api/v1/bwp-points/{point['id']}"
        assert point["expired"] is False

        resp = await shared_client.patch(
            f"/api/v1/bwp-points/{point['id']}", json={"expired": True, "note": " served "}
        )
        assert resp.status_code == 200
        assert resp.json()["expired"] is True
        assert resp.json()["note"] == "served"
        assert resp.json()["expiresOn"] == datetime.now(UTC).date().isoformat()

        resp = await shared_client.delete(f"/api/v1/bwp-points/{point['id']}")
        assert resp.status_code == 204
        resp = await shared_client.delete(f"/api/v1/bwp-points/{point['id']}")
        assert resp.status_code == 404

    async def test_unexpire_rejected(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Pointy")
        _set_auth_user(shared_client._admin_user)
        point = (await self._add(shared_client, driver.id)).json()

        resp = await shared_client.patch(f"/api/v1/bwp-points/{point['id']}", json={"expired": False})
        assert resp.status_code == 422

    async def test_bwp_reset_expires_points_and_clears(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Reset Me")
        _set_auth_user(shared_client._admin_user)
        await self._add(shared_client, driver.id, points=4)
        await self._add(shared_client, driver.id, points=5)
        rule = (
            await shared_client.post("/api/v1/penalty-rules", json={"threshold": 5, "label": "Ban"})
        ).json()
        assert (
            await shared_client.put(f"/api/v1/drivers/{driver.id}/clearances/{rule['id']}")
        ).status_code == 201

        resp = await shared_client.post(f"/api/v1/drivers/{driver.id}/bwp-resets", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["activeBwp"] == 0
        assert body["clearances"] == []
        assert all(p["expired"] for p in body["points"])
        assert {p["note"] for p in body["points"]} == {"All penalties cleared — points reset"}

    async def test_bwp_reset_requires_admin(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Reset Me")
        _set_auth_user(shared_client._judge_user)
        resp = await shared_client.post(f"/api/v1/drivers/{driver.id}/bwp-resets", json={})
        assert resp.status_code == 403


class TestPenaltyRulesAndClearances:
    async def test_rule_crud(self, shared_client: AsyncClient):
        _set_auth_user(shared_client._admin_user)
        first = await shared_client.post("/api/v1/penalty-rules", json={"threshold": 5, "label": "A"})
        second = await shared_client.post("/api/v1/penalty-rules", json={"threshold": 10, "label": "B"})
        assert first.status_code == 201
        assert first.headers["Location"] == f"/api/v1/penalty-rules/{first.json()['id']}"
        assert second.json()["sortOrder"] > first.json()["sortOrder"]

        rule_id = first.json()["id"]
        resp = await shared_client.patch(f"/api/v1/penalty-rules/{rule_id}", json={"label": "A2"})
        assert resp.status_code == 200
        assert resp.json()["label"] == "A2"

        rules = (await shared_client.get("/api/v1/penalty-rules")).json()
        assert [r["label"] for r in rules] == ["A2", "B"]

        assert (await shared_client.delete(f"/api/v1/penalty-rules/{rule_id}")).status_code == 204
        assert (await shared_client.delete(f"/api/v1/penalty-rules/{rule_id}")).status_code == 404

    async def test_rules_are_public(self, client: AsyncClient):
        assert (await client.get("/api/v1/penalty-rules")).status_code == 200

    async def test_clearance_put_is_idempotent(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Clear Me")
        _set_auth_user(shared_client._admin_user)
        rule = (
            await shared_client.post("/api/v1/penalty-rules", json={"threshold": 5, "label": "Ban"})
        ).json()
        url = f"/api/v1/drivers/{driver.id}/clearances/{rule['id']}"

        created = await shared_client.put(url)
        again = await shared_client.put(url)

        assert created.status_code == 201
        assert again.status_code == 200
        assert again.json()["id"] == created.json()["id"]

        assert (await shared_client.delete(url)).status_code == 204
        assert (await shared_client.delete(url)).status_code == 404

    async def test_clearance_unknown_rule_404(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Clear Me")
        _set_auth_user(shared_client._admin_user)
        resp = await shared_client.put(f"/api/v1/drivers/{driver.id}/clearances/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Penalty rule not found."


async def test_old_bwp_and_profile_paths_are_gone(client: AsyncClient):
    assert (await client.get("/api/bwp/drivers")).status_code == 404
    assert (await client.get("/api/profile/drivers")).status_code == 404
    assert (await client.get("/api/profile/drivers-index")).status_code == 404

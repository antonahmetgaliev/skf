from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("YOUTUBE_API_KEY", "fake")
os.environ.setdefault("YOUTUBE_CHANNEL_ID", "fake")

import uuid
from datetime import datetime, timezone

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from tests.conftest import _factory


def _now() -> datetime:
    return datetime.now(timezone.utc)


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

    result = await db.execute(
        select(User).options(joinedload(User.role)).where(User.id == user.id)
    )
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


async def _create_driver(db: AsyncSession, name: str):
    from app.models.bwp import Driver

    driver = Driver(name=name, created_at=_now())
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return driver


class TestBwpDriverRename:
    async def test_admin_can_rename_driver(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Alex Ivanov8")

        _set_auth_user(shared_client._admin_user)
        resp = await shared_client.patch(
            f"/api/bwp/drivers/{driver.id}",
            json={"name": "Alex Ivanov"},
        )

        assert resp.status_code == 200
        assert resp.json()["name"] == "Alex Ivanov"

    async def test_judge_can_rename_driver(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Driver Old")

        _set_auth_user(shared_client._judge_user)
        resp = await shared_client.patch(
            f"/api/bwp/drivers/{driver.id}",
            json={"name": "Driver New"},
        )

        assert resp.status_code == 200
        assert resp.json()["name"] == "Driver New"

    async def test_driver_cannot_rename_driver(self, shared_client: AsyncClient, db: AsyncSession):
        driver = await _create_driver(db, "Readonly Name")

        _set_auth_user(shared_client._driver_user)
        resp = await shared_client.patch(
            f"/api/bwp/drivers/{driver.id}",
            json={"name": "Should Fail"},
        )

        assert resp.status_code == 403

    async def test_rename_conflict_returns_409(self, shared_client: AsyncClient, db: AsyncSession):
        first = await _create_driver(db, "Alpha")
        await _create_driver(db, "Bravo")

        _set_auth_user(shared_client._judge_user)
        resp = await shared_client.patch(
            f"/api/bwp/drivers/{first.id}",
            json={"name": "Bravo"},
        )

        assert resp.status_code == 409
        assert resp.json()["detail"] == "Driver name already exists."

    async def test_rename_unknown_driver_returns_404(self, shared_client: AsyncClient):
        _set_auth_user(shared_client._admin_user)
        resp = await shared_client.patch(
            f"/api/bwp/drivers/{uuid.uuid4()}",
            json={"name": "Nobody"},
        )

        assert resp.status_code == 404

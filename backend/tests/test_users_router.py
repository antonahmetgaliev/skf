"""Tests for /api/v1/users (admin user management)."""

from __future__ import annotations

import uuid
from datetime import UTC

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

USERS_URL = "/api/v1/users"


@pytest_asyncio.fixture
async def admin_client(engine, db: AsyncSession, seed_roles):
    """AsyncClient authenticated as an admin."""
    import app.database as db_module
    from app.auth import get_current_user, get_current_user_optional
    from app.database import get_db
    from app.main import app
    from app.models.user import User
    from tests.conftest import _factory

    admin = User(id=uuid.uuid4(), discord_id="admin", username="aaa-admin", display_name="Admin", role_id=2)
    db.add(admin)
    await db.commit()
    admin = (
        await db.execute(select(User).options(joinedload(User.role)).where(User.id == admin.id))
    ).scalar_one()

    factory = _factory(engine)
    original = db_module.async_session
    db_module.async_session = factory

    async def _override_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_current_user_optional] = lambda: admin
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.admin = admin  # type: ignore[attr-defined]
        yield ac
    for dep in (get_db, get_current_user, get_current_user_optional):
        app.dependency_overrides.pop(dep, None)
    db_module.async_session = original


async def _add_users(db: AsyncSession, n: int) -> list:
    from app.models.user import User

    users = [
        User(id=uuid.uuid4(), discord_id=f"d{i}", username=f"user{i:02d}", display_name=f"U{i}", role_id=1)
        for i in range(n)
    ]
    db.add_all(users)
    await db.commit()
    return users


async def _add_community(db: AsyncSession, name: str = "SKF"):
    from app.models.community import Community

    community = Community(name=name)
    db.add(community)
    await db.commit()
    return community


async def test_list_users_is_paginated(admin_client: AsyncClient, db: AsyncSession):
    await _add_users(db, 5)  # + the admin = 6 users

    resp = await admin_client.get(USERS_URL, params={"limit": 2, "offset": 2})
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "6"
    assert 'rel="next"' in resp.headers["Link"] and 'rel="prev"' in resp.headers["Link"]
    assert [u["username"] for u in resp.json()] == ["user01", "user02"]


async def test_list_users_includes_driver_and_communities(admin_client: AsyncClient, db: AsyncSession):
    from app.models.bwp import Driver
    from app.models.community_manager import CommunityManager

    (user,) = await _add_users(db, 1)
    community = await _add_community(db)
    db.add_all(
        [
            Driver(name="Linked", user_id=user.id),
            CommunityManager(user_id=user.id, community_id=community.id),
        ]
    )
    await db.commit()

    resp = await admin_client.get(USERS_URL, params={"limit": 1000})
    row = next(u for u in resp.json() if u["id"] == str(user.id))
    assert row["driverId"] is not None
    assert row["managedCommunityIds"] == [str(community.id)]


async def test_users_requires_admin(auth_client: AsyncClient):
    resp = await auth_client.get(USERS_URL)
    assert resp.status_code == 403


async def test_update_user_role_and_block(admin_client: AsyncClient, db: AsyncSession):
    (user,) = await _add_users(db, 1)
    resp = await admin_client.patch(f"{USERS_URL}/{user.id}", json={"role": "admin", "blocked": True})
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"
    assert resp.json()["blocked"] is True


async def test_update_user_unknown_role_is_422(admin_client: AsyncClient, db: AsyncSession):
    (user,) = await _add_users(db, 1)
    resp = await admin_client.patch(f"{USERS_URL}/{user.id}", json={"role": "wizard"})
    assert resp.status_code == 422


async def test_update_unknown_user_is_404(admin_client: AsyncClient):
    resp = await admin_client.patch(f"{USERS_URL}/{uuid.uuid4()}", json={"blocked": True})
    assert resp.status_code == 404


async def test_revoke_sessions(admin_client: AsyncClient, db: AsyncSession):
    from datetime import datetime, timedelta

    from app.models.user import Session

    (user,) = await _add_users(db, 1)
    db.add(Session(user_id=user.id, expires_at=datetime.now(UTC) + timedelta(days=1)))
    await db.commit()

    resp = await admin_client.delete(f"{USERS_URL}/{user.id}/sessions")
    assert resp.status_code == 204
    remaining = (await db.execute(select(Session).where(Session.user_id == user.id))).all()
    assert remaining == []


async def test_managed_communities_roundtrip(admin_client: AsyncClient, db: AsyncSession):
    (user,) = await _add_users(db, 1)
    community = await _add_community(db)
    url = f"{USERS_URL}/{user.id}/managed-communities"

    resp = await admin_client.put(url, json={"communityIds": [str(community.id), str(community.id)]})
    assert resp.status_code == 200
    assert resp.json() == [str(community.id)]

    resp = await admin_client.get(url)
    assert resp.json() == [str(community.id)]

    resp = await admin_client.put(url, json={"communityIds": []})
    assert resp.json() == []


async def test_managed_communities_unknown_id_is_rejected(admin_client: AsyncClient, db: AsyncSession):
    (user,) = await _add_users(db, 1)
    community = await _add_community(db)
    resp = await admin_client.put(
        f"{USERS_URL}/{user.id}/managed-communities",
        json={"communityIds": [str(community.id), str(uuid.uuid4())]},
    )
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")

    resp = await admin_client.get(f"{USERS_URL}/{user.id}/managed-communities")
    assert resp.json() == []


async def test_managed_communities_invalid_uuid_is_422(admin_client: AsyncClient, db: AsyncSession):
    (user,) = await _add_users(db, 1)
    resp = await admin_client.put(
        f"{USERS_URL}/{user.id}/managed-communities", json={"communityIds": ["not-a-uuid"]}
    )
    assert resp.status_code == 422


async def test_managed_communities_unknown_user_is_404(admin_client: AsyncClient):
    resp = await admin_client.put(
        f"{USERS_URL}/{uuid.uuid4()}/managed-communities", json={"communityIds": []}
    )
    assert resp.status_code == 404

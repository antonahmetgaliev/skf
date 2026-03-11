"""Tests for /api/profile/* endpoints.

Covers all five endpoints:
  GET  /api/profile/link-candidates
  POST /api/profile/link-driver
  DELETE /api/profile/unlink-driver
  GET  /api/profile/me/driver
  GET  /api/profile/drivers/{driver_id}
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# GET /api/profile/link-candidates
# ---------------------------------------------------------------------------

async def test_candidates_returns_name_match(auth_client: AsyncClient, db: AsyncSession):
    """Driver whose name matches user.display_name ('Test Driver') is returned."""
    from app.models.bwp import Driver

    match = Driver(name="Test Driver", user_id=None, created_at=_now())
    no_match = Driver(name="Unrelated Person", user_id=None, created_at=_now())
    db.add_all([match, no_match])
    await db.commit()

    resp = await auth_client.get("/api/profile/link-candidates")
    assert resp.status_code == 200
    names = [d["name"] for d in resp.json()]
    assert "Test Driver" in names
    assert "Unrelated Person" not in names


async def test_candidates_excludes_already_linked_drivers(
    auth_client: AsyncClient, db: AsyncSession
):
    """Drivers with a non-NULL user_id are NOT offered as candidates."""
    from app.models.bwp import Driver

    already_linked = Driver(name="Test Driver", user_id=uuid.uuid4(), created_at=_now())
    db.add(already_linked)
    await db.commit()

    resp = await auth_client.get("/api/profile/link-candidates")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_candidates_matches_via_simgrid_display_name(
    auth_client: AsyncClient, db: AsyncSession
):
    """Drivers matched through simgrid_display_name also appear in the list."""
    from app.models.bwp import Driver

    d = Driver(
        name="T. Driver",
        simgrid_display_name="Test Driver",
        user_id=None,
        created_at=_now(),
    )
    db.add(d)
    await db.commit()

    resp = await auth_client.get("/api/profile/link-candidates")
    assert resp.status_code == 200
    names = [x["name"] for x in resp.json()]
    assert "T. Driver" in names


async def test_candidates_requires_auth(client: AsyncClient):
    """Unauthenticated requests receive 401."""
    resp = await client.get("/api/profile/link-candidates")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/profile/link-driver
# ---------------------------------------------------------------------------

async def test_link_driver_success(auth_client: AsyncClient, db: AsyncSession, test_user):
    """Linking a free driver sets driver.user_id to the authenticated user."""
    from app.models.bwp import Driver

    driver = Driver(name="Link Me", user_id=None, created_at=_now())
    db.add(driver)
    await db.commit()

    resp = await auth_client.post(
        "/api/profile/link-driver",
        json={"driver_id": str(driver.id)},
    )
    assert resp.status_code == 204

    await db.refresh(driver)
    assert driver.user_id == test_user.id


async def test_link_driver_404_unknown_driver(auth_client: AsyncClient):
    """Linking a non-existent driver UUID returns 404."""
    resp = await auth_client.post(
        "/api/profile/link-driver",
        json={"driver_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404


async def test_link_driver_409_driver_already_taken(
    auth_client: AsyncClient, db: AsyncSession
):
    """Linking a driver that already belongs to another user returns 409."""
    from app.models.bwp import Driver

    other_user = uuid.uuid4()
    driver = Driver(name="Taken Driver", user_id=other_user, created_at=_now())
    db.add(driver)
    await db.commit()

    resp = await auth_client.post(
        "/api/profile/link-driver",
        json={"driver_id": str(driver.id)},
    )
    assert resp.status_code == 409


async def test_link_driver_409_when_user_already_linked(
    auth_client: AsyncClient, db: AsyncSession, test_user
):
    """A user who already has a linked driver cannot link a second one."""
    from app.models.bwp import Driver

    first = Driver(name="First Driver", user_id=test_user.id, created_at=_now())
    second = Driver(name="Second Driver", user_id=None, created_at=_now())
    db.add_all([first, second])
    await db.commit()

    resp = await auth_client.post(
        "/api/profile/link-driver",
        json={"driver_id": str(second.id)},
    )
    assert resp.status_code == 409


async def test_link_driver_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/profile/link-driver",
        json={"driver_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/profile/unlink-driver
# ---------------------------------------------------------------------------

async def test_unlink_driver_clears_user_id(
    auth_client: AsyncClient, db: AsyncSession, test_user
):
    """Unlinking sets driver.user_id back to None."""
    from app.models.bwp import Driver

    driver = Driver(name="Will Unlink", user_id=test_user.id, created_at=_now())
    db.add(driver)
    await db.commit()

    resp = await auth_client.delete("/api/profile/unlink-driver")
    assert resp.status_code == 204

    await db.refresh(driver)
    assert driver.user_id is None


async def test_unlink_driver_no_link_is_noop(auth_client: AsyncClient):
    """Unlinking when no driver is linked is a no-op (returns 204, not 404)."""
    resp = await auth_client.delete("/api/profile/unlink-driver")
    assert resp.status_code == 204


async def test_unlink_driver_requires_auth(client: AsyncClient):
    resp = await client.delete("/api/profile/unlink-driver")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/profile/me/driver
# ---------------------------------------------------------------------------

async def test_get_my_driver_returns_linked_driver(
    auth_client: AsyncClient, db: AsyncSession, test_user
):
    from app.models.bwp import Driver

    driver = Driver(name="My Driver", user_id=test_user.id, created_at=_now())
    db.add(driver)
    await db.commit()

    resp = await auth_client.get("/api/profile/me/driver")
    assert resp.status_code == 200
    assert resp.json()["name"] == "My Driver"


async def test_get_my_driver_404_when_not_linked(auth_client: AsyncClient):
    resp = await auth_client.get("/api/profile/me/driver")
    assert resp.status_code == 404


async def test_get_my_driver_requires_auth(client: AsyncClient):
    resp = await client.get("/api/profile/me/driver")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/profile/drivers/{driver_id}  — public endpoint
# ---------------------------------------------------------------------------

async def test_get_public_driver_returns_data(client: AsyncClient, db: AsyncSession):
    from app.models.bwp import Driver

    driver = Driver(
        name="Public Star",
        simgrid_driver_id=777,
        country_code="ES",
        created_at=_now(),
    )
    db.add(driver)
    await db.commit()

    resp = await client.get(f"/api/profile/drivers/{driver.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Public Star"
    assert body["simgridDriverId"] == 777
    assert body["countryCode"] == "ES"


async def test_get_public_driver_404_unknown(client: AsyncClient):
    resp = await client.get(f"/api/profile/drivers/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_get_public_driver_no_auth_required(client: AsyncClient, db: AsyncSession):
    """Public driver endpoint is accessible without authentication."""
    from app.models.bwp import Driver

    driver = Driver(name="Open Profile", created_at=_now())
    db.add(driver)
    await db.commit()

    resp = await client.get(f"/api/profile/drivers/{driver.id}")
    assert resp.status_code == 200

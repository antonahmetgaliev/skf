"""Tests for /api/profile/* endpoints.

Covers:
  GET  /api/profile/me/driver
  GET  /api/profile/drivers          (public directory)
  GET  /api/profile/drivers-index    (SimGrid-id → UUID map)
  GET  /api/profile/drivers/{driver_id}

Account↔driver linking is fully automatic (discord_uid) and covered in
test_drivers_service.py — there are no manual link endpoints anymore.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _now():
    return datetime.now(timezone.utc)


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
# Removed manual link endpoints stay removed
# ---------------------------------------------------------------------------

async def test_manual_link_endpoints_are_gone(auth_client: AsyncClient):
    assert (await auth_client.get("/api/profile/link-candidates")).status_code == 404
    assert (
        await auth_client.post(
            "/api/profile/link-driver", json={"driverId": str(uuid.uuid4())}
        )
    ).status_code == 404
    assert (await auth_client.delete("/api/profile/unlink-driver")).status_code == 404


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


async def test_get_public_driver_by_simgrid_id(client: AsyncClient, db: AsyncSession):
    from app.models.bwp import Driver

    driver = Driver(name="By Numeric Id", simgrid_driver_id=555, created_at=_now())
    db.add(driver)
    await db.commit()

    resp = await client.get("/api/profile/drivers/555")
    assert resp.status_code == 200
    assert resp.json()["name"] == "By Numeric Id"


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


# ---------------------------------------------------------------------------
# GET /api/profile/drivers + /drivers-index  — public lists
# ---------------------------------------------------------------------------

async def test_public_driver_list_hides_user_link(client: AsyncClient, db: AsyncSession):
    """The public directory never exposes which user claimed a driver."""
    from app.models.bwp import Driver

    db.add(Driver(name="Linked Racer", user_id=uuid.uuid4(), created_at=_now()))
    await db.commit()

    resp = await client.get("/api/profile/drivers")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert "userId" not in body[0]


async def test_drivers_index_only_simgrid_linked(client: AsyncClient, db: AsyncSession):
    from app.models.bwp import Driver

    db.add_all([
        Driver(name="With SimGrid", simgrid_driver_id=42, created_at=_now()),
        Driver(name="Without SimGrid", created_at=_now()),
    ])
    await db.commit()

    resp = await client.get("/api/profile/drivers-index")
    assert resp.status_code == 200
    body = resp.json()
    assert [d["name"] for d in body] == ["With SimGrid"]
    assert body[0]["simgridDriverId"] == 42


async def test_bwp_driver_list_requires_auth(client: AsyncClient):
    """The full BWP driver list (with user linkage) is not public."""
    resp = await client.get("/api/bwp/drivers")
    assert resp.status_code == 401

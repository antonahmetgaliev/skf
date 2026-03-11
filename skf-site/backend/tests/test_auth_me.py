"""Tests for GET /api/auth/me — verifies driver_id field is populated correctly."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _now():
    return datetime.now(timezone.utc)


async def test_me_returns_null_driver_id_when_not_linked(auth_client: AsyncClient):
    """When the user has no linked driver, driverId is null in the response."""
    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["driverId"] is None


async def test_me_returns_driver_id_when_linked(
    auth_client: AsyncClient, db: AsyncSession, test_user
):
    """When the user has a linked driver, driverId matches driver.id."""
    from app.models.bwp import Driver

    driver = Driver(
        name="Linked Driver",
        user_id=test_user.id,
        created_at=_now(),
    )
    db.add(driver)
    await db.commit()

    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["driverId"] == str(driver.id)


async def test_me_returns_correct_user_fields(auth_client: AsyncClient, test_user):
    """Standard user fields are correctly serialised in the /me response."""
    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == test_user.username
    assert data["displayName"] == test_user.display_name
    assert data["role"] == "driver"
    assert data["blocked"] is False


async def test_me_requires_authentication(client: AsyncClient):
    """Unauthenticated /me request returns 401."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401

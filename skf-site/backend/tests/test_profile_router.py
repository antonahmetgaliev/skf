"""Tests for the signed-in user's own driver.

Covers:
  GET   /api/v1/me/driver
  PATCH /api/v1/me/driver   {photoUrl}

The public driver directory lives in test_bwp_router.py. Account↔driver
linking is fully automatic (discord_uid) and covered in
test_drivers_service.py — there are no manual link endpoints.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _now():
    return datetime.now(timezone.utc)


async def _link_driver(db: AsyncSession, user_id, name="My Driver"):
    from app.models.bwp import Driver

    driver = Driver(name=name, user_id=user_id, created_at=_now())
    db.add(driver)
    await db.commit()
    return driver


# ---------------------------------------------------------------------------
# GET /api/v1/me/driver
# ---------------------------------------------------------------------------

async def test_get_my_driver_returns_linked_driver(
    auth_client: AsyncClient, db: AsyncSession, test_user
):
    await _link_driver(db, test_user.id)

    resp = await auth_client.get("/api/v1/me/driver")
    assert resp.status_code == 200
    assert resp.json()["name"] == "My Driver"
    assert resp.json()["userId"] == str(test_user.id)


async def test_get_my_driver_404_when_not_linked(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/me/driver")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "No linked driver."


async def test_get_my_driver_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/me/driver")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /api/v1/me/driver
# ---------------------------------------------------------------------------

async def test_set_and_clear_photo(auth_client: AsyncClient, db: AsyncSession, test_user):
    await _link_driver(db, test_user.id)

    resp = await auth_client.patch(
        "/api/v1/me/driver", json={"photoUrl": "  https://example.com/me.png "}
    )
    assert resp.status_code == 200
    assert resp.json()["photoUrl"] == "https://example.com/me.png"

    resp = await auth_client.patch("/api/v1/me/driver", json={"photoUrl": None})
    assert resp.status_code == 200
    assert resp.json()["photoUrl"] is None


@pytest.mark.parametrize(
    "url",
    ["http://example.com/me.png", "javascript:alert(1)", "https://", "ftp://x/y.png"],
)
async def test_photo_must_be_https(
    auth_client: AsyncClient, db: AsyncSession, test_user, url
):
    await _link_driver(db, test_user.id)
    resp = await auth_client.patch("/api/v1/me/driver", json={"photoUrl": url})
    assert resp.status_code == 422


async def test_photo_url_length_limit(auth_client: AsyncClient, db: AsyncSession, test_user):
    await _link_driver(db, test_user.id)
    url = "https://example.com/" + "a" * 500
    resp = await auth_client.patch("/api/v1/me/driver", json={"photoUrl": url})
    assert resp.status_code == 422


async def test_photo_404_when_not_linked(auth_client: AsyncClient):
    resp = await auth_client.patch(
        "/api/v1/me/driver", json={"photoUrl": "https://example.com/me.png"}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Removed endpoints stay removed
# ---------------------------------------------------------------------------

async def test_old_profile_endpoints_are_gone(auth_client: AsyncClient):
    assert (await auth_client.get("/api/profile/me/driver")).status_code == 404
    assert (await auth_client.get("/api/profile/link-candidates")).status_code == 404
    assert (
        await auth_client.post(
            "/api/profile/link-driver", json={"driverId": str(uuid.uuid4())}
        )
    ).status_code == 404

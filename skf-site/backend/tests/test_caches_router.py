"""Tests for DELETE /api/v1/caches[/{domain}]."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.test_users_router import admin_client  # noqa: F401 – fixture


@pytest.fixture
def cleared(monkeypatch) -> list[str]:
    from app.services.simgrid import simgrid_service
    from app.services.youtube import youtube_service

    calls: list[str] = []

    async def clear_simgrid(*_args):
        calls.append("simgrid")

    async def clear_youtube():
        calls.append("youtube")

    monkeypatch.setattr(simgrid_service, "invalidate_cache", clear_simgrid)
    monkeypatch.setattr(youtube_service, "invalidate_cache", clear_youtube)
    return calls


async def test_clear_one_domain(admin_client: AsyncClient, cleared: list[str]):  # noqa: F811
    resp = await admin_client.delete("/api/v1/caches/simgrid")
    assert resp.status_code == 204
    assert cleared == ["simgrid"]


async def test_clear_all(admin_client: AsyncClient, cleared: list[str]):  # noqa: F811
    resp = await admin_client.delete("/api/v1/caches")
    assert resp.status_code == 204
    assert sorted(cleared) == ["simgrid", "youtube"]


async def test_unknown_domain_is_404(admin_client: AsyncClient, cleared: list[str]):  # noqa: F811
    resp = await admin_client.delete("/api/v1/caches/nope")
    assert resp.status_code == 404
    assert cleared == []


async def test_requires_admin(auth_client: AsyncClient, cleared: list[str]):
    resp = await auth_client.delete("/api/v1/caches/youtube")
    assert resp.status_code == 403
    assert cleared == []

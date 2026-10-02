"""Every 201 names its new resource in ``Location``, and that URL can be read back."""

from __future__ import annotations

from httpx import AsyncClient

from tests.test_users_router import admin_client  # noqa: F401 – fixture

API = "/api/v1"


async def _create(client: AsyncClient, method: str, path: str, json: dict | None = None) -> dict:
    resp = await client.request(method, f"{API}{path}", json=json)
    assert resp.status_code == 201, f"{method} {path}: {resp.text}"

    read = await client.get(resp.headers["location"])
    assert read.status_code == 200, f"{resp.headers['location']}: {read.text}"
    # A read may be a narrower projection (a driver without its account), never a different one.
    assert read.json().items() <= resp.json().items()
    return resp.json()


async def test_catalogue_resources_can_be_read_back(admin_client: AsyncClient):  # noqa: F811
    await _create(admin_client, "POST", "/communities", {"name": "Readable"})
    await _create(admin_client, "POST", "/languages", {"code": "zz", "name": "Zed"})
    await _create(admin_client, "POST", "/verdict-rules", {"verdict": "Warning"})
    await _create(admin_client, "POST", "/description-presets", {"text": "Divebomb"})
    await _create(admin_client, "POST", "/regulation-pages", {"slug": "readable"})


async def test_driver_resources_can_be_read_back(admin_client: AsyncClient):  # noqa: F811
    driver = await _create(admin_client, "POST", "/drivers", {"name": "Readable Driver"})
    rule = await _create(admin_client, "POST", "/penalty-rules", {"threshold": 5, "label": "Race ban"})
    await _create(
        admin_client,
        "POST",
        f"/drivers/{driver['id']}/bwp-points",
        {"points": 2, "issuedOn": "2026-01-01", "expiresOn": "2026-04-01"},
    )
    await _create(admin_client, "PUT", f"/drivers/{driver['id']}/clearances/{rule['id']}")


async def test_incident_resources_can_be_read_back(admin_client: AsyncClient):  # noqa: F811
    window = await _create(admin_client, "POST", "/incident-windows", {"raceName": "Round 1"})
    incident = await _create(
        admin_client, "POST", f"/incident-windows/{window['id']}/incidents", {"drivers": ["A", "B"]}
    )
    await _create(admin_client, "POST", f"/incidents/{incident['id']}/drivers", {"driverName": "C"})
    await _create(admin_client, "POST", f"/incidents/{incident['id']}/copies")


async def test_custom_championship_resources_can_be_read_back(admin_client: AsyncClient):  # noqa: F811
    champ = await _create(admin_client, "POST", "/custom-championships", {"name": "Cup", "game": "LMU"})
    await _create(admin_client, "POST", f"/custom-championships/{champ['id']}/races", {"track": "Spa"})

"""Calendar events: the date range and the in-memory SimGrid snapshot."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.models.active_championship import ActiveChampionship
from app.schemas.championship import ChampionshipSummaryOut
from app.services import calendar_events as service
from app.services import championships as championships_service
from app.services import simgrid as sg_mod

URL = "/api/v1/calendar-events"
YEAR_2026 = {"from": "2026-01-01", "to": "2026-12-31"}

DATED, DATELESS, INACTIVE = 101, 102, 103


@pytest.fixture
async def simgrid(db, simgrid_stub, monkeypatch):
    """Three SimGrid championships, two of them active; counts the race lookups."""
    db.add_all([ActiveChampionship(simgrid_id=DATED), ActiveChampionship(simgrid_id=DATELESS)])
    await db.commit()

    async def get_championships():
        return [ChampionshipSummaryOut(id=i, name=f"Championship {i}") for i in (DATED, DATELESS, INACTIVE)]

    monkeypatch.setattr(sg_mod.simgrid_service, "get_championships", get_championships)
    simgrid_stub.races = {
        DATED: [{"starts_at": "2026-05-10T18:00:00+00:00", "track": {"name": "Spa"}}],
        INACTIVE: [{"starts_at": "2026-05-17T18:00:00+00:00", "track": {"name": "Monza"}}],
    }

    stub_races = sg_mod.simgrid_service.get_races
    simgrid_stub.race_lookups = 0

    async def get_races(championship_id):
        simgrid_stub.race_lookups += 1
        return await stub_races(championship_id)

    monkeypatch.setattr(sg_mod.simgrid_service, "get_races", get_races)
    return simgrid_stub


async def _names(client, params) -> set[str]:
    resp = await client.get(URL, params=params)
    assert resp.status_code == 200
    return {e["name"] for e in resp.json()}


async def test_range_keeps_overlapping_and_dateless_championships(client, simgrid):
    assert await _names(client, {"from": "2026-05-10", "to": "2026-05-10"}) == {
        "Championship 101",
        "Championship 102",
    }
    assert await _names(client, {"from": "2026-05-11", "to": "2027-12-31"}) == {"Championship 102"}


async def test_range_must_not_end_before_it_starts(client, simgrid):
    resp = await client.get(URL, params={"from": "2026-05-02", "to": "2026-05-01"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


async def test_simgrid_is_read_once_for_any_number_of_requests(client, simgrid):
    await _names(client, YEAR_2026)
    lookups = simgrid.race_lookups
    assert lookups == 2

    await _names(client, {"from": "2027-01-01", "to": "2027-12-31"})
    assert simgrid.race_lookups == lookups


async def test_old_snapshot_is_served_while_it_is_rebuilt(client, simgrid):
    await _names(client, YEAR_2026)
    service._snapshot = replace(service._snapshot, built_at=datetime(2026, 1, 1, tzinfo=UTC))
    simgrid.races[DATELESS] = [{"starts_at": "2026-06-01T18:00:00+00:00"}]

    first = (await client.get(URL, params=YEAR_2026)).json()
    assert {e["name"]: len(e["races"]) for e in first} == {"Championship 101": 1, "Championship 102": 0}

    await service._refresh_task
    second = (await client.get(URL, params=YEAR_2026)).json()
    assert {e["name"]: len(e["races"]) for e in second} == {"Championship 101": 1, "Championship 102": 1}


async def test_failed_rebuild_keeps_the_old_snapshot(client, simgrid, monkeypatch):
    await _names(client, YEAR_2026)
    service._snapshot = replace(service._snapshot, built_at=datetime(2026, 1, 1, tzinfo=UTC))

    async def unavailable():
        raise RuntimeError("SimGrid is down")

    monkeypatch.setattr(sg_mod.simgrid_service, "get_championships", unavailable)
    await _names(client, YEAR_2026)
    await service._refresh_task

    assert await _names(client, YEAR_2026) == {"Championship 101", "Championship 102"}


async def test_activating_a_championship_shows_it_at_once(client, db, simgrid):
    assert "Championship 103" not in await _names(client, YEAR_2026)

    await championships_service.set_active(db, INACTIVE, True)

    assert "Championship 103" in await _names(client, YEAR_2026)

"""SimGrid response contract, checked against recorded (anonymised) payloads.

Fixtures in ``tests/fixtures/simgrid`` are real responses trimmed to two items.
When SimGrid changes shape, re-record them and these tests show what broke.
``RUN_SIMGRID_LIVE=1`` additionally validates the models against the live API
(needs ``SIMGRID_API_KEY`` in the environment).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.schemas.championship import ChampionshipDetails
from app.schemas.simgrid_raw import (
    RawChampionshipCarClass,
    RawChampionshipRef,
    RawNamed,
    RawParticipant,
    RawRace,
    RawSessionResultsPage,
    RawStandingsPage,
    collection,
)
from app.services import simgrid as sg_mod
from app.services.simgrid import SimgridService

FIXTURES = Path(__file__).parent / "fixtures" / "simgrid"
LIVE_CHAMPIONSHIP_ID = 26927
LIVE_RACE_ID = 256741

COLLECTIONS = {
    "championships": RawChampionshipRef,
    "races": RawRace,
    "participating_users": RawParticipant,
    "championship_car_classes": RawChampionshipCarClass,
    "games": RawNamed,
    "car_classes": RawNamed,
}


def _fixture(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def memory_cache(monkeypatch):
    cache: dict = {}

    async def read_cache(key, ttl):
        return cache.get(key)

    async def write_cache(key, value):
        cache[key] = value

    monkeypatch.setattr(sg_mod, "read_cache", read_cache)
    monkeypatch.setattr(sg_mod, "read_stale_cache", lambda key: read_cache(key, None))
    monkeypatch.setattr(sg_mod, "write_cache", write_cache)
    monkeypatch.setattr(sg_mod, "mark_stale", lambda: None)
    return cache


def _serve(monkeypatch, service: SimgridService, body) -> None:
    async def fake_get(url, params=None):
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(service, "_get", fake_get)


# ── Recorded payloads ──────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(COLLECTIONS))
def test_recorded_collections_match_models(name):
    page = collection(COLLECTIONS[name], _fixture(name))
    assert page.data


def test_recorded_championship_details():
    details = ChampionshipDetails(**_fixture("championship"))
    assert details.id and details.name and details.start_date


def test_recorded_standings_map_to_entries_and_races():
    raw = RawStandingsPage.model_validate(_fixture("standings"))
    data = SimgridService._parse_standings(raw)
    assert [e.id for e in data.entries] == [1001, 1002]
    assert all(e.car_class and e.display_name for e in data.entries)
    assert data.races and all(r.id and r.display_name for r in data.races)


def test_standings_total_pages():
    def page(total):
        return RawStandingsPage.model_validate(
            {"data": [], "pagination": {"limit": 40, "offset": 0, "total_count": total}}
        )

    assert SimgridService._standings_total_pages(page(21)) == 1
    assert SimgridService._standings_total_pages(page(81)) == 3
    assert (
        SimgridService._standings_total_pages(
            RawStandingsPage.model_validate({"data": [], "pagination": None})
        )
        == 1
    )


# ── Shape changes must fail loudly ─────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(COLLECTIONS))
def test_bare_array_is_rejected(name):
    """The pre-2026-09-28 shape: a bare array must not pass as a collection."""
    with pytest.raises(ValidationError):
        collection(COLLECTIONS[name], _fixture(name)["data"])


async def test_races_shape_change_raises_instead_of_empty(monkeypatch, memory_cache):
    service = SimgridService()
    _serve(monkeypatch, service, _fixture("races")["data"])
    with pytest.raises(ValidationError):
        await service.get_races(1)


async def test_races_shape_change_falls_back_to_stale(monkeypatch, memory_cache):
    stale = [{"id": 7, "race_name": "Round 1"}]

    async def expired(key, ttl):
        return None

    async def read_stale_cache(key):
        return stale

    monkeypatch.setattr(sg_mod, "read_cache", expired)
    monkeypatch.setattr(sg_mod, "read_stale_cache", read_stale_cache)
    service = SimgridService()
    _serve(monkeypatch, service, {"unexpected": True})
    assert await service.get_races(1) == stale


# ── Service behaviour on recorded payloads ─────────────────────────────────


async def test_championships_list_is_unwrapped_and_empty_cache_refetched(monkeypatch, memory_cache):
    memory_cache["championships_list_200"] = []
    service = SimgridService()
    body = _fixture("championships")
    body["pagination"] = {"limit": 200, "offset": 0, "total_count": len(body["data"])}
    _serve(monkeypatch, service, body)

    items = await service.get_championships()
    assert [i.id for i in items] == [c["id"] for c in body["data"]]
    assert memory_cache["championships_list_200"] == body["data"]


async def test_races_cache_raw_items(monkeypatch, memory_cache):
    service = SimgridService()
    body = _fixture("races")
    _serve(monkeypatch, service, body)

    assert await service.get_races(1) == body["data"]
    assert memory_cache["races_1"] == body["data"]


async def test_non_list_cache_is_refetched(monkeypatch, memory_cache):
    """Collections cached whole before 2026-09-28 are treated as a miss."""
    memory_cache["races_1"] = {"data": [{"id": 1}], "pagination": None}
    service = SimgridService()
    body = _fixture("races")
    _serve(monkeypatch, service, body)
    assert await service.get_races(1) == body["data"]


# ── Live contract (opt-in) ─────────────────────────────────────────────────


@pytest.mark.skipif(os.environ.get("RUN_SIMGRID_LIVE") != "1", reason="set RUN_SIMGRID_LIVE=1")
def test_live_api_matches_models():
    headers = {"Authorization": f"Bearer {os.environ['SIMGRID_API_KEY']}"}
    cid = LIVE_CHAMPIONSHIP_ID
    paths = {
        "championships": ("/championships", {"limit": 5}),
        "races": ("/races", {"championship_id": cid, "limit": 5}),
        "participating_users": (f"/championships/{cid}/participating_users", None),
        "championship_car_classes": (f"/championships/{cid}/championship_car_classes", None),
        "games": ("/games", None),
        "car_classes": ("/car_classes", {"game_id": 65}),
    }
    with httpx.Client(base_url="https://www.thesimgrid.com/api/v1", headers=headers, timeout=30) as client:
        for name, (path, params) in paths.items():
            collection(COLLECTIONS[name], client.get(path, params=params).raise_for_status().json())
        ChampionshipDetails(**client.get(f"/championships/{cid}").raise_for_status().json())
        RawStandingsPage.model_validate(
            client.get(f"/championships/{cid}/standings").raise_for_status().json()
        )
        for session in ("race_1", "qualifying"):
            page = RawSessionResultsPage.model_validate(
                client.get(
                    f"/races/{LIVE_RACE_ID}/session_results",
                    params={"session_type": session, "result_type": "results"},
                )
                .raise_for_status()
                .json()
            )
            assert page.data

"""Parsing of SimGrid's wrapped collection payloads (``{"data", "pagination"}``)."""
from __future__ import annotations

import httpx

from app.services import simgrid as sg_mod
from app.services.simgrid import SimgridService, _unwrap


def test_unwrap_collection_and_passthrough():
    assert _unwrap({"data": [{"id": 1}], "pagination": None}) == [{"id": 1}]
    assert _unwrap([{"id": 1}]) == [{"id": 1}]
    assert _unwrap({"id": 1, "name": "x"}) == {"id": 1, "name": "x"}
    assert _unwrap(None) is None


def test_parse_wrapped_standings():
    raw = {
        "data": [{
            "id": 999, "user_id": 42, "position_cache": 1, "display_name": "Driver",
            "championship_points": 25.0, "championship_score": 25.0,
            "championship_car_class": {"display_name": "GT3"},
            "participant": {"country_code": "UA"},
        }],
        "pagination": {"limit": 40, "offset": 0, "total_count": 1},
        "completed_races": [{"id": 7, "display_name": "Round 1", "ended": True}],
        "standings": None,
        "is_series": False,
    }
    data = SimgridService._parse_standings(raw)
    assert [(e.id, e.car_class, e.country_code) for e in data.entries] == [(42, "GT3", "UA")]
    assert [(r.id, r.ended) for r in data.races] == [(7, True)]


def test_standings_total_pages_from_total_count():
    page = lambda total: {"data": [], "pagination": {"limit": 40, "offset": 0, "total_count": total}}
    assert SimgridService._standings_total_pages(page(21)) == 1
    assert SimgridService._standings_total_pages(page(81)) == 3
    assert SimgridService._standings_total_pages({"data": [], "pagination": None}) == 1


async def test_championships_list_is_unwrapped_and_empty_cache_refetched(monkeypatch):
    cache: dict = {"championships_list_200": []}

    async def read_cache(key, ttl):
        return cache.get(key)

    async def write_cache(key, value):
        cache[key] = value

    async def fake_get(url, params=None):
        body = {
            "data": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
            "pagination": {"limit": 200, "offset": 0, "total_count": 2},
        }
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(sg_mod, "read_cache", read_cache)
    monkeypatch.setattr(sg_mod, "write_cache", write_cache)
    service = SimgridService()
    monkeypatch.setattr(service, "_get", fake_get)

    items = await service.get_championships()
    assert [i.id for i in items] == [1, 2]
    assert [i["id"] for i in cache["championships_list_200"]] == [1, 2]

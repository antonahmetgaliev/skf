"""Custom championships: CRUD, races and community-manager access (IDOR)."""
from __future__ import annotations

import pytest

from app.models.community import Community
from app.models.custom_championship import CustomChampionship, CustomRace
from tests.roles import act_as, assign_manager, make_user

URL = "/api/v1/custom-championships"


@pytest.fixture(autouse=True)
def _anonymous_after():
    yield
    act_as(None)


@pytest.fixture
async def setup(db):
    mine = Community(name="Mine")
    foreign = Community(name="Foreign")
    db.add_all([mine, foreign])
    await db.commit()
    champs = {
        "mine": CustomChampionship(name="Mine Cup", game="ACC", community_id=mine.id),
        "foreign": CustomChampionship(name="Foreign Cup", game="ACC", community_id=foreign.id),
        "orphan": CustomChampionship(name="Orphan Cup", game="ACC", community_id=None),
    }
    champs["mine"].races.append(CustomRace(track="Spa", sort_order=0))
    db.add_all(champs.values())
    await db.commit()

    manager = await make_user(db, "community_manager")
    await assign_manager(db, manager, mine.id)
    admin = await make_user(db, "admin")
    return {"mine": mine, "foreign": foreign, "champs": champs, "manager": manager, "admin": admin}


# ── Admin ────────────────────────────────────────────────────────────────────


async def test_admin_lists_all_paginated(client, setup):
    act_as(setup["admin"])
    resp = await client.get(URL, params={"limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()) == 2
    assert resp.headers["X-Total-Count"] == "3"


async def test_admin_full_lifecycle(client, setup):
    act_as(setup["admin"])
    resp = await client.post(URL, json={"name": "New", "game": "iRacing", "races": [{"track": "Monza"}]})
    assert resp.status_code == 201
    champ = resp.json()
    assert resp.headers["Location"] == f"{URL}/{champ['id']}"
    assert [r["track"] for r in champ["races"]] == ["Monza"]

    resp = await client.post(f"{URL}/{champ['id']}/races", json={"track": " Spa "})
    assert resp.status_code == 201
    race = resp.json()
    assert race["track"] == "Spa" and race["sortOrder"] == 1
    assert resp.headers["Location"] == f"{URL}/{champ['id']}/races/{race['id']}"

    resp = await client.patch(f"{URL}/{champ['id']}/races/{race['id']}", json={"track": "Imola"})
    assert resp.status_code == 200 and resp.json()["track"] == "Imola"

    resp = await client.put(f"{URL}/{champ['id']}/races", json=[{"id": race["id"], "track": "Imola"}, {"track": "Zandvoort"}])
    assert resp.status_code == 200
    assert [r["track"] for r in resp.json()] == ["Imola", "Zandvoort"]

    assert (await client.delete(f"{URL}/{champ['id']}/races/{race['id']}")).status_code == 204
    assert (await client.delete(f"{URL}/{champ['id']}")).status_code == 204
    assert (await client.get(f"{URL}/{champ['id']}")).status_code == 404


async def test_admin_can_detach_from_community(client, setup):
    act_as(setup["admin"])
    champ = setup["champs"]["mine"]
    resp = await client.patch(f"{URL}/{champ.id}", json={"communityId": None})
    assert resp.status_code == 200 and resp.json()["communityId"] is None


# ── Community manager ────────────────────────────────────────────────────────


async def test_manager_lists_only_managed(client, setup):
    act_as(setup["manager"])
    resp = await client.get(URL)
    assert resp.status_code == 200
    assert [c["name"] for c in resp.json()] == ["Mine Cup"]
    assert (await client.get(URL, params={"communityId": str(setup["foreign"].id)})).status_code == 403


async def test_manager_manages_own_championship(client, setup):
    act_as(setup["manager"])
    champ = setup["champs"]["mine"]
    assert (await client.get(f"{URL}/{champ.id}")).status_code == 200
    resp = await client.patch(f"{URL}/{champ.id}", json={"name": "Renamed"})
    assert resp.status_code == 200 and resp.json()["name"] == "Renamed"


@pytest.mark.parametrize("which", ["foreign", "orphan"])
async def test_manager_cannot_touch_foreign_or_orphan(client, setup, which):
    act_as(setup["manager"])
    champ = setup["champs"][which]
    assert (await client.get(f"{URL}/{champ.id}")).status_code == 403
    assert (await client.patch(f"{URL}/{champ.id}", json={"name": "X"})).status_code == 403
    assert (await client.delete(f"{URL}/{champ.id}")).status_code == 403
    assert (await client.post(f"{URL}/{champ.id}/races", json={"track": "X"})).status_code == 403
    assert (await client.put(f"{URL}/{champ.id}/races", json=[])).status_code == 403


async def test_manager_cannot_create_without_or_in_foreign_community(client, setup):
    act_as(setup["manager"])
    body = {"name": "New", "game": "ACC"}
    assert (await client.post(URL, json=body)).status_code == 403
    assert (await client.post(URL, json={**body, "communityId": str(setup["foreign"].id)})).status_code == 403
    assert (await client.post(URL, json={**body, "communityId": str(setup["mine"].id)})).status_code == 201


@pytest.mark.parametrize("target", ["foreign", None])
async def test_manager_cannot_move_championship_out(client, setup, target):
    act_as(setup["manager"])
    champ = setup["champs"]["mine"]
    community_id = str(setup[target].id) if target else None
    resp = await client.patch(f"{URL}/{champ.id}", json={"communityId": community_id})
    assert resp.status_code == 403
    act_as(setup["admin"])
    assert (await client.get(f"{URL}/{champ.id}")).json()["communityId"] == str(setup["mine"].id)


async def test_driver_is_forbidden(client, db, setup):
    act_as(await make_user(db, "driver"))
    assert (await client.get(URL)).status_code == 403


async def test_calendar_events_include_visible_custom_championships(client, setup, monkeypatch):
    from app.services import simgrid as sg_mod

    async def no_championships():
        return []

    monkeypatch.setattr(sg_mod.simgrid_service, "get_championships", no_championships)
    resp = await client.get("/api/v1/calendar-events", params={"year": 2026})
    assert resp.status_code == 200
    events = {e["name"]: e for e in resp.json()}
    # Championships without dated races are listed as unscheduled.
    assert set(events) == {"Mine Cup", "Foreign Cup", "Orphan Cup"}
    mine = events["Mine Cup"]
    assert mine["source"] == "custom" and mine["communityName"] == "Mine"
    assert mine["customChampionshipId"] == str(setup["champs"]["mine"].id)

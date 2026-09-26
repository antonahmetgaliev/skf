"""Communities: public list, ``?scope=managed`` and admin CRUD."""
from __future__ import annotations

import pytest

from app.models.community import Community
from tests.roles import act_as, assign_manager, make_user

URL = "/api/v1/communities"


@pytest.fixture(autouse=True)
def _anonymous_after():
    yield
    act_as(None)


@pytest.fixture
async def communities(db):
    skf = Community(name="SKF", is_skf=True)
    visible = Community(name="Alpha")
    hidden = Community(name="Hidden", is_visible=False)
    db.add_all([skf, visible, hidden])
    await db.commit()
    return skf, visible, hidden


async def test_public_list_returns_visible_skf_first(client, communities):
    resp = await client.get(URL)
    assert resp.status_code == 200
    assert [c["name"] for c in resp.json()] == ["SKF", "Alpha"]


async def test_managed_scope_requires_login(client, communities):
    assert (await client.get(URL, params={"scope": "managed"})).status_code == 401


async def test_managed_scope_admin_sees_hidden(client, db, communities):
    act_as(await make_user(db, "admin"))
    resp = await client.get(URL, params={"scope": "managed"})
    assert resp.status_code == 200
    assert {c["name"] for c in resp.json()} == {"SKF", "Alpha", "Hidden"}


async def test_managed_scope_manager_sees_only_assigned(client, db, communities):
    _, _, hidden = communities
    manager = await make_user(db, "community_manager")
    await assign_manager(db, manager, hidden.id)
    act_as(manager)
    resp = await client.get(URL, params={"scope": "managed"})
    assert resp.status_code == 200
    assert [c["name"] for c in resp.json()] == ["Hidden"]


async def test_managed_scope_forbidden_for_driver(client, db, communities):
    act_as(await make_user(db, "driver"))
    assert (await client.get(URL, params={"scope": "managed"})).status_code == 403


async def test_unknown_scope_is_rejected(client, communities):
    assert (await client.get(URL, params={"scope": "all"})).status_code == 422


async def test_admin_crud(client, db, communities):
    act_as(await make_user(db, "admin"))
    resp = await client.post(URL, json={"name": " New ", "discordUrl": "https://discord.gg/x"})
    assert resp.status_code == 201
    created = resp.json()
    assert created["name"] == "New"
    assert resp.headers["Location"] == f"{URL}/{created['id']}"

    resp = await client.patch(f"{URL}/{created['id']}", json={"isVisible": False})
    assert resp.status_code == 200 and resp.json()["isVisible"] is False

    assert (await client.delete(f"{URL}/{created['id']}")).status_code == 204


async def test_skf_community_cannot_be_deleted(client, db, communities):
    skf, _, _ = communities
    act_as(await make_user(db, "admin"))
    resp = await client.delete(f"{URL}/{skf.id}")
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_manager_can_only_patch_managed_community(client, db, communities):
    _, alpha, hidden = communities
    manager = await make_user(db, "community_manager")
    await assign_manager(db, manager, alpha.id)
    act_as(manager)
    assert (await client.patch(f"{URL}/{alpha.id}", json={"color": "#fff"})).status_code == 200
    assert (await client.patch(f"{URL}/{hidden.id}", json={"color": "#fff"})).status_code == 403
    assert (await client.post(URL, json={"name": "X"})).status_code == 403

"""Regulations: public localized views and admin ``regulation-pages`` by UUID."""

from __future__ import annotations

import uuid

import pytest

from app.models.translation import Language
from app.services import regulations as regulations_service
from tests.roles import act_as, make_user

PAGES = "/api/v1/regulation-pages"


@pytest.fixture(autouse=True)
def _reset():
    regulations_service.invalidate_cache()
    yield
    regulations_service.invalidate_cache()
    act_as(None)


@pytest.fixture
async def admin(db):
    db.add_all([Language(code="en", name="English"), Language(code="ua", name="Українська")])
    await db.commit()
    user = await make_user(db, "admin")
    act_as(user)
    return user


BODY = {
    "slug": "general",
    "sortOrder": 2,
    "contents": {"en": {"title": "General", "content": "Rules"}, "ua": {"title": "Загальні"}},
}


async def test_crud_by_uuid(client, admin):
    resp = await client.post(PAGES, json=BODY)
    assert resp.status_code == 201
    page = resp.json()
    assert page["sortOrder"] == 2 and page["isVisible"] is True
    assert resp.headers["Location"] == f"{PAGES}/{page['id']}"

    resp = await client.get(f"{PAGES}/{page['id']}")
    assert resp.status_code == 200 and resp.json()["contents"]["ua"]["title"] == "Загальні"

    # The slug is mutable, the UUID key is not.
    resp = await client.patch(f"{PAGES}/{page['id']}", json={"slug": "basics", "isVisible": False})
    assert resp.status_code == 200
    assert resp.json()["slug"] == "basics" and resp.json()["isVisible"] is False
    assert resp.json()["contents"]["en"]["content"] == "Rules"  # untouched

    resp = await client.patch(f"{PAGES}/{page['id']}", json={"contents": {"en": {"title": "Basics"}}})
    assert resp.json()["contents"]["en"]["title"] == "Basics"

    assert len((await client.get(PAGES)).json()) == 1
    assert (await client.delete(f"{PAGES}/{page['id']}")).status_code == 204
    assert (await client.get(f"{PAGES}/{page['id']}")).status_code == 404


async def test_duplicate_slug_conflicts(client, admin):
    first = (await client.post(PAGES, json=BODY)).json()
    assert (await client.post(PAGES, json=BODY)).status_code == 409
    other = (await client.post(PAGES, json={**BODY, "slug": "other"})).json()
    assert (await client.patch(f"{PAGES}/{other['id']}", json={"slug": first["slug"]})).status_code == 409


async def test_unknown_page_is_404(client, admin):
    assert (await client.patch(f"{PAGES}/{uuid.uuid4()}", json={"sortOrder": 1})).status_code == 404


async def test_admin_only(client, db):
    act_as(await make_user(db, "driver"))
    assert (await client.get(PAGES)).status_code == 403
    act_as(None)
    assert (await client.get(PAGES)).status_code == 401


async def test_public_views_follow_visibility_and_language(client, admin):
    page = (await client.post(PAGES, json=BODY)).json()
    hidden = (await client.post(PAGES, json={**BODY, "slug": "hidden", "sortOrder": 1})).json()
    await client.patch(f"{PAGES}/{hidden['id']}", json={"isVisible": False})
    act_as(None)

    listing = (await client.get("/api/v1/regulations", params={"lang": "ua"})).json()
    assert [(p["slug"], p["title"]) for p in listing] == [("general", "Загальні")]
    assert listing[0]["id"] == page["id"] and listing[0]["sortOrder"] == 2

    resp = await client.get("/api/v1/regulations/general", params={"lang": "en"})
    assert resp.status_code == 200 and resp.json()["content"] == "Rules"
    # Missing language falls back to another one.
    assert (await client.get("/api/v1/regulations/general", params={"lang": "de"})).status_code == 200
    assert (await client.get("/api/v1/regulations/hidden")).status_code == 404

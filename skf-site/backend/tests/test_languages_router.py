"""Languages and flat translation maps."""
from __future__ import annotations

import pytest

from app.models.translation import Language, Translation
from app.services import translations as translations_service
from tests.roles import act_as, make_user

LANGS = "/api/v1/languages"


@pytest.fixture(autouse=True)
def _reset():
    translations_service.invalidate_cache()
    yield
    translations_service.invalidate_cache()
    act_as(None)


@pytest.fixture
async def seeded(db):
    db.add_all([
        Language(code="en", name="English"),
        Language(code="xx", name="Draft", is_active=False),
        Translation(lang="en", key="home.title", value="Home"),
        Translation(lang="en", key="nav.home", value="Home page"),
    ])
    await db.commit()


@pytest.fixture
async def admin(db, seeded):
    user = await make_user(db, "admin")
    act_as(user)
    return user


async def test_public_language_list_hides_inactive(client, seeded):
    resp = await client.get(LANGS)
    assert resp.status_code == 200
    assert resp.json() == [{"code": "en", "name": "English", "isActive": True}]


async def test_admin_sees_inactive_languages(client, admin):
    assert [l["code"] for l in (await client.get(LANGS)).json()] == ["en", "xx"]


async def test_public_translation_map(client, seeded):
    resp = await client.get(f"{LANGS}/en/translations")
    assert resp.status_code == 200
    assert resp.json() == {"home.title": "Home", "nav.home": "Home page"}
    assert "content-disposition" not in resp.headers

    resp = await client.get(f"{LANGS}/en/translations", params={"prefix": "nav."})
    assert resp.json() == {"nav.home": "Home page"}


async def test_download_sets_content_disposition(client, seeded):
    resp = await client.get(f"{LANGS}/en/translations", params={"download": "true"})
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == 'attachment; filename="translations_en.json"'
    assert resp.json()["home.title"] == "Home"


async def test_patch_merges_and_invalidates_cache(client, admin):
    await client.get(f"{LANGS}/en/translations")  # warm the cache
    resp = await client.patch(f"{LANGS}/en/translations", json={"home.title": "Start", "new.key": "New"})
    assert resp.status_code == 204
    assert (await client.get(f"{LANGS}/en/translations")).json() == {
        "home.title": "Start",
        "new.key": "New",
        "nav.home": "Home page",
    }


async def test_patch_validation(client, admin):
    url = f"{LANGS}/en/translations"
    assert (await client.patch(url, json={"a": 1})).status_code == 422
    assert (await client.patch(url, json={"k" * 256: "v"})).status_code == 422
    assert (await client.patch(url, json=["a"])).status_code == 422
    too_many = {f"key.{i}": "v" for i in range(5001)}
    resp = await client.patch(url, json=too_many)
    assert resp.status_code == 413
    assert (await client.patch(f"{LANGS}/zz/translations", json={"a": "b"})).status_code == 404


async def test_patch_accepts_the_limit(client, admin):
    entries = {f"bulk.{i:04d}": str(i) for i in range(5000)}
    assert (await client.patch(f"{LANGS}/en/translations", json=entries)).status_code == 204
    assert len((await client.get(f"{LANGS}/en/translations", params={"prefix": "bulk."})).json()) == 5000


async def test_delete_key_with_path(client, admin):
    assert (await client.delete(f"{LANGS}/en/translations/nav.home")).status_code == 204
    assert (await client.delete(f"{LANGS}/en/translations/nav.home")).status_code == 404
    await client.patch(f"{LANGS}/en/translations", json={"a/b": "slash"})
    assert (await client.delete(f"{LANGS}/en/translations/a/b")).status_code == 204


async def test_language_lifecycle(client, admin):
    resp = await client.post(LANGS, json={"code": "de", "name": "Deutsch"})
    assert resp.status_code == 201 and resp.headers["Location"] == f"{LANGS}/de"
    assert (await client.post(LANGS, json={"code": "de", "name": "Deutsch"})).status_code == 409
    await client.patch(f"{LANGS}/de/translations", json={"a": "b"})
    assert (await client.get(f"{LANGS}/de/translations")).json() == {"a": "b"}

    assert (await client.delete(f"{LANGS}/de")).status_code == 204
    assert (await client.get(f"{LANGS}/de/translations")).json() == {}
    assert (await client.delete(f"{LANGS}/de")).status_code == 404


async def test_writes_are_admin_only(client, db, seeded):
    act_as(await make_user(db, "driver"))
    assert (await client.patch(f"{LANGS}/en/translations", json={"a": "b"})).status_code == 403
    assert (await client.delete(f"{LANGS}/en/translations/home.title")).status_code == 403
    assert (await client.post(LANGS, json={"code": "de", "name": "Deutsch"})).status_code == 403
    assert (await client.delete(f"{LANGS}/en")).status_code == 403

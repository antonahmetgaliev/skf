"""Translations router – public serving and admin CRUD."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.translation import Language, Translation
from app.models.user import User
from app.schemas.translations import LanguageCreate, LanguageOut, TranslationBulkUpdate, TranslationItem

router = APIRouter(tags=["Translations"])

# Simple in-memory cache: {lang: (timestamp, data_dict)}
_cache: dict[str, tuple[float, dict[str, str]]] = {}
_CACHE_TTL = 60  # seconds


def _invalidate_cache(lang: str | None = None) -> None:
    if lang:
        _cache.pop(lang, None)
    else:
        _cache.clear()


# ─── Public endpoint ───────────────────────────────────────────────────────────


@router.get("/translations/{lang}")
async def get_translations(lang: str, db: AsyncSession = Depends(get_db)):
    """Return flat {key: value} JSON for a language. Used by transloco loader."""
    now = time.time()
    if lang in _cache and (now - _cache[lang][0]) < _CACHE_TTL:
        return _cache[lang][1]

    result = await db.execute(
        select(Translation.key, Translation.value).where(Translation.lang == lang)
    )
    data = {row.key: row.value for row in result.all()}
    _cache[lang] = (now, data)
    return data


# ─── Admin: Languages ──────────────────────────────────────────────────────────


@router.get("/admin/languages", response_model=list[LanguageOut])
async def list_languages(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Language).order_by(Language.code))
    return result.scalars().all()


@router.post("/admin/languages", response_model=LanguageOut, status_code=status.HTTP_201_CREATED)
async def add_language(
    body: LanguageCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    existing = await db.get(Language, body.code)
    if existing:
        raise HTTPException(status_code=409, detail="Language already exists.")
    lang = Language(code=body.code, name=body.name, is_active=True)
    db.add(lang)
    await db.commit()
    await db.refresh(lang)
    return lang


@router.delete("/admin/languages/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_language(
    code: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    lang = await db.get(Language, code)
    if not lang:
        raise HTTPException(status_code=404, detail="Language not found.")
    await db.execute(delete(Translation).where(Translation.lang == code))
    await db.delete(lang)
    await db.commit()
    _invalidate_cache(code)


# ─── Admin: Translations CRUD ─────────────────────────────────────────────────


@router.get("/admin/translations", response_model=list[TranslationItem])
async def list_translations(
    lang: str = Query(...),
    prefix: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    stmt = select(Translation.key, Translation.value).where(Translation.lang == lang)
    if prefix:
        stmt = stmt.where(Translation.key.startswith(prefix))
    stmt = stmt.order_by(Translation.key)
    result = await db.execute(stmt)
    return [TranslationItem(key=row.key, value=row.value) for row in result.all()]


@router.put("/admin/translations/{lang}", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_upsert_translations(
    lang: str,
    body: TranslationBulkUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Upsert translations for a language. Existing keys are updated, new keys are inserted."""
    # Verify language exists
    language = await db.get(Language, lang)
    if not language:
        raise HTTPException(status_code=404, detail="Language not found.")

    if not body.items:
        return

    # Use PostgreSQL ON CONFLICT upsert
    stmt = pg_insert(Translation).values(
        [{"lang": lang, "key": item.key, "value": item.value} for item in body.items]
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_translation_lang_key",
        set_={"value": stmt.excluded.value},
    )
    await db.execute(stmt)
    await db.commit()
    _invalidate_cache(lang)


@router.delete("/admin/translations/{lang}/{key:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_translation(
    lang: str,
    key: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        delete(Translation).where(Translation.lang == lang, Translation.key == key)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Translation not found.")
    await db.commit()
    _invalidate_cache(lang)


# ─── Admin: Import / Export ────────────────────────────────────────────────────


@router.get("/admin/translations/export/{lang}")
async def export_translations(
    lang: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Export all translations for a language as JSON."""
    result = await db.execute(
        select(Translation.key, Translation.value)
        .where(Translation.lang == lang)
        .order_by(Translation.key)
    )
    data = {row.key: row.value for row in result.all()}
    return JSONResponse(content=data)


@router.post("/admin/translations/import/{lang}", status_code=status.HTTP_204_NO_CONTENT)
async def import_translations(
    lang: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Import translations from a JSON file. Upserts all keys."""
    import json

    language = await db.get(Language, lang)
    if not language:
        raise HTTPException(status_code=404, detail="Language not found.")

    try:
        content = await file.read()
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON file.")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON must be a flat object {key: value}.")

    items = [{"lang": lang, "key": k, "value": str(v)} for k, v in data.items()]
    if items:
        stmt = pg_insert(Translation).values(items)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_translation_lang_key",
            set_={"value": stmt.excluded.value},
        )
        await db.execute(stmt)
        await db.commit()
    _invalidate_cache(lang)

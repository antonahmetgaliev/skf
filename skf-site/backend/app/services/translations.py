"""Languages and their flat ``{key: value}`` translation bundles."""

from __future__ import annotations

import time

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PayloadTooLarge, Unprocessable
from app.models.regulation import RegulationContent
from app.models.translation import Language, Translation
from app.schemas.translations import LanguageCreate
from app.services import regulations as regulations_service

MAX_KEYS_PER_PATCH = 5000
MAX_KEY_LENGTH = 255
_UPSERT_CHUNK = 1000

# In-process cache: {lang: (timestamp, bundle)} (per worker; see audit open questions).
_cache: dict[str, tuple[float, dict[str, str]]] = {}
_CACHE_TTL = 60


def invalidate_cache(lang: str | None = None) -> None:
    if lang:
        _cache.pop(lang, None)
    else:
        _cache.clear()


# ── Languages ────────────────────────────────────────────────────────────────


async def list_languages(db: AsyncSession, *, include_inactive: bool) -> list[Language]:
    stmt = select(Language).order_by(Language.code)
    if not include_inactive:
        stmt = stmt.where(Language.is_active.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def _get_language(db: AsyncSession, code: str) -> Language:
    language = await db.get(Language, code)
    if language is None:
        raise NotFound("Language not found.")
    return language


async def add_language(db: AsyncSession, body: LanguageCreate) -> Language:
    if await db.get(Language, body.code) is not None:
        raise Conflict("Language already exists.")
    language = Language(code=body.code, name=body.name.strip(), is_active=True)
    db.add(language)
    await db.commit()
    await db.refresh(language)
    return language


async def delete_language(db: AsyncSession, code: str) -> None:
    """Delete a language with its translations and regulation contents."""
    language = await _get_language(db, code)
    await db.execute(delete(Translation).where(Translation.lang == code))
    await db.execute(delete(RegulationContent).where(RegulationContent.lang == code))
    await db.delete(language)
    await db.commit()
    invalidate_cache(code)
    # Regulation views fall back to another language's content when one is missing.
    regulations_service.invalidate_cache()


# ── Translations ─────────────────────────────────────────────────────────────


async def get_bundle(db: AsyncSession, lang: str, prefix: str | None = None) -> dict[str, str]:
    """The flat ``{key: value}`` map for *lang*, sorted by key."""
    hit = _cache.get(lang)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        bundle = hit[1]
    else:
        result = await db.execute(
            select(Translation.key, Translation.value)
            .where(Translation.lang == lang)
            .order_by(Translation.key)
        )
        bundle = {row.key: row.value for row in result.all()}
        _cache[lang] = (time.time(), bundle)
    if prefix:
        return {k: v for k, v in bundle.items() if k.startswith(prefix)}
    return dict(bundle)


def _validate_patch(entries: dict[str, str]) -> None:
    if len(entries) > MAX_KEYS_PER_PATCH:
        raise PayloadTooLarge(
            f"At most {MAX_KEYS_PER_PATCH} translations can be saved per request."
        )
    for key in entries:
        if not key or len(key) > MAX_KEY_LENGTH:
            raise Unprocessable(
                f"Translation keys must be 1–{MAX_KEY_LENGTH} characters long."
            )


async def merge(db: AsyncSession, lang: str, entries: dict[str, str]) -> None:
    """Upsert *entries*: existing keys get the new value, new keys are added."""
    _validate_patch(entries)
    await _get_language(db, lang)
    if not entries:
        return

    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    rows = [{"lang": lang, "key": k, "value": v} for k, v in entries.items()]
    for i in range(0, len(rows), _UPSERT_CHUNK):
        stmt = insert(Translation).values(rows[i : i + _UPSERT_CHUNK])
        stmt = stmt.on_conflict_do_update(
            index_elements=[Translation.lang, Translation.key],
            set_={"value": stmt.excluded.value, "updated_at": func.now()},
        )
        await db.execute(stmt)
    await db.commit()
    invalidate_cache(lang)


async def delete_key(db: AsyncSession, lang: str, key: str) -> None:
    result = await db.execute(
        delete(Translation).where(Translation.lang == lang, Translation.key == key)
    )
    if result.rowcount == 0:
        raise NotFound("Translation not found.")
    await db.commit()
    invalidate_cache(lang)

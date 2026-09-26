"""Regulation pages: localized public views and admin CRUD."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.models.regulation import RegulationContent, RegulationPage
from app.repository import get_or_404
from app.schemas.regulations import (
    RegulationContentOut,
    RegulationPageCreate,
    RegulationPageListItem,
    RegulationPageOut,
    RegulationPageUpdate,
)

# In-process cache of the public views (per worker; see audit open questions).
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 120
PAGE_NOT_FOUND = "Regulation page not found."


def invalidate_cache() -> None:
    _cache.clear()


def _cached(key: str):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    return None


def _content_out(c: RegulationContent) -> RegulationContentOut:
    return RegulationContentOut(lang=c.lang, title=c.title, subtitle=c.subtitle, content=c.content)


def page_out(page: RegulationPage) -> RegulationPageOut:
    """The one place a :class:`RegulationPageOut` is built."""
    return RegulationPageOut(
        id=page.id,
        slug=page.slug,
        sort_order=page.sort_order,
        is_visible=page.is_visible,
        contents={c.lang: _content_out(c) for c in page.contents},
    )


def _pick_content(page: RegulationPage, lang: str) -> RegulationContent | None:
    """Content in *lang*, else the first available one."""
    for c in page.contents:
        if c.lang == lang:
            return c
    return page.contents[0] if page.contents else None


# ── Public ───────────────────────────────────────────────────────────────────


async def list_public(db: AsyncSession, lang: str) -> list[RegulationPageListItem]:
    key = f"list:{lang}"
    cached = _cached(key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    result = await db.execute(
        select(RegulationPage)
        .where(RegulationPage.is_visible.is_(True))
        .order_by(RegulationPage.sort_order, RegulationPage.slug)
    )
    items = []
    for page in result.scalars().all():
        content = _pick_content(page, lang)
        items.append(RegulationPageListItem(
            id=page.id,
            slug=page.slug,
            sort_order=page.sort_order,
            is_visible=page.is_visible,
            title=content.title if content else page.slug,
        ))
    _cache[key] = (time.time(), items)
    return items


async def get_public(db: AsyncSession, slug: str, lang: str) -> RegulationContentOut:
    key = f"page:{slug}:{lang}"
    cached = _cached(key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    page = (
        await db.execute(select(RegulationPage).where(RegulationPage.slug == slug))
    ).scalar_one_or_none()
    if page is None or not page.is_visible:
        raise NotFound(PAGE_NOT_FOUND)
    content = _pick_content(page, lang)
    if content is None:
        raise NotFound("No content available for this page.")
    out = _content_out(content)
    _cache[key] = (time.time(), out)
    return out


# ── Admin ────────────────────────────────────────────────────────────────────


async def list_all(db: AsyncSession) -> list[RegulationPageOut]:
    result = await db.execute(
        select(RegulationPage).order_by(RegulationPage.sort_order, RegulationPage.slug)
    )
    return [page_out(p) for p in result.scalars().all()]


async def get(db: AsyncSession, page_id: uuid.UUID) -> RegulationPageOut:
    return page_out(await get_or_404(db, RegulationPage, page_id, detail=PAGE_NOT_FOUND))


async def _ensure_slug_free(db: AsyncSession, slug: str) -> None:
    taken = await db.scalar(select(RegulationPage.id).where(RegulationPage.slug == slug))
    if taken is not None:
        raise Conflict("Slug already exists.")


async def create(db: AsyncSession, body: RegulationPageCreate) -> RegulationPageOut:
    await _ensure_slug_free(db, body.slug)
    page = RegulationPage(slug=body.slug, sort_order=body.sort_order, is_visible=body.is_visible)
    for lang, data in body.contents.items():
        page.contents.append(
            RegulationContent(lang=lang, title=data.title, subtitle=data.subtitle, content=data.content)
        )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    invalidate_cache()
    return page_out(page)


async def update(
    db: AsyncSession, page_id: uuid.UUID, body: RegulationPageUpdate
) -> RegulationPageOut:
    page = await get_or_404(db, RegulationPage, page_id, detail=PAGE_NOT_FOUND)

    if body.slug is not None and body.slug != page.slug:
        await _ensure_slug_free(db, body.slug)
        page.slug = body.slug
    if body.sort_order is not None:
        page.sort_order = body.sort_order
    if body.is_visible is not None:
        page.is_visible = body.is_visible
    if body.contents is not None:
        existing = {c.lang: c for c in page.contents}
        for lang, data in body.contents.items():
            content = existing.get(lang)
            if content is None:
                page.contents.append(
                    RegulationContent(lang=lang, title=data.title, subtitle=data.subtitle, content=data.content)
                )
            else:
                content.title = data.title
                content.subtitle = data.subtitle
                content.content = data.content

    await db.commit()
    await db.refresh(page)
    invalidate_cache()
    return page_out(page)


async def delete(db: AsyncSession, page_id: uuid.UUID) -> None:
    page = await get_or_404(db, RegulationPage, page_id, detail=PAGE_NOT_FOUND)
    await db.delete(page)
    await db.commit()
    invalidate_cache()

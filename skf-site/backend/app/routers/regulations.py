"""Regulations router – public serving and admin CRUD."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.regulation import RegulationContent, RegulationPage
from app.models.user import User
from app.schemas.regulations import (
    RegulationContentOut,
    RegulationContentUpdate,
    RegulationPageCreate,
    RegulationPageListItem,
    RegulationPageOut,
    RegulationPageUpdate,
)

router = APIRouter(tags=["Regulations"])

# Simple in-memory cache
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 120


def _invalidate_cache() -> None:
    _cache.clear()


# ─── Public endpoints ─────────────────────────────────────────────────────────


@router.get("/regulations", response_model=list[RegulationPageListItem])
async def list_regulations(
    lang: str = Query("en"),
    db: AsyncSession = Depends(get_db),
):
    """List all regulation pages with title in requested language."""
    cache_key = f"list:{lang}"
    now = time.time()
    if cache_key in _cache and (now - _cache[cache_key][0]) < _CACHE_TTL:
        return _cache[cache_key][1]

    result = await db.execute(
        select(RegulationPage).order_by(RegulationPage.sort_order, RegulationPage.slug)
    )
    pages = result.scalars().all()

    items = []
    for page in pages:
        title = page.slug  # fallback
        for c in page.contents:
            if c.lang == lang:
                title = c.title
                break
        else:
            # fallback to any available content
            if page.contents:
                title = page.contents[0].title
        items.append(
            RegulationPageListItem(
                id=str(page.id),
                slug=page.slug,
                sort_order=page.sort_order,
                title=title,
            )
        )

    _cache[cache_key] = (now, items)
    return items


@router.get("/regulations/{slug}", response_model=RegulationContentOut)
async def get_regulation(
    slug: str,
    lang: str = Query("en"),
    db: AsyncSession = Depends(get_db),
):
    """Get regulation content for a specific page and language."""
    cache_key = f"page:{slug}:{lang}"
    now = time.time()
    if cache_key in _cache and (now - _cache[cache_key][0]) < _CACHE_TTL:
        return _cache[cache_key][1]

    result = await db.execute(
        select(RegulationPage).where(RegulationPage.slug == slug)
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Regulation page not found.")

    content = None
    fallback = None
    for c in page.contents:
        if c.lang == lang:
            content = c
            break
        if fallback is None:
            fallback = c

    if content is None:
        content = fallback
    if content is None:
        raise HTTPException(status_code=404, detail="No content available for this page.")

    out = RegulationContentOut(
        lang=content.lang,
        title=content.title,
        subtitle=content.subtitle,
        content=content.content,
    )
    _cache[cache_key] = (now, out)
    return out


# ─── Admin endpoints ──────────────────────────────────────────────────────────


@router.get("/admin/regulations", response_model=list[RegulationPageOut])
async def admin_list_regulations(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(RegulationPage).order_by(RegulationPage.sort_order, RegulationPage.slug)
    )
    pages = result.scalars().all()

    return [
        RegulationPageOut(
            id=str(p.id),
            slug=p.slug,
            sort_order=p.sort_order,
            contents={
                c.lang: RegulationContentOut(
                    lang=c.lang, title=c.title, subtitle=c.subtitle, content=c.content
                )
                for c in p.contents
            },
        )
        for p in pages
    ]


@router.post("/admin/regulations", response_model=RegulationPageOut, status_code=status.HTTP_201_CREATED)
async def create_regulation(
    body: RegulationPageCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    # Check slug uniqueness
    existing = await db.execute(
        select(RegulationPage).where(RegulationPage.slug == body.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Slug already exists.")

    page = RegulationPage(slug=body.slug, sort_order=body.sort_order)
    for lang, content_data in body.contents.items():
        page.contents.append(
            RegulationContent(
                lang=lang,
                title=content_data.title,
                subtitle=content_data.subtitle,
                content=content_data.content,
            )
        )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    _invalidate_cache()

    return RegulationPageOut(
        id=str(page.id),
        slug=page.slug,
        sort_order=page.sort_order,
        contents={
            c.lang: RegulationContentOut(
                lang=c.lang, title=c.title, subtitle=c.subtitle, content=c.content
            )
            for c in page.contents
        },
    )


@router.put("/admin/regulations/{slug}", response_model=RegulationPageOut)
async def update_regulation(
    slug: str,
    body: RegulationPageUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(RegulationPage).where(RegulationPage.slug == slug)
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Regulation page not found.")

    if body.slug is not None and body.slug != page.slug:
        dup = await db.execute(
            select(RegulationPage).where(RegulationPage.slug == body.slug)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Slug already exists.")
        page.slug = body.slug

    if body.sort_order is not None:
        page.sort_order = body.sort_order

    if body.contents is not None:
        existing_contents = {c.lang: c for c in page.contents}
        for lang, content_data in body.contents.items():
            if lang in existing_contents:
                c = existing_contents[lang]
                c.title = content_data.title
                c.subtitle = content_data.subtitle
                c.content = content_data.content
            else:
                page.contents.append(
                    RegulationContent(
                        lang=lang,
                        title=content_data.title,
                        subtitle=content_data.subtitle,
                        content=content_data.content,
                    )
                )

    await db.commit()
    await db.refresh(page)
    _invalidate_cache()

    return RegulationPageOut(
        id=str(page.id),
        slug=page.slug,
        sort_order=page.sort_order,
        contents={
            c.lang: RegulationContentOut(
                lang=c.lang, title=c.title, subtitle=c.subtitle, content=c.content
            )
            for c in page.contents
        },
    )


@router.delete("/admin/regulations/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_regulation(
    slug: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(RegulationPage).where(RegulationPage.slug == slug)
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Regulation page not found.")

    await db.delete(page)
    await db.commit()
    _invalidate_cache()

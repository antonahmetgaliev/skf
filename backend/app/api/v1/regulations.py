"""Regulations: localized public views and the admin ``regulation-pages`` resource."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.params import PageId
from app.auth import require_admin
from app.core.openapi import problem_responses
from app.database import get_db
from app.schemas.regulations import (
    RegulationContentOut,
    RegulationPageCreate,
    RegulationPageOut,
    RegulationPageSummaryOut,
    RegulationPageUpdate,
)
from app.schemas.translations import LANGUAGE_CODE_MAX_LENGTH, LANGUAGE_CODE_PATTERN
from app.services import regulations as service

router = APIRouter(tags=["Regulations"])

_lang_query = Query("en", max_length=LANGUAGE_CODE_MAX_LENGTH, pattern=LANGUAGE_CODE_PATTERN)


# ── Public ───────────────────────────────────────────────────────────────────


@router.get("/regulations", response_model=list[RegulationPageSummaryOut])
async def list_regulations(lang: str = _lang_query, db: AsyncSession = Depends(get_db)):
    """Visible pages with their title in *lang* (falling back to any language)."""
    return await service.list_public(db, lang)


@router.get("/regulations/{slug}", response_model=RegulationContentOut)
async def get_regulation(slug: str, lang: str = _lang_query, db: AsyncSession = Depends(get_db)):
    return await service.get_public(db, slug, lang)


# ── Admin ────────────────────────────────────────────────────────────────────

admin = APIRouter(prefix="/regulation-pages", dependencies=[Depends(require_admin)])


@admin.get("", response_model=list[RegulationPageOut])
async def list_regulation_pages(db: AsyncSession = Depends(get_db)):
    return await service.list_all(db)


@admin.post(
    "",
    response_model=RegulationPageOut,
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(409),
)
async def create_regulation_page(
    body: RegulationPageCreate, response: Response, db: AsyncSession = Depends(get_db)
):
    page = await service.create(db, body)
    response.headers["Location"] = f"/api/v1/regulation-pages/{page.id}"
    return page


@admin.get("/{pageId}", response_model=RegulationPageOut)
async def get_regulation_page(page_id: PageId, db: AsyncSession = Depends(get_db)):
    return await service.get(db, page_id)


@admin.patch("/{pageId}", response_model=RegulationPageOut, responses=problem_responses(409))
async def update_regulation_page(
    page_id: PageId, body: RegulationPageUpdate, db: AsyncSession = Depends(get_db)
):
    return await service.update(db, page_id, body)


@admin.delete("/{pageId}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_regulation_page(page_id: PageId, db: AsyncSession = Depends(get_db)):
    await service.delete(db, page_id)


router.include_router(admin)

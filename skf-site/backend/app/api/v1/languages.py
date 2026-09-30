"""Languages and their translation bundles (flat ``{key: value}`` maps)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Body, Depends, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_optional, is_admin, require_admin
from app.database import get_db
from app.models.user import User
from app.schemas.translations import LanguageCreate, LanguageOut
from app.services import translations as service

router = APIRouter(prefix="/languages", tags=["Languages"])


@router.get("", response_model=list[LanguageOut])
async def list_languages(
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Active languages; admins also see inactive ones."""
    return await service.list_languages(db, include_inactive=is_admin(user))


@router.post(
    "",
    response_model=LanguageOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def add_language(body: LanguageCreate, response: Response, db: AsyncSession = Depends(get_db)):
    language = await service.add_language(db, body)
    response.headers["Location"] = f"/api/v1/languages/{language.code}"
    return language


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_language(code: str, db: AsyncSession = Depends(get_db)):
    """Delete a language together with its translations and regulation texts."""
    await service.delete_language(db, code)


@router.get("/{code}/translations", response_model=dict[str, str])
async def get_translations(
    code: str,
    prefix: str | None = Query(None),
    download: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """The flat bundle Transloco loads; ``?download=true`` serves it as a file."""
    bundle = await service.get_bundle(db, code, prefix)
    if download:
        safe_code = re.sub(r"[^A-Za-z0-9_-]", "", code)
        return JSONResponse(
            bundle,
            headers={"Content-Disposition": f'attachment; filename="translations_{safe_code}.json"'},
        )
    return bundle


@router.patch(
    "/{code}/translations",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def merge_translations(
    code: str,
    entries: dict[str, str] = Body(..., description="Keys to add or overwrite."),
    db: AsyncSession = Depends(get_db),
):
    """Merge a flat ``{key: value}`` map into the language (upsert)."""
    await service.merge(db, code, entries)


@router.delete(
    "/{code}/translations/{key:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def delete_translation(code: str, key: str, db: AsyncSession = Depends(get_db)):
    await service.delete_key(db, code, key)

"""Languages and their translation bundles (flat ``{key: value}`` maps)."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Path, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ensure_admin, get_current_user_optional, is_admin, require_admin
from app.core.openapi import problem_responses
from app.database import get_db
from app.models.user import User
from app.schemas.translations import (
    LANGUAGE_CODE_MAX_LENGTH,
    LANGUAGE_CODE_PATTERN,
    LanguageCreate,
    LanguageOut,
)
from app.services import translations as service

router = APIRouter(prefix="/languages", tags=["Languages"])

LanguageCode = Annotated[str, Path(max_length=LANGUAGE_CODE_MAX_LENGTH, pattern=LANGUAGE_CODE_PATTERN)]


@router.get("", response_model=list[LanguageOut], responses=problem_responses(401, 403))
async def list_languages(
    include: Literal["inactive"] | None = Query(
        None, description="`inactive` adds the languages not offered on the site; admins only."
    ),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """The languages the site is offered in."""
    if include is not None:
        ensure_admin(user)
    return await service.list_languages(db, include_inactive=include is not None)


@router.post(
    "",
    response_model=LanguageOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    responses=problem_responses(409),
)
async def create_language(body: LanguageCreate, response: Response, db: AsyncSession = Depends(get_db)):
    language = await service.add_language(db, body)
    response.headers["Location"] = f"/api/v1/languages/{language.code}"
    return language


@router.get("/{code}", response_model=LanguageOut)
async def get_language(
    code: LanguageCode,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """A language offered on the site; one that is not, only for admins."""
    return await service.get_language(db, code, include_inactive=is_admin(user))


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_language(code: LanguageCode, db: AsyncSession = Depends(get_db)):
    """Delete a language together with its translations and regulation texts."""
    await service.delete_language(db, code)


@router.get("/{code}/translations", response_model=dict[str, str])
async def get_translations(
    code: LanguageCode,
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
    responses=problem_responses(413),
)
async def merge_translations(
    code: LanguageCode,
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
async def delete_translation(code: LanguageCode, key: str, db: AsyncSession = Depends(get_db)):
    await service.delete_key(db, code, key)

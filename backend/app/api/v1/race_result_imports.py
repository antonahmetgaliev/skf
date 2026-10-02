"""Race result imports: one uploaded game-server file per SimGrid round.

Each file (LMU `.xml` or iRaceControl `.bin` for iRacing) feeds both the
giveaway and the round's "Auto" incidents. The simulator, and so the expected
file type, follows from the championship's SimGrid game.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.core.pagination import PageParams, page_params, paginate
from app.database import get_db
from app.models.race_result import RaceResultImport
from app.models.user import User
from app.repository import get_or_404
from app.schemas.race_results import ImportOut, ImportResultOut
from app.services import race_import as service

router = APIRouter(prefix="/race-result-imports", tags=["Race results"])

_NOT_FOUND = "Import not found"


def _location(import_id: uuid.UUID) -> str:
    return f"/api/v1/race-result-imports/{import_id}"


async def _get(db: AsyncSession, import_id: uuid.UUID) -> RaceResultImport:
    return await get_or_404(db, RaceResultImport, import_id, detail=_NOT_FOUND)


@router.get("", response_model=list[ImportOut])
async def list_imports(
    request: Request,
    response: Response,
    championship_id: int | None = Query(None, alias="championshipId"),
    page: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    records = await paginate(db, service.imports_query(championship_id), page, request, response)
    return await service.list_out(db, records)


@router.post("", response_model=ImportResultOut, status_code=status.HTTP_201_CREATED)
async def create_import(
    response: Response,
    file: UploadFile = File(...),
    championship_id: int = Form(..., alias="championshipId"),
    race_id: int = Form(..., alias="raceId"),
    create_incidents: bool = Form(True, alias="createIncidents"),
    window_hours: int = Form(24, alias="windowHours", ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Import one round's result file, replacing any earlier upload of it."""
    payload = await service.read_upload(file)
    result = await service.upload(
        db,
        payload=payload,
        filename=file.filename,
        championship_id=championship_id,
        race_id=race_id,
        user_id=user.id,
        create_incidents=create_incidents,
        window_hours=window_hours,
    )
    response.headers["Location"] = _location(result.record.id)
    return service.result_out(result)


@router.get("/{import_id}", response_model=ImportOut)
async def get_import(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    return (await service.list_out(db, [await _get(db, import_id)]))[0]


@router.get("/{import_id}/file", response_class=Response)
async def download_import_file(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    payload, filename = await service.stored_file(await _get(db, import_id))
    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/{import_id}/parse-runs",
    response_model=ImportResultOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_parse_run(
    import_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Re-run the parser on the stored original, e.g. after a parser fix.

    A parse run replaces the import with a new one (new id), so this answers
    201 with the replacement's ``Location``.
    """
    result = await service.reparse(db, await _get(db, import_id), user.id)
    response.headers["Location"] = _location(result.record.id)
    return service.result_out(result)


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_import(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Remove the round's results. Its incidents stay with the window."""
    await service.delete_import(db, await _get(db, import_id))

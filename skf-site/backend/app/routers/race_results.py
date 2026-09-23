"""Race results router - admin upload of each round's game-server result file.

One file per SimGrid round (LMU `.xml` or iRaceControl `.bin` for iRacing)
feeds both the giveaway and the round's "Auto" incidents. The simulator, and
so the expected file type, follows from the championship's SimGrid game.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.incidents import Incident, IncidentWindow
from app.models.race_result import RaceResultImport
from app.models.user import User
from app.schemas.giveaway import ImportEntryOut
from app.schemas.race_results import (
    ImportResultOut,
    RaceImportOut,
    RoundOut,
    RoundsOut,
    RoundWindowOut,
)
from app.services import file_storage
from app.services.race_files import (
    FILE_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    RaceFileError,
    Sim,
    sim_for_game,
)
from app.services.race_import import ImportResult, import_race_file
from app.services.simgrid import simgrid_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/race-results", tags=["Race results"])


async def _championship(championship_id: int) -> tuple[str, str, Sim | None]:
    """(name, game name, simulator) of a SimGrid championship."""
    try:
        details = await simgrid_service.get_championship(championship_id)
    except Exception as exc:  # noqa: BLE001 - SimGrid down or unknown id
        logger.exception("Failed to load championship %s", championship_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Could not load the championship from SimGrid"
        ) from exc
    return details.name, details.game_name, sim_for_game(details.game_name)


def _import_out(record: RaceResultImport, entry_count: int, unmatched: int) -> RaceImportOut:
    return RaceImportOut(
        id=record.id,
        sim=record.sim,
        track_event=record.track_event,
        session_started_at=record.session_started_at,
        source_filename=record.source_filename,
        file_size=record.file_size,
        has_file=record.storage_key is not None,
        entry_count=entry_count,
        unmatched_count=unmatched,
        contacts_count=record.contacts_count,
        auto_grouped=record.auto_grouped,
        created_at=record.created_at,
    )


def _result_out(result: ImportResult) -> ImportResultOut:
    entries = result.entries
    return ImportResultOut(
        race_import=_import_out(
            result.record, len(entries), sum(1 for e in entries if e.driver_id is None)
        ),
        window_id=result.window.id if result.window else None,
        incidents_created=result.incidents_created,
        incidents_kept=result.incidents_kept,
        entries=[
            ImportEntryOut(
                raw_name=e.raw_name,
                car_class=e.car_class,
                laps=e.laps,
                position=e.position,
                finish_status=e.finish_status,
                matched=e.driver_id is not None,
            )
            for e in entries
        ],
    )


async def _get_import_or_404(db: AsyncSession, import_id: uuid.UUID) -> RaceResultImport:
    record = await db.get(RaceResultImport, import_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    return record


@router.get("/rounds", response_model=RoundsOut)
async def list_rounds(
    championship_simgrid_id: int = Query(..., alias="championshipSimgridId"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """The championship's rounds with their upload and incident window."""
    name, game_name, sim = await _championship(championship_simgrid_id)
    try:
        races = await simgrid_service.get_races(championship_simgrid_id)
    except Exception:  # noqa: BLE001 - a missing round list must not break the page
        logger.exception("Failed to load rounds for championship %s", championship_simgrid_id)
        races = []
    races = sorted(
        (r for r in races if isinstance(r, dict) and r.get("id") is not None),
        key=lambda r: r.get("starts_at") or "",
    )

    imports = {
        r.race_simgrid_id: r
        for r in (
            await db.execute(
                select(RaceResultImport).where(
                    RaceResultImport.championship_simgrid_id == championship_simgrid_id
                )
            )
        ).scalars()
    }
    race_ids = [race["id"] for race in races]
    windows = {
        w.race_id: w
        for w in (
            await db.execute(select(IncidentWindow).where(IncidentWindow.race_id.in_(race_ids)))
        ).scalars()
    } if race_ids else {}
    counts = dict(
        (
            await db.execute(
                select(Incident.window_id, func.count(Incident.id))
                .where(Incident.window_id.in_([w.id for w in windows.values()]))
                .group_by(Incident.window_id)
            )
        ).all()
    ) if windows else {}

    rounds: list[RoundOut] = []
    for race in races:
        record = imports.get(race["id"])
        window = windows.get(race["id"])
        rounds.append(
            RoundOut(
                race_id=race["id"],
                name=race.get("display_name") or race.get("race_name") or "",
                starts_at=race.get("starts_at"),
                ended=race.get("ended", False),
                race_import=(
                    _import_out(
                        record,
                        len(record.entries),
                        sum(1 for e in record.entries if e.driver_id is None),
                    )
                    if record
                    else None
                ),
                window=(
                    RoundWindowOut(
                        id=window.id,
                        is_open=window.is_open,
                        closes_at=window.closes_at,
                        incidents_count=counts.get(window.id, 0),
                    )
                    if window
                    else None
                ),
            )
        )

    return RoundsOut(
        championship_id=championship_simgrid_id,
        championship_name=name,
        game_name=game_name,
        sim=sim,
        storage_enabled=file_storage.is_enabled(),
        rounds=rounds,
    )


@router.post("/imports", response_model=ImportResultOut, status_code=status.HTTP_201_CREATED)
async def create_import(
    file: UploadFile = File(...),
    championship_simgrid_id: int = Form(..., alias="championshipSimgridId"),
    race_simgrid_id: int = Form(..., alias="raceSimgridId"),
    create_incidents: bool = Form(True, alias="createIncidents"),
    window_hours: int = Form(24, alias="windowHours", ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Import one round's result file, replacing any earlier upload of it."""
    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large")

    name, game_name, sim = await _championship(championship_simgrid_id)
    if sim is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Result files are not supported for {game_name or 'this game'}",
        )

    try:
        result = await import_race_file(
            db,
            payload=payload,
            filename=file.filename,
            sim=sim,
            championship_id=championship_simgrid_id,
            championship_name=name,
            race_id=race_simgrid_id,
            user_id=user.id,
            create_incidents=create_incidents,
            window_hours=window_hours,
        )
    except RaceFileError as exc:
        expected = FILE_EXTENSIONS[sim]
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{exc}. {game_name} expects a .{expected} file."
        ) from exc
    return _result_out(result)


@router.post("/imports/{import_id}/reparse", response_model=ImportResultOut)
async def reparse_import(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Re-run the parser on the stored original, e.g. after a parser fix."""
    record = await _get_import_or_404(db, import_id)
    if record.storage_key is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The original file was not kept")
    payload = await _read_stored(record.storage_key)
    name, _, _ = await _championship(record.championship_simgrid_id)

    try:
        result = await import_race_file(
            db,
            payload=payload,
            filename=record.source_filename,
            sim=record.sim,
            championship_id=record.championship_simgrid_id,
            championship_name=name,
            race_id=record.race_simgrid_id,
            user_id=user.id,
        )
    except RaceFileError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _result_out(result)


@router.get("/imports/{import_id}/file")
async def download_import_file(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    record = await _get_import_or_404(db, import_id)
    if record.storage_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The original file was not kept")
    payload = await _read_stored(record.storage_key)
    filename = record.source_filename or f"{record.id}.{FILE_EXTENSIONS.get(record.sim, 'bin')}"
    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"'},
    )


@router.delete("/imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_import(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Remove the round's results. Its incidents stay with the window."""
    record = await _get_import_or_404(db, import_id)
    storage_key = record.storage_key
    await db.execute(
        Incident.__table__.update().where(Incident.import_id == record.id).values(import_id=None)
    )
    await db.delete(record)
    await db.commit()
    if storage_key:
        try:
            await file_storage.delete(storage_key)
        except Exception:  # noqa: BLE001 - an orphaned object is harmless
            logger.exception("Could not delete race file %s", storage_key)


async def _read_stored(key: str) -> bytes:
    try:
        return await file_storage.get(key)
    except file_storage.StorageUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - bucket errors
        logger.exception("Could not read race file %s", key)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not read the stored file") from exc


def _safe_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "._- ") or "race-results"

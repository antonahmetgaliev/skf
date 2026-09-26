"""Import one round's result file: giveaway entries plus Auto incidents.

Shared by the admin upload, the re-parse of a stored file, and the legacy
`/incidents/ingest` endpoint (window lookup and incident creation only).
Also assembles the per-championship round overview the admin uploads from.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from fastapi import UploadFile
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    BadGateway,
    BadRequest,
    Conflict,
    NotFound,
    PayloadTooLarge,
    ServiceUnavailable,
    Unprocessable,
)

from app.models.incidents import Incident, IncidentDriver, IncidentWindow
from app.models.race_result import (
    GiveawayNameAlias,
    RaceResultEntry,
    RaceResultImport,
    normalize_driver_name,
)
from app.schemas.race_results import (
    ImportEntryOut,
    ImportOut,
    ImportResultOut,
    RaceImportOut,
    RoundOut,
    RoundsOut,
    RoundWindowOut,
)
from app.services import file_storage
from app.services.driver_matching import match_driver_id_by_name
from app.services.race_files import (
    FILE_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    ParsedContact,
    ParsedRaceFile,
    RaceFileError,
    Sim,
    parse_race_file,
    sim_for_game,
)
from app.services.simgrid import simgrid_service

logger = logging.getLogger(__name__)

_CONTENT_TYPES: dict[Sim, str] = {
    "lmu": "application/xml",
    "iracing": "application/octet-stream",
}


@dataclass(frozen=True)
class IncidentLike:
    """Anything with the fields an ingested incident is created from."""

    session_name: str | None
    time: str | None
    drivers: list[str]
    lap: str | None = None


@dataclass
class ImportResult:
    record: RaceResultImport
    entries: list[RaceResultEntry]
    window: IncidentWindow | None
    incidents_created: int
    incidents_kept: int


async def entry_counts(
    db: AsyncSession, import_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """``{import_id: (entries, unmatched entries)}`` counted in SQL."""
    ids = list(import_ids)
    if not ids:
        return {}
    rows = await db.execute(
        select(
            RaceResultEntry.import_id,
            func.count(RaceResultEntry.id),
            func.sum(case((RaceResultEntry.driver_id.is_(None), 1), else_=0)),
        )
        .where(RaceResultEntry.import_id.in_(ids))
        .group_by(RaceResultEntry.import_id)
    )
    return {import_id: (total, unmatched or 0) for import_id, total, unmatched in rows.all()}


async def alias_map(db: AsyncSession) -> dict[str, tuple[str, str]]:
    """normalized alias -> (canonical normalized name, canonical display name)."""
    result = await db.execute(
        select(
            GiveawayNameAlias.normalized_alias,
            GiveawayNameAlias.canonical_normalized_name,
            GiveawayNameAlias.canonical_display_name,
        )
    )
    return {row[0]: (row[1], row[2]) for row in result.all()}


async def championship_name_for(championship_id: int) -> str | None:
    """The SimGrid championship's name (day-cached), or None if unavailable."""
    try:
        return (await simgrid_service.get_championship(championship_id)).name
    except Exception:  # noqa: BLE001 - a missing name must not block incidents
        logger.warning(
            "Could not load championship %s from SimGrid", championship_id, exc_info=True
        )
        return None


async def backfill_window_championship_names(db: AsyncSession) -> int:
    """Fill in championship names on windows that only have the id.

    Windows sent by the legacy ingest API before the name was stored carry the
    championship id only; the incidents page groups rounds by name. Returns the
    number of windows updated.
    """
    windows = (
        await db.execute(
            select(IncidentWindow).where(
                IncidentWindow.championship_id.is_not(None),
                IncidentWindow.championship_name.is_(None),
            )
        )
    ).scalars().all()
    names: dict[int, str | None] = {}
    updated = 0
    for window in windows:
        cid = window.championship_id
        if cid not in names:
            names[cid] = await championship_name_for(cid)
        if names[cid]:
            window.championship_name = names[cid]
            updated += 1
    if updated:
        await db.commit()
    return updated


async def find_or_create_window(
    db: AsyncSession,
    *,
    race_id: int,
    championship_id: int | None,
    interval_hours: int = 24,
    championship_name: str | None = None,
    race_name: str | None = None,
    race_date: date | None = None,
) -> IncidentWindow:
    """The round's incident window, opened now if it does not exist yet."""
    result = await db.execute(select(IncidentWindow).where(IncidentWindow.race_id == race_id))
    window = result.scalar_one_or_none()
    if window is not None:
        # Windows opened by hand may lack the championship; the upload knows it.
        if window.championship_id is None and championship_id is not None:
            window.championship_id = championship_id
        if window.championship_name is None and window.championship_id is not None:
            window.championship_name = championship_name or await championship_name_for(
                window.championship_id
            )
        return window

    if championship_name is None and championship_id is not None:
        championship_name = await championship_name_for(championship_id)
    now = datetime.now(timezone.utc)
    window = IncidentWindow(
        championship_id=championship_id,
        championship_name=championship_name,
        race_id=race_id,
        race_name=race_name or await simgrid_service.get_race_name(race_id),
        date=(race_date or now.date()).isoformat(),
        interval_hours=interval_hours,
        opened_at=now,
        closes_at=now + timedelta(hours=interval_hours),
    )
    db.add(window)
    await db.flush()
    return window


async def add_ingested_incidents(
    db: AsyncSession,
    window: IncidentWindow,
    incidents: Iterable[IncidentLike | ParsedContact],
    import_id: uuid.UUID | None = None,
) -> int:
    count = 0
    for item in incidents:
        incident = Incident(
            window_id=window.id,
            session_name=item.session_name,
            time=item.time,
            lap=getattr(item, "lap", None),
            source="ingested",
            is_published=False,
            import_id=import_id,
        )
        db.add(incident)
        await db.flush()
        for idx, driver_name in enumerate(item.drivers):
            db.add(
                IncidentDriver(
                    incident_id=incident.id,
                    driver_name=driver_name.strip(),
                    driver_id=await match_driver_id_by_name(db, driver_name),
                    sort_order=idx,
                )
            )
        count += 1
    return count


def _signature(time: str | None, drivers: Iterable[str]) -> tuple:
    return (time or "", frozenset(normalize_driver_name(d) for d in drivers))


def _is_touched(incident: Incident) -> bool:
    """A steward has worked on it, so a re-upload must not throw it away."""
    return incident.is_published or any(d.resolution is not None for d in incident.drivers)


async def _detach_round_incidents(
    db: AsyncSession, window: IncidentWindow, old_import_ids: list[uuid.UUID]
) -> tuple[list[Incident], set[tuple]]:
    """Clear the way for a new upload's Auto incidents.

    Untouched incidents from an earlier upload are deleted. Ones a steward has
    resolved or published stay and are returned, detached from the old import
    so it can be deleted, to be re-pointed at the new one. The returned
    signatures (time + cars) also cover incidents that arrived through the
    legacy ingest API, so a new contact matching any of them is skipped.
    """
    await db.refresh(window, attribute_names=["incidents"])
    kept: list[Incident] = []
    signatures: set[tuple] = set()
    for incident in list(window.incidents):
        if incident.source != "ingested":
            continue
        from_old_upload = incident.import_id in old_import_ids
        if from_old_upload and not _is_touched(incident):
            await db.delete(incident)
            continue
        if from_old_upload or incident.import_id is None:
            signatures.add(_signature(incident.time, (d.driver_name for d in incident.drivers)))
        if from_old_upload:
            incident.import_id = None
            kept.append(incident)
    await db.flush()
    return kept, signatures


async def import_race_file(
    db: AsyncSession,
    *,
    payload: bytes,
    filename: str | None,
    sim: Sim,
    championship_id: int,
    championship_name: str | None,
    race_id: int,
    user_id: uuid.UUID | None,
    create_incidents: bool = True,
    window_hours: int = 24,
    parsed: ParsedRaceFile | None = None,
) -> ImportResult:
    """Parse and store a round's file, replacing any earlier upload of it.

    Raises `RaceFileError` for an unusable file. Commits on success.
    """
    parsed = parsed or parse_race_file(payload, sim)

    existing = await db.execute(
        select(RaceResultImport).where(
            RaceResultImport.championship_simgrid_id == championship_id,
            RaceResultImport.race_simgrid_id == race_id,
        )
    )
    old_imports = list(existing.scalars().all())
    old_ids = [r.id for r in old_imports]
    old_keys = [r.storage_key for r in old_imports if r.storage_key]

    record = RaceResultImport(
        id=uuid.uuid4(),
        championship_simgrid_id=championship_id,
        race_simgrid_id=race_id,
        track_event=parsed.track_event,
        session_started_at=parsed.session_started_at,
        source_filename=filename,
        sim=sim,
        file_size=len(payload),
        contacts_count=len(parsed.contacts),
        external_session_id=parsed.external_session_id,
        auto_grouped=parsed.auto_grouped,
        uploaded_by_user_id=user_id,
    )
    storage_key = (
        f"race-results/{championship_id}/{race_id}/{record.id}.{FILE_EXTENSIONS[sim]}"
    )

    window: IncidentWindow | None = None
    kept: list[Incident] = []
    signatures: set[tuple] = set()
    if create_incidents:
        window = await find_or_create_window(
            db,
            race_id=race_id,
            championship_id=championship_id,
            interval_hours=window_hours,
            championship_name=championship_name,
            race_date=parsed.session_started_at.date() if parsed.session_started_at else None,
        )
        kept, signatures = await _detach_round_incidents(db, window, old_ids)

    # One import per round: the old rows go before the new one is inserted.
    for old_id in old_ids:
        await db.execute(delete(RaceResultImport).where(RaceResultImport.id == old_id))
    db.add(record)
    await db.flush()

    aliases = await alias_map(db)
    entries: list[RaceResultEntry] = []
    for parsed_entry in parsed.entries:
        normalized = normalize_driver_name(parsed_entry.raw_name)
        canonical = aliases.get(normalized, (normalized, parsed_entry.raw_name))[0]
        # Match on the canonical spelling so a previously merged name links to
        # the same driver record as the spelling it was merged into.
        driver_id = await match_driver_id_by_name(db, canonical)
        if driver_id is None and canonical != normalized:
            driver_id = await match_driver_id_by_name(db, parsed_entry.raw_name)
        entries.append(
            RaceResultEntry(
                import_id=record.id,
                raw_name=parsed_entry.raw_name,
                normalized_name=normalized,
                car_class=parsed_entry.car_class,
                laps=parsed_entry.laps,
                position=parsed_entry.position,
                class_position=parsed_entry.class_position,
                finish_status=parsed_entry.finish_status,
                driver_id=driver_id,
            )
        )
    db.add_all(entries)

    created = 0
    if window is not None:
        for incident in kept:
            incident.import_id = record.id
        fresh = [c for c in parsed.contacts if _signature(c.time, c.drivers) not in signatures]
        created = await add_ingested_incidents(db, window, fresh, import_id=record.id)

    # Upload last, so a bucket outage leaves the database untouched.
    if await file_storage.put(storage_key, payload, _CONTENT_TYPES[sim]):
        record.storage_key = storage_key

    await db.commit()

    for key in old_keys:
        if key == record.storage_key:
            continue
        try:
            await file_storage.delete(key)
        except Exception:  # noqa: BLE001 - an orphaned object is harmless
            logger.exception("Could not delete replaced race file %s", key)

    return ImportResult(
        record=record,
        entries=entries,
        window=window,
        incidents_created=created,
        incidents_kept=len(kept),
    )


# ── Admin upload API ────────────────────────────────────────────────────────

_READ_CHUNK = 1024 * 1024


async def read_upload(file: UploadFile, limit: int | None = None) -> bytes:
    """The upload's bytes, refusing anything over *limit* without reading it all.

    The declared size is checked first; the body is then read in chunks so a
    file whose size was not declared still stops at the cap.
    """
    limit = MAX_UPLOAD_BYTES if limit is None else limit
    if file.size is not None and file.size > limit:
        raise PayloadTooLarge("File is too large")
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_READ_CHUNK):
        total += len(chunk)
        if total > limit:
            raise PayloadTooLarge("File is too large")
        chunks.append(chunk)
    return b"".join(chunks)


async def championship_info(championship_id: int) -> tuple[str, str, Sim | None]:
    """(name, game name, simulator) of a SimGrid championship."""
    try:
        details = await simgrid_service.get_championship(championship_id)
    except Exception as exc:  # noqa: BLE001 - SimGrid down or unknown id
        logger.warning("Failed to load championship %s", championship_id, exc_info=True)
        raise BadGateway("Could not load the championship from SimGrid") from exc
    return details.name, details.game_name, sim_for_game(details.game_name)


def import_out(record: RaceResultImport, entry_count: int, unmatched: int) -> RaceImportOut:
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


def result_out(result: ImportResult) -> ImportResultOut:
    entries = result.entries
    return ImportResultOut(
        race_import=import_out(
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


def imports_query(championship_id: int | None = None):
    """Uploads in round order, optionally for one championship."""
    stmt = select(RaceResultImport).order_by(
        RaceResultImport.session_started_at, RaceResultImport.created_at
    )
    if championship_id is not None:
        stmt = stmt.where(RaceResultImport.championship_simgrid_id == championship_id)
    return stmt


async def list_out(db: AsyncSession, records: list[RaceResultImport]) -> list[ImportOut]:
    counts = await entry_counts(db, (r.id for r in records))
    return [
        ImportOut(
            id=record.id,
            championship_simgrid_id=record.championship_simgrid_id,
            race_simgrid_id=record.race_simgrid_id,
            track_event=record.track_event,
            session_started_at=record.session_started_at,
            source_filename=record.source_filename,
            sim=record.sim,
            created_at=record.created_at,
            entry_count=counts.get(record.id, (0, 0))[0],
            unmatched_count=counts.get(record.id, (0, 0))[1],
        )
        for record in records
    ]


async def upload(
    db: AsyncSession,
    *,
    payload: bytes,
    filename: str | None,
    championship_id: int,
    race_id: int,
    user_id: uuid.UUID,
    create_incidents: bool,
    window_hours: int,
) -> ImportResult:
    """Import an uploaded round file for a championship whose game decides the parser."""
    name, game_name, sim = await championship_info(championship_id)
    if sim is None:
        raise Unprocessable(f"Result files are not supported for {game_name or 'this game'}")
    try:
        return await import_race_file(
            db,
            payload=payload,
            filename=filename,
            sim=sim,
            championship_id=championship_id,
            championship_name=name,
            race_id=race_id,
            user_id=user_id,
            create_incidents=create_incidents,
            window_hours=window_hours,
        )
    except RaceFileError as exc:
        raise BadRequest(f"{exc}. {game_name} expects a .{FILE_EXTENSIONS[sim]} file.") from exc


async def reparse(db: AsyncSession, record: RaceResultImport, user_id: uuid.UUID) -> ImportResult:
    """Re-run the parser on the stored original, replacing the import."""
    if record.storage_key is None:
        raise Conflict("The original file was not kept")
    payload = await read_stored(record.storage_key)
    name, _, _ = await championship_info(record.championship_simgrid_id)
    try:
        return await import_race_file(
            db,
            payload=payload,
            filename=record.source_filename,
            sim=record.sim,
            championship_id=record.championship_simgrid_id,
            championship_name=name,
            race_id=record.race_simgrid_id,
            user_id=user_id,
        )
    except RaceFileError as exc:
        raise BadRequest(str(exc)) from exc


async def stored_file(record: RaceResultImport) -> tuple[bytes, str]:
    """The kept original and a download-safe filename for it."""
    if record.storage_key is None:
        raise NotFound("The original file was not kept")
    payload = await read_stored(record.storage_key)
    filename = record.source_filename or f"{record.id}.{FILE_EXTENSIONS.get(record.sim, 'bin')}"
    safe = "".join(c for c in filename if c.isalnum() or c in "._- ") or "race-results"
    return payload, safe


async def delete_import(db: AsyncSession, record: RaceResultImport) -> None:
    """Remove the round's results. Its incidents stay with the window."""
    storage_key = record.storage_key
    await db.execute(
        update(Incident).where(Incident.import_id == record.id).values(import_id=None)
    )
    await db.delete(record)
    await db.commit()
    if storage_key:
        try:
            await file_storage.delete(storage_key)
        except Exception:  # noqa: BLE001 - an orphaned object is harmless
            logger.exception("Could not delete race file %s", storage_key)


async def read_stored(key: str) -> bytes:
    try:
        return await file_storage.get(key)
    except file_storage.StorageUnavailable as exc:
        raise ServiceUnavailable("File storage is not available") from exc
    except Exception as exc:  # noqa: BLE001 - bucket errors
        logger.exception("Could not read race file %s", key)
        raise BadGateway("Could not read the stored file") from exc


async def build_rounds(db: AsyncSession, championship_id: int) -> RoundsOut:
    """The championship's rounds with their upload and incident window."""
    name, game_name, sim = await championship_info(championship_id)
    try:
        races = await simgrid_service.get_races(championship_id)
    except Exception:  # noqa: BLE001 - a missing round list must not break the page
        logger.exception("Failed to load rounds for championship %s", championship_id)
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
                    RaceResultImport.championship_simgrid_id == championship_id
                )
            )
        ).scalars()
    }
    entry_totals = await entry_counts(db, (r.id for r in imports.values()))
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
                    import_out(record, *entry_totals.get(record.id, (0, 0))) if record else None
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
        championship_id=championship_id,
        championship_name=name,
        game_name=game_name,
        sim=sim,
        storage_enabled=file_storage.is_enabled(),
        rounds=rounds,
    )

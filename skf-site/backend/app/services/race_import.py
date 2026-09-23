"""Import one round's result file: giveaway entries plus Auto incidents.

Shared by the admin upload, the re-parse of a stored file, and the legacy
`/incidents/ingest` endpoint (window lookup and incident creation only).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incidents import Incident, IncidentDriver, IncidentWindow
from app.models.race_result import (
    GiveawayNameAlias,
    RaceResultEntry,
    RaceResultImport,
    normalize_driver_name,
)
from app.services import file_storage
from app.services.driver_matching import match_driver_id_by_name
from app.services.race_files import (
    FILE_EXTENSIONS,
    ParsedContact,
    ParsedRaceFile,
    Sim,
    parse_race_file,
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
        logger.warning("Could not load championship %s from SimGrid", championship_id)
        return None


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
        date=(race_date or date.today()).isoformat(),
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

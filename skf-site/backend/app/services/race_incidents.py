"""Incident windows fed by race files: find or open the round's window, add Auto incidents."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incidents import Incident, IncidentDriver, IncidentWindow
from app.models.race_result import (
    normalize_driver_name,
)
from app.services.driver_matching import match_driver_id_by_name
from app.services.race_files import (
    ParsedContact,
)
from app.services.simgrid import simgrid_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IncidentLike:
    """Anything with the fields an ingested incident is created from."""

    session_name: str | None
    time: str | None
    drivers: list[str]
    lap: str | None = None


async def championship_name_for(championship_id: int) -> str | None:
    """The SimGrid championship's name (day-cached), or None if unavailable."""
    try:
        return (await simgrid_service.get_championship(championship_id)).name
    except Exception:  # noqa: BLE001 - a missing name must not block incidents
        logger.warning("Could not load championship %s from SimGrid", championship_id, exc_info=True)
        return None


async def backfill_window_championship_names(db: AsyncSession) -> int:
    """Fill in championship names on windows that only have the id.

    Windows sent by the legacy ingest API before the name was stored carry the
    championship id only; the incidents page groups rounds by name. Returns the
    number of windows updated.
    """
    windows = (
        (
            await db.execute(
                select(IncidentWindow).where(
                    IncidentWindow.championship_id.is_not(None),
                    IncidentWindow.championship_name.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
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
    now = datetime.now(UTC)
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


def signature(time: str | None, drivers: Iterable[str]) -> tuple:
    return (time or "", frozenset(normalize_driver_name(d) for d in drivers))


def is_touched(incident: Incident) -> bool:
    """A steward has worked on it, so a re-upload must not throw it away."""
    return incident.is_published or any(d.resolution is not None for d in incident.drivers)


async def detach_round_incidents(
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
        if from_old_upload and not is_touched(incident):
            await db.delete(incident)
            continue
        if from_old_upload or incident.import_id is None:
            signatures.add(signature(incident.time, (d.driver_name for d in incident.drivers)))
        if from_old_upload:
            incident.import_id = None
            kept.append(incident)
    await db.flush()
    return kept, signatures

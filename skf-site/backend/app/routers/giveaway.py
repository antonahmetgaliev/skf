"""Giveaway router - admin-only race-result import and eligibility.

Every figure the giveaway needs is read from imported game-server XML, so no
endpoint here calls SimGrid. That is deliberate: eligibility would otherwise
need one request per driver and SimGrid enforces a per-minute rate limit that
such a fan-out trips immediately. The round list comes from the existing
day-cached `simgrid_service.get_races`, which costs no extra request.
"""

from __future__ import annotations

import difflib
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.bwp import Driver
from app.models.race_result import (
    GiveawayNameAlias,
    RaceResultEntry,
    RaceResultImport,
    normalize_driver_name,
)
from app.models.user import User
from app.schemas.giveaway import (
    AliasCreate,
    AliasOut,
    EligibilityOut,
    EligibleDriverOut,
    ImportDetailOut,
    ImportEntryOut,
    ImportOut,
    RoundBreakdownOut,
    UnmatchedNameOut,
)
from app.services.driver_matching import match_driver_id_by_name
from app.services.giveaway import RoundEntry, compute_eligibility
from app.services.race_results_xml import (
    MAX_UPLOAD_BYTES,
    RaceResultsXmlError,
    parse_race_results,
)
from app.services.simgrid import simgrid_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/giveaway", tags=["Giveaway"])


async def _alias_map(db: AsyncSession) -> dict[str, tuple[str, str]]:
    """normalized alias -> (canonical normalized name, canonical display name)."""
    result = await db.execute(
        select(
            GiveawayNameAlias.normalized_alias,
            GiveawayNameAlias.canonical_normalized_name,
            GiveawayNameAlias.canonical_display_name,
        )
    )
    return {row[0]: (row[1], row[2]) for row in result.all()}


async def _load_imports(
    db: AsyncSession, championship_simgrid_id: int
) -> list[RaceResultImport]:
    result = await db.execute(
        select(RaceResultImport)
        .where(RaceResultImport.championship_simgrid_id == championship_simgrid_id)
        .order_by(RaceResultImport.session_started_at, RaceResultImport.created_at)
    )
    return list(result.scalars().all())


def _round_key(record: RaceResultImport) -> str:
    """Stable per-round identity used to group and sort rounds."""
    if record.race_simgrid_id is not None:
        return f"race:{record.race_simgrid_id}"
    return f"import:{record.id}"


@router.get("/imports", response_model=list[ImportOut])
async def list_imports(
    championship_simgrid_id: int = Query(..., alias="championshipSimgridId"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    records = await _load_imports(db, championship_simgrid_id)
    return [
        ImportOut(
            id=record.id,
            championship_simgrid_id=record.championship_simgrid_id,
            race_simgrid_id=record.race_simgrid_id,
            track_event=record.track_event,
            session_started_at=record.session_started_at,
            source_filename=record.source_filename,
            created_at=record.created_at,
            entry_count=len(record.entries),
            unmatched_count=sum(1 for e in record.entries if e.driver_id is None),
        )
        for record in records
    ]


@router.post(
    "/imports", response_model=ImportDetailOut, status_code=status.HTTP_201_CREATED
)
async def create_import(
    file: UploadFile = File(...),
    championship_simgrid_id: int = Form(..., alias="championshipSimgridId"),
    race_simgrid_id: int | None = Form(None, alias="raceSimgridId"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Import one round's results from a game-server XML file."""
    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large"
        )
    try:
        parsed = parse_race_results(payload)
    except RaceResultsXmlError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    # Re-importing a round replaces it, so a corrected file cannot leave the
    # championship counting the same round twice.
    if race_simgrid_id is not None:
        existing = await db.execute(
            select(RaceResultImport.id).where(
                RaceResultImport.championship_simgrid_id == championship_simgrid_id,
                RaceResultImport.race_simgrid_id == race_simgrid_id,
            )
        )
        for old_id in existing.scalars().all():
            await db.execute(
                delete(RaceResultImport).where(RaceResultImport.id == old_id)
            )

    record = RaceResultImport(
        championship_simgrid_id=championship_simgrid_id,
        race_simgrid_id=race_simgrid_id,
        track_event=parsed.track_event,
        session_started_at=parsed.session_started_at,
        source_filename=file.filename,
        uploaded_by_user_id=user.id,
    )
    db.add(record)
    await db.flush()

    aliases = await _alias_map(db)
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
    await db.commit()

    return ImportDetailOut(
        id=record.id,
        championship_simgrid_id=record.championship_simgrid_id,
        race_simgrid_id=record.race_simgrid_id,
        track_event=record.track_event,
        session_started_at=record.session_started_at,
        source_filename=record.source_filename,
        created_at=record.created_at,
        entry_count=len(entries),
        unmatched_count=sum(1 for e in entries if e.driver_id is None),
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


@router.delete("/imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_import(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    record = await db.get(RaceResultImport, import_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    await db.delete(record)
    await db.commit()


@router.get("/eligibility", response_model=EligibilityOut)
async def get_eligibility(
    championship_simgrid_id: int = Query(..., alias="championshipSimgridId"),
    min_distance_pct: float = Query(50.0, alias="minDistancePct", ge=0, le=100),
    min_rounds: int = Query(3, alias="minRounds", ge=1),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Drivers who cleared the distance bar in enough rounds, grouped by class."""
    records = await _load_imports(db, championship_simgrid_id)
    aliases = await _alias_map(db)
    labels = {_round_key(r): (r.track_event or r.source_filename or "") for r in records}

    rows: list[RoundEntry] = []
    for record in records:
        key = _round_key(record)
        for entry in record.entries:
            canonical, display = aliases.get(
                entry.normalized_name, (entry.normalized_name, entry.raw_name)
            )
            rows.append(
                RoundEntry(
                    round_key=key,
                    identity=canonical,
                    display_name=display,
                    car_class=entry.car_class,
                    laps=entry.laps,
                )
            )

    eligible = compute_eligibility(rows, min_distance_pct, min_rounds)
    return EligibilityOut(
        championship_simgrid_id=championship_simgrid_id,
        min_distance_pct=min_distance_pct,
        min_rounds=min_rounds,
        imported_rounds=len(records),
        car_classes=sorted({r.car_class for r in rows if r.car_class}),
        drivers=[
            EligibleDriverOut(
                identity=d.identity,
                display_name=d.display_name,
                car_class=d.car_class,
                qualifying_rounds=d.qualifying_rounds,
                rounds=[
                    RoundBreakdownOut(
                        round_key=r.round_key,
                        round_label=labels.get(r.round_key, ""),
                        car_class=r.car_class,
                        laps=r.laps,
                        class_leader_laps=r.class_leader_laps,
                        distance_pct=r.distance_pct,
                        qualifies=r.qualifies,
                    )
                    for r in d.rounds
                ],
            )
            for d in eligible
        ],
    )


@router.get("/unmatched", response_model=list[UnmatchedNameOut])
async def list_unmatched(
    championship_simgrid_id: int = Query(..., alias="championshipSimgridId"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Imported names with no driver record, plus ranked spelling hints.

    Suggestions exist so an admin can spot a merge quickly; they are never
    applied on their own, because the closest string is not reliably the same
    person.
    """
    records = await _load_imports(db, championship_simgrid_id)
    aliases = await _alias_map(db)

    counts: dict[str, dict] = {}
    for record in records:
        for entry in record.entries:
            if entry.driver_id is not None or entry.normalized_name in aliases:
                continue
            bucket = counts.setdefault(
                entry.normalized_name, {"raw_name": entry.raw_name, "rounds": 0}
            )
            bucket["rounds"] += 1

    if not counts:
        return []

    known = await db.execute(select(Driver.name, Driver.simgrid_display_name))
    pool = sorted({n for row in known.all() for n in row if n})

    return [
        UnmatchedNameOut(
            raw_name=data["raw_name"],
            normalized_name=normalized,
            rounds=data["rounds"],
            suggestions=difflib.get_close_matches(data["raw_name"], pool, n=3, cutoff=0.6),
        )
        for normalized, data in sorted(counts.items())
    ]


@router.get("/aliases", response_model=list[AliasOut])
async def list_aliases(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(GiveawayNameAlias).order_by(GiveawayNameAlias.normalized_alias)
    )
    return list(result.scalars().all())


@router.post("/aliases", response_model=AliasOut, status_code=status.HTTP_201_CREATED)
async def create_alias(
    payload: AliasCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Merge one imported spelling into another driver's identity."""
    normalized_alias = normalize_driver_name(payload.normalized_alias)
    canonical = normalize_driver_name(payload.canonical_display_name)
    if not normalized_alias or not canonical:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Both names are required")
    if normalized_alias == canonical:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A name cannot be merged into itself"
        )

    existing = await db.execute(
        select(GiveawayNameAlias).where(
            GiveawayNameAlias.normalized_alias == normalized_alias
        )
    )
    record = existing.scalars().first()
    driver_id = payload.driver_id or await match_driver_id_by_name(db, canonical)
    if record is None:
        record = GiveawayNameAlias(normalized_alias=normalized_alias)
        db.add(record)
    record.canonical_normalized_name = canonical
    record.canonical_display_name = payload.canonical_display_name.strip()
    record.driver_id = driver_id

    # Backfill the link on rows already imported under the merged spelling, so
    # the unmatched list reflects the decision immediately.
    if driver_id is not None:
        await db.execute(
            RaceResultEntry.__table__.update()
            .where(RaceResultEntry.normalized_name == normalized_alias)
            .values(driver_id=driver_id)
        )
    await db.commit()
    await db.refresh(record)
    return record


@router.delete("/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alias(
    alias_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    record = await db.get(GiveawayNameAlias, alias_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alias not found")
    await db.delete(record)
    await db.commit()


@router.get("/rounds", response_model=list[dict])
async def list_rounds(
    championship_simgrid_id: int = Query(..., alias="championshipSimgridId"),
    _: User = Depends(require_admin),
):
    """Championship rounds, so an admin can pin an upload to the right one.

    Served from the day-long SimGrid cache; no live request is made here.
    """
    try:
        races = await simgrid_service.get_races(championship_simgrid_id)
    except Exception:  # noqa: BLE001 - a missing round list must not block imports
        logger.exception("Failed to load rounds for championship %s", championship_simgrid_id)
        return []
    return [
        {
            "id": race.get("id"),
            "name": race.get("display_name") or race.get("race_name") or "",
            "startsAt": race.get("starts_at"),
            "ended": race.get("ended", False),
        }
        for race in races
        if isinstance(race, dict)
    ]

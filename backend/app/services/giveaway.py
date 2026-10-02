"""Eligibility rules for the championship giveaway.

The regulation reads: "among drivers who covered at least 50% of the distance
in 3 of the 5 championship rounds". Two decisions pin down what that means
here:

* **Distance is measured against the leader of the driver's own class.** The
  races are timed (RaceLaps=0, 70 minutes), so "the distance" is however far
  the leader got. Measuring GT3 against an overall Hypercar winner would hold
  the slower class to a bar it can never reach — at Portimao the GT3 leader
  finished on 40 laps against the Hypercar's 44.
* **Finish status is ignored.** A DNF or DQ does not erase the distance a
  driver actually covered, so only laps count. `finish_status` is carried
  through for display but never gates a round.

The rule functions (`class_leader_laps`, `compute_eligibility`) are free of
I/O so they can be unit-tested directly, and they are mirrored on the
frontend by `src/app/pages/admin/admin-giveaway-tab/giveaway-eligibility.ts`.
The async functions below them read imported round files and manage the
name aliases that merge one driver's spellings.

Every figure is read from the round result files uploaded by admins, never
from SimGrid: eligibility would otherwise need one request per driver, and
SimGrid's per-minute rate limit trips on such a fan-out immediately.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import BadRequest
from app.models.bwp import Driver
from app.models.race_result import (
    GiveawayNameAlias,
    RaceResultEntry,
    RaceResultImport,
    normalize_driver_name,
)
from app.schemas.giveaway import (
    DriverAliasCreate,
    EligibleDriverOut,
    GiveawayEligibilityOut,
    RoundBreakdownOut,
    UnmatchedDriverNameOut,
)
from app.services.driver_matching import match_driver_id_by_name
from app.services.race_import import alias_map


@dataclass(frozen=True)
class RoundEntry:
    """One driver's result in one round, already name-normalised."""

    round_key: str
    identity: str
    display_name: str
    car_class: str
    laps: int


@dataclass
class RoundBreakdown:
    round_key: str
    car_class: str
    laps: int
    class_leader_laps: int
    distance_pct: float
    qualifies: bool


@dataclass
class EligibleDriver:
    identity: str
    display_name: str
    car_class: str
    qualifying_rounds: int
    rounds: list[RoundBreakdown] = field(default_factory=list)


def class_leader_laps(entries: list[RoundEntry]) -> dict[tuple[str, str], int]:
    """Highest lap count per (round, class) — the 100% mark for that class."""
    leaders: dict[tuple[str, str], int] = {}
    for entry in entries:
        key = (entry.round_key, entry.car_class)
        if entry.laps > leaders.get(key, 0):
            leaders[key] = entry.laps
    return leaders


def compute_eligibility(
    entries: list[RoundEntry],
    min_distance_pct: float,
    min_rounds: int,
) -> list[EligibleDriver]:
    """Drivers who cleared the distance bar in at least `min_rounds` rounds.

    Eligibility is computed per car class: a driver who switched classes
    mid-championship accrues rounds separately in each, which matches a
    regulation that draws the classes separately and for different prizes.
    """
    leaders = class_leader_laps(entries)
    by_driver: dict[tuple[str, str], EligibleDriver] = {}

    for entry in entries:
        leader = leaders.get((entry.round_key, entry.car_class), 0)
        # A round nobody completed a lap of cannot qualify anyone, and guards
        # the division below.
        pct = (entry.laps / leader * 100) if leader > 0 else 0.0
        qualifies = leader > 0 and pct >= min_distance_pct

        key = (entry.identity, entry.car_class)
        driver = by_driver.get(key)
        if driver is None:
            driver = EligibleDriver(
                identity=entry.identity,
                display_name=entry.display_name,
                car_class=entry.car_class,
                qualifying_rounds=0,
            )
            by_driver[key] = driver
        driver.rounds.append(
            RoundBreakdown(
                round_key=entry.round_key,
                car_class=entry.car_class,
                laps=entry.laps,
                class_leader_laps=leader,
                distance_pct=round(pct, 1),
                qualifies=qualifies,
            )
        )
        if qualifies:
            driver.qualifying_rounds += 1

    eligible = [d for d in by_driver.values() if d.qualifying_rounds >= min_rounds]
    # Most rounds first, then alphabetical — the ordering the previous
    # giveaway modal used, so the list reads the same way it used to.
    eligible.sort(key=lambda d: (-d.qualifying_rounds, d.display_name.lower()))
    for driver in eligible:
        driver.rounds.sort(key=lambda r: r.round_key)
    return eligible


# ── Database-backed views ───────────────────────────────────────────────────


async def _imports_with_entries(db: AsyncSession, championship_id: int) -> list[RaceResultImport]:
    result = await db.execute(
        select(RaceResultImport)
        .options(selectinload(RaceResultImport.entries))
        .where(RaceResultImport.championship_simgrid_id == championship_id)
        .order_by(RaceResultImport.session_started_at, RaceResultImport.created_at)
    )
    return list(result.scalars().all())


def _round_key(record: RaceResultImport) -> str:
    """Stable per-round identity used to group and sort rounds."""
    if record.race_simgrid_id is not None:
        return f"race:{record.race_simgrid_id}"
    return f"import:{record.id}"


async def eligibility(
    db: AsyncSession, championship_id: int, min_distance_pct: float, min_rounds: int
) -> GiveawayEligibilityOut:
    """Drivers who cleared the distance bar in enough rounds, grouped by class."""
    records = await _imports_with_entries(db, championship_id)
    aliases = await alias_map(db)
    labels = {_round_key(r): (r.track_event or r.source_filename or "") for r in records}

    rows: list[RoundEntry] = []
    for record in records:
        key = _round_key(record)
        for entry in record.entries:
            canonical, display = aliases.get(entry.normalized_name, (entry.normalized_name, entry.raw_name))
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
    return GiveawayEligibilityOut(
        championship_id=championship_id,
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


async def unmatched_names(db: AsyncSession, championship_id: int) -> list[UnmatchedDriverNameOut]:
    """Imported names with no driver record, plus ranked spelling hints.

    Suggestions exist so an admin can spot a merge quickly; they are never
    applied on their own, because the closest string is not reliably the same
    person.
    """
    records = await _imports_with_entries(db, championship_id)
    aliases = await alias_map(db)

    counts: dict[str, dict] = {}
    for record in records:
        for entry in record.entries:
            if entry.driver_id is not None or entry.normalized_name in aliases:
                continue
            bucket = counts.setdefault(entry.normalized_name, {"raw_name": entry.raw_name, "rounds": 0})
            bucket["rounds"] += 1

    if not counts:
        return []

    known = await db.execute(select(Driver.name, Driver.simgrid_display_name))
    pool = sorted({n for row in known.all() for n in row if n})

    return [
        UnmatchedDriverNameOut(
            raw_name=data["raw_name"],
            normalized_name=normalized,
            rounds=data["rounds"],
            suggestions=difflib.get_close_matches(data["raw_name"], pool, n=3, cutoff=0.6),
        )
        for normalized, data in sorted(counts.items())
    ]


# ── Aliases ─────────────────────────────────────────────────────────────────


def aliases_query():
    return select(GiveawayNameAlias).order_by(GiveawayNameAlias.normalized_alias)


async def upsert_alias(db: AsyncSession, payload: DriverAliasCreate) -> tuple[GiveawayNameAlias, bool]:
    """Merge one imported spelling into another driver's identity.

    Keyed by the normalized alias. Returns the alias and whether it was created.
    """
    normalized_alias = normalize_driver_name(payload.normalized_alias)
    canonical = normalize_driver_name(payload.canonical_display_name)
    if not normalized_alias or not canonical:
        raise BadRequest("Both names are required")
    if normalized_alias == canonical:
        raise BadRequest("A name cannot be merged into itself")

    existing = await db.execute(
        select(GiveawayNameAlias).where(GiveawayNameAlias.normalized_alias == normalized_alias)
    )
    record = existing.scalars().first()
    created = record is None
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
            update(RaceResultEntry)
            .where(RaceResultEntry.normalized_name == normalized_alias)
            .values(driver_id=driver_id)
        )
    await db.commit()
    await db.refresh(record)
    return record, created


async def delete_alias(db: AsyncSession, alias: GiveawayNameAlias) -> None:
    await db.delete(alias)
    await db.commit()

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

This module is deliberately free of I/O so the rules can be unit-tested
directly, and it is mirrored on the frontend by
`src/app/pages/admin/admin-giveaway-tab/giveaway-eligibility.ts`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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

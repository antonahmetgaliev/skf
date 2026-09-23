"""Tests for giveaway eligibility.

Pinned to the regulation: "at least 50% of the distance in 3 of the 5 rounds",
with distance measured against the leader of the driver's own class and finish
status ignored.
"""

from __future__ import annotations

import pathlib

import pytest

from app.services.giveaway import RoundEntry, class_leader_laps, compute_eligibility
from app.services.race_files import parse_race_file

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _rows(*fixtures: str) -> list[RoundEntry]:
    rows: list[RoundEntry] = []
    for name in fixtures:
        race = parse_race_file((FIXTURES / name).read_bytes(), "lmu")
        for entry in race.entries:
            rows.append(
                RoundEntry(
                    round_key=name,
                    identity=" ".join(entry.raw_name.split()).lower(),
                    display_name=entry.raw_name,
                    car_class=entry.car_class,
                    laps=entry.laps,
                )
            )
    return rows


def test_distance_is_measured_against_the_class_leader():
    leaders = class_leader_laps(_rows("portimao.xml"))
    assert leaders[("portimao.xml", "Hyper")] == 44
    assert leaders[("portimao.xml", "GT3")] == 40


def test_portimao_excludes_only_drivers_under_half_distance():
    rows = _rows("portimao.xml")
    eligible = {d.display_name for d in compute_eligibility(rows, 50.0, 1)}
    everyone = {r.display_name for r in rows}

    assert everyone - eligible == {
        "Artur Ivanov",        # 14/40 = 35.0%
        "Ars Ilanovich",       # 11/44 = 25.0%
        "Datian Lozovskyi",    # 10/40 = 25.0%
        "Maxym Beldij",        #  5/44 = 11.4%
        "Dan Edvardsen",       #  5/40 = 12.5%
    }


def test_disqualified_driver_still_counts_when_distance_is_met():
    """DQ is a sanction on the result, not a claim the laps were not driven."""
    rows = _rows("portimao.xml")
    bondariev = next(
        d for d in compute_eligibility(rows, 50.0, 1)
        if d.display_name == "Dmitriy Bondariev"
    )
    breakdown = bondariev.rounds[0]

    assert breakdown.laps == 22
    assert breakdown.class_leader_laps == 40
    assert breakdown.distance_pct == 55.0
    assert breakdown.qualifies


def test_dnf_counts_when_distance_is_met():
    """Gaydabura retired at Laguna Seca having covered 81.8% of the distance."""
    rows = _rows("laguna_seca.xml")
    driver = next(
        d for d in compute_eligibility(rows, 50.0, 1)
        if d.display_name == "Sergiy Gaydabura"
    )
    assert driver.rounds[0].distance_pct == pytest.approx(81.8, abs=0.1)


def test_classes_are_counted_separately():
    rows = _rows("portimao.xml", "laguna_seca.xml")
    eligible = compute_eligibility(rows, 50.0, 2)

    by_class: dict[str, set[str]] = {}
    for driver in eligible:
        by_class.setdefault(driver.car_class, set()).add(driver.display_name)

    assert by_class["Hyper"] == {
        "Arsen Petrosian", "Max Tarasenko", "Sergiy Gaydabura", "Vladyslav Mykhailenko",
    }
    assert len(by_class["GT3"]) == 10
    assert "Bohdan Hulobov" in by_class["GT3"]  # DQ at 54.5%, still counted


def test_min_rounds_threshold_is_applied():
    rows = _rows("portimao.xml", "laguna_seca.xml")

    # Petrosian raced both rounds; Whitfield only Portimao.
    two_rounds = {d.display_name for d in compute_eligibility(rows, 50.0, 2)}
    one_round = {d.display_name for d in compute_eligibility(rows, 50.0, 1)}

    assert "Arsen Petrosian" in two_rounds
    assert "Jaz Whitfield" in one_round
    assert "Jaz Whitfield" not in two_rounds


def test_a_driver_racing_under_two_spellings_splits_without_a_merge():
    """The case the alias table exists to fix.

    The same person entered as "Max Tarasenko" and "Maksym Tarasenko" holds one
    qualifying round under each identity, so a 2-round bar rejects them.
    """
    rows = [
        RoundEntry("r1", "max tarasenko", "Max Tarasenko", "Hyper", 44),
        RoundEntry("r2", "maksym tarasenko", "Maksym Tarasenko", "Hyper", 55),
    ]
    assert compute_eligibility(rows, 50.0, 2) == []

    merged = [
        RoundEntry("r1", "max tarasenko", "Max Tarasenko", "Hyper", 44),
        RoundEntry("r2", "max tarasenko", "Max Tarasenko", "Hyper", 55),
    ]
    assert [d.display_name for d in compute_eligibility(merged, 50.0, 2)] == [
        "Max Tarasenko"
    ]


def test_round_where_nobody_completed_a_lap_qualifies_nobody():
    rows = [
        RoundEntry("r1", "a", "A", "GT3", 0),
        RoundEntry("r1", "b", "B", "GT3", 0),
    ]
    assert compute_eligibility(rows, 50.0, 1) == []


def test_results_are_sorted_by_rounds_then_name():
    rows = [
        RoundEntry("r1", "zoe", "Zoe", "GT3", 10),
        RoundEntry("r1", "adam", "Adam", "GT3", 10),
        RoundEntry("r2", "zoe", "Zoe", "GT3", 10),
    ]
    assert [d.display_name for d in compute_eligibility(rows, 50.0, 1)] == ["Zoe", "Adam"]


def test_zero_threshold_admits_everyone_who_started():
    rows = _rows("portimao.xml")
    assert len(compute_eligibility(rows, 0.0, 1)) == 26

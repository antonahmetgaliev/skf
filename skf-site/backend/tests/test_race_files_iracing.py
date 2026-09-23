"""Tests for the iRaceControl `.bin` parser (iRacing).

`iracing_gt4_r3.bin` is a real SKF round from ir-incidents-parser's samples.
`iracing_gt4_r3.expected.json` is that tool's own output for it (filtered
incidents and standings), so the port is pinned to the original behaviour.
The rest use small hand-built MessagePack files.
"""

from __future__ import annotations

import json
import pathlib

import msgpack
import pytest

from app.services.race_files import RaceFileError, parse_race_file
from app.services.race_files.iracing import (
    DEFAULT_RULES,
    FilterRules,
    apply_filters,
    parse_race_file as parse_bin,
    race_clock,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _fixture() -> bytes:
    return (FIXTURES / "iracing_gt4_r3.bin").read_bytes()


def test_matches_the_original_parser_on_a_real_round():
    expected = json.loads((FIXTURES / "iracing_gt4_r3.expected.json").read_text())
    race_file = parse_bin(_fixture())

    assert race_file.auto_grouped == expected["autoGrouped"]
    assert race_file.subsession_id == expected["event"]["subsessionId"]
    assert [
        {
            "id": i.id,
            "sessionNum": i.session_num,
            "sessionName": i.session_name,
            "time": i.time,
            "drivers": [d.name for d in i.drivers],
        }
        for i in apply_filters(race_file.incidents)
    ] == expected["incidents"]
    assert [
        {
            "num": s.num,
            "name": s.name,
            "type": s.type,
            "standingsSource": s.standings_source,
            "standings": [
                {
                    "pos": r.pos,
                    "classPos": r.class_pos,
                    "name": r.name,
                    "className": r.class_name,
                    "laps": r.laps,
                    "status": r.status,
                }
                for r in s.standings
            ],
        }
        for s in race_file.sessions
    ] == expected["sessions"]


def test_round_summary_for_giveaway_and_stewards():
    parsed = parse_race_file(_fixture(), "iracing")

    assert parsed.sim == "iracing"
    assert parsed.external_session_id is not None
    assert parsed.session_started_at is not None
    assert len(parsed.contacts) == 4
    assert all(len(c.drivers) >= 2 for c in parsed.contacts)
    # Entries are the race session's official classification.
    assert [e.position for e in parsed.entries] == sorted(e.position for e in parsed.entries)
    assert parsed.entries[0].laps > 0


def test_race_time_uses_float32_subtraction():
    # iRaceControl subtracts in float32: 1730.99988 s, printed as 00:28:50.
    # Double precision gives exactly 1731.0 and prints 00:28:51.
    _, pre_green, time = race_clock(2425.994, 694.994)
    assert pre_green is False
    assert time == "00:28:50"
    _, pre_green, time = race_clock(10.0, 141.5)
    assert pre_green is True
    assert time == "-00:02:12"


def _driver(car, name, lap=3, x=4, dist=3.5, session=2, t=100.0):
    return {
        "car_id": car,
        "car_number": str(car),
        "driver_name": name,
        "team_name": "",
        "lap": lap,
        "x": x,
        "text": f"{x}x",
        "dist": dist,
        "session_num": session,
        "session_name": "RACE",
        "session_type": "Race",
        "time": t,
    }


def _bin(log: dict, *, session_type="Race") -> bytes:
    raw = {
        "track_name": "Test Track",
        "config_name": "GP",
        "subsession_id": 123,
        "pace_car_idx": 0,
        "cars": {
            1: {"car_number": "1", "driver_name": "Alpha", "team": "", "class_name": "GT4"},
            2: {"car_number": "2", "driver_name": "Bravo", "team": "", "class_name": "GT4"},
            3: {"car_number": "3", "driver_name": "Charlie", "team": "", "class_name": "GT4"},
        },
        "sessionData": {
            2: {
                "session_name": "RACE",
                "session_type": session_type,
                "race_start_delay": 40.0,
                "cars": {
                    1: {"car_id": 1, "position": 1, "class_position": 1, "laps_completed": 20},
                    2: {"car_id": 2, "position": 2, "class_position": 2, "laps_completed": 19},
                },
            }
        },
        "raceLog": {"log": log},
    }
    return msgpack.packb(raw)


def test_grouping_off_files_are_regrouped():
    """Singles within 10 s and 0.1 lap of a group's first incident join it."""
    payload = _bin(
        {
            1: [1, _driver(1, "Alpha", t=100.0, dist=3.50)],
            2: [1, _driver(2, "Bravo", t=101.0, dist=3.55)],
            # Too far along the lap to be the same incident.
            3: [1, _driver(3, "Charlie", t=102.0, dist=3.90)],
            # Same place, but more than 10 s later.
            4: [1, _driver(3, "Charlie", t=115.0, dist=3.52)],
        }
    )
    parsed = parse_race_file(payload, "iracing")

    assert parsed.auto_grouped is True
    # Only the Alpha/Bravo group is multi-car; the rest are filtered out.
    assert [(c.drivers, c.time, c.lap) for c in parsed.contacts] == [
        (["Alpha", "Bravo"], "00:01:00", "3")
    ]
    assert parsed.track_event == "Test Track - GP"
    assert parsed.external_session_id == 123


def test_recorded_groups_are_kept_as_is():
    group = _driver(-1, "", t=100.0)
    group["entries"] = {
        0: [1, _driver(1, "Alpha")],
        1: [1, _driver(2, "Bravo", x=1)],  # 1x row: dropped by the points filter
        2: [1, _driver(3, "Charlie")],
    }
    parsed = parse_race_file(_bin({5: [0, group]}), "iracing")

    assert parsed.auto_grouped is False
    assert [c.drivers for c in parsed.contacts] == [["Alpha", "Charlie"]]


def test_filters_can_be_overridden():
    race_file = parse_bin(_bin({1: [1, _driver(1, "Alpha")]}))
    assert apply_filters(race_file.incidents, DEFAULT_RULES) == []
    singles = apply_filters(race_file.incidents, FilterRules(min_cars_per_incident=1))
    assert [d.name for d in singles[0].drivers] == ["Alpha"]


def test_standings_fall_back_to_iracecontrol_tracking():
    parsed = parse_race_file(_bin({}), "iracing")
    assert [(e.raw_name, e.laps, e.position) for e in parsed.entries] == [
        ("Alpha", 20, 1),
        ("Bravo", 19, 2),
    ]


@pytest.mark.parametrize(
    "payload,message",
    [
        (b"<?xml version='1.0'?><rFactorXML/>", "iRaceControl"),
        (msgpack.packb({"hello": "world"}), "missing raceLog"),
    ],
)
def test_rejects_files_that_are_not_iracecontrol(payload, message):
    with pytest.raises(RaceFileError) as exc:
        parse_race_file(payload, "iracing")
    assert message in str(exc.value)


def test_rejects_a_file_without_a_race_session():
    with pytest.raises(RaceFileError) as exc:
        parse_race_file(_bin({}, session_type="Lone Qualify"), "iracing")
    assert "no race session" in str(exc.value)

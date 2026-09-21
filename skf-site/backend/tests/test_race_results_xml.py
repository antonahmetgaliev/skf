"""Tests for the rFactor2/LMU race-result parser.

The fixtures are two real SKF races with the chat stream and per-lap rows
removed (the parser ignores both, and the chat is private conversation).
"""

from __future__ import annotations

import pathlib

import pytest

from app.services.race_results_xml import RaceResultsXmlError, parse_race_results

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_parses_portimao_grid():
    race = parse_race_results(_load("portimao.xml"))

    assert race.track_event == "6 Hours of Portimao"
    assert len(race.entries) == 26
    # Timed race: RaceLaps is 0 in the file, so there is no lap target.
    assert race.race_laps is None
    assert race.race_minutes == 70
    assert race.session_started_at is not None


def test_parses_laguna_seca_grid():
    race = parse_race_results(_load("laguna_seca.xml"))

    assert race.track_event == "WeatherTech Raceway Laguna Seca"
    assert len(race.entries) == 17


@pytest.mark.parametrize(
    "fixture,expected",
    [("portimao.xml", {"Hyper": 44, "GT3": 40}), ("laguna_seca.xml", {"Hyper": 55, "GT3": 50})],
)
def test_class_leader_lap_counts(fixture, expected):
    """The per-class leader is what "100% of the distance" means for a class."""
    race = parse_race_results(_load(fixture))
    leaders: dict[str, int] = {}
    for entry in race.entries:
        leaders[entry.car_class] = max(leaders.get(entry.car_class, 0), entry.laps)
    assert leaders == expected


def test_finish_statuses_are_preserved():
    race = parse_race_results(_load("portimao.xml"))
    counts: dict[str, int] = {}
    for entry in race.entries:
        counts[entry.finish_status] = counts.get(entry.finish_status, 0) + 1
    assert counts == {"Finished Normally": 18, "DNF": 6, "DQ": 2}


def test_entry_fields_are_populated():
    race = parse_race_results(_load("laguna_seca.xml"))
    winner = next(e for e in race.entries if e.position == 1)

    assert winner.raw_name == "Max Tarasenko"
    assert winner.car_class == "Hyper"
    assert winner.laps == 55
    assert winner.class_position == 1


def test_chat_and_lap_rows_are_ignored():
    """A stream block and per-lap rows must not leak into the parsed result."""
    payload = b"""<?xml version="1.0" encoding="utf-8"?>
<rFactorXML version="1.0">
<RaceResults>
<TrackEvent>Test Event</TrackEvent>
<RaceTime>70</RaceTime>
<Race>
<Stream>
<ChatMessage et="52.5">A Driver: something private</ChatMessage>
<Incident et="162.0">A Driver(7) reported contact with B Driver(13)</Incident>
</Stream>
<Driver>
<Name>A Driver</Name><CarClass>GT3</CarClass><ServerScored>1</ServerScored>
<Position>1</Position><ClassPosition>1</ClassPosition>
<Laps>10</Laps><FinishStatus>Finished Normally</FinishStatus>
<Lap num="1">95.1</Lap><Lap num="2">94.8</Lap>
</Driver>
</Race>
</RaceResults>
</rFactorXML>"""
    race = parse_race_results(payload)

    assert len(race.entries) == 1
    entry = race.entries[0]
    assert entry.raw_name == "A Driver"
    assert entry.laps == 10
    # The dataclass has no field that could carry chat or lap times at all.
    assert not any("private" in str(v) for v in vars(entry).values())


def test_unscored_entries_are_skipped():
    payload = b"""<rFactorXML><RaceResults><Race>
<Driver><Name>Scored</Name><CarClass>GT3</CarClass><ServerScored>1</ServerScored><Laps>10</Laps></Driver>
<Driver><Name>Spectator</Name><CarClass>GT3</CarClass><ServerScored>0</ServerScored><Laps>0</Laps></Driver>
</Race></RaceResults></rFactorXML>"""
    race = parse_race_results(payload)

    assert [e.raw_name for e in race.entries] == ["Scored"]


def test_driver_without_laps_element_scores_zero():
    payload = b"""<rFactorXML><RaceResults><Race>
<Driver><Name>Did Not Start</Name><CarClass>GT3</CarClass><ServerScored>1</ServerScored></Driver>
</Race></RaceResults></rFactorXML>"""
    assert parse_race_results(payload).entries[0].laps == 0


@pytest.mark.parametrize(
    "payload,message",
    [
        (b"", "empty"),
        (b"not xml at all", "valid XML"),
        (b"<something/>", "rFactor2/LMU"),
        (b"<rFactorXML><RaceResults><Qualify/></RaceResults></rFactorXML>", "no race session"),
        (
            b"<rFactorXML><RaceResults><Race><Driver><Name>X</Name>"
            b"<ServerScored>0</ServerScored></Driver></Race></RaceResults></rFactorXML>",
            "no scored drivers",
        ),
    ],
)
def test_rejects_unusable_files(payload, message):
    with pytest.raises(RaceResultsXmlError) as exc:
        parse_race_results(payload)
    assert message in str(exc.value)


def test_rejects_oversized_file():
    from app.services.race_results_xml import MAX_UPLOAD_BYTES

    with pytest.raises(RaceResultsXmlError) as exc:
        parse_race_results(b"x" * (MAX_UPLOAD_BYTES + 1))
    assert "too large" in str(exc.value)


def test_external_entities_are_not_resolved():
    """An uploaded file must not be able to read server files (XXE)."""
    payload = (
        b'<!DOCTYPE r [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b"<rFactorXML><RaceResults><Race><Driver><Name>&xxe;</Name>"
        b"<ServerScored>1</ServerScored><Laps>1</Laps></Driver></Race></RaceResults></rFactorXML>"
    )
    with pytest.raises(RaceResultsXmlError):
        parse_race_results(payload)

"""Parser for iRaceControl race files (`.bin`), the iRacing stewarding log.

A port of ir-incidents-parser (`bin-parser.js` + `incident-filters.js`), the
desktop tool stewards used before this moved server-side. Its FORMAT.md is
the reference for the layout; the behaviour here matches it on all 24 sample
files shipped with that tool.

The file is one MessagePack map. It holds every session of the event
(practice, qualifying, heats, race) in a single incident log, iRacing's own
official results as a YAML string, and iRaceControl's per-session tracking.
"""

from __future__ import annotations

import logging
import math
import re
import struct
from dataclasses import dataclass, field, replace
from datetime import datetime

import msgpack
import yaml

from app.services.race_files.types import (
    ParsedContact,
    ParsedEntry,
    ParsedRaceFile,
    RaceFileError,
    format_clock,
)

logger = logging.getLogger(__name__)

LOG_KIND_GROUP = 0
LOG_KIND_INCIDENT = 1

# iRaceControl's grouping rule, fitted on files recorded with grouping on
# (FORMAT.md, "Grouping rule"): an incident joins a group whose first incident
# was at most 10 s earlier and 0.1 lap away.
GROUP_WINDOW_S = 10
GROUP_DISTANCE_LAPS = 0.1


@dataclass(frozen=True)
class FilterRules:
    """Which incident blocks are worth a steward's review.

    Applied in order: session -> baseline -> points (per driver) -> cars (per
    block) -> pre-green.
    """

    # Matched on session *type*, so custom names ("FP1", "HEAT 2") still work.
    exclude_session_types: tuple[str, ...] = ("Practice", "Warmup")
    # Rows iRaceControl dumps on connect with each driver's running total.
    exclude_baseline: bool = True
    # Drop 1x rows (off-tracks); upgraded incidents ("2x->4x") count with
    # their final value.
    min_incident_points: int = 2
    # Only multi-car incidents; distinct cars left after the points filter.
    min_cars_per_incident: int = 2
    # Incidents before the green flag (grid / formation lap contacts).
    include_pre_green: bool = True


DEFAULT_RULES = FilterRules()


@dataclass(frozen=True)
class Driver:
    car_idx: int
    num: str
    name: str
    team: str
    lap: int
    inc: int | None
    inc_text: str
    dist: float
    baseline: bool


@dataclass(frozen=True)
class Incident:
    id: int
    session_num: int
    session_name: str
    session_type: str
    session_time: float
    race_time: float
    pre_green: bool
    time: str
    grouped: bool
    drivers: list[Driver] = field(default_factory=list)
    auto_grouped: bool = False


@dataclass(frozen=True)
class Standing:
    pos: int
    class_pos: int | None
    car_idx: int
    num: str
    name: str
    team: str
    class_name: str
    laps: int
    status: str | None


@dataclass(frozen=True)
class Session:
    num: int
    name: str
    type: str
    standings_source: str
    standings: list[Standing]


@dataclass(frozen=True)
class RaceFile:
    auto_grouped: bool
    track_name: str | None
    config_name: str | None
    subsession_id: int | None
    start_time: datetime | None
    sessions: list[Session]
    incidents: list[Incident]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _f32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


def _get(mapping, key):
    """Look a key up whether the map was written with int or str keys."""
    if not isinstance(mapping, dict):
        return None
    if key in mapping:
        return mapping[key]
    return mapping.get(str(key))


def _by_numeric_key(mapping) -> list[tuple[int, object]]:
    if not isinstance(mapping, dict):
        return []
    return sorted(((int(k), v) for k, v in mapping.items()), key=lambda kv: kv[0])


def race_clock(session_time: float, race_start_delay: float | None) -> tuple[float, bool, str]:
    """Time relative to the green flag, exactly as iRaceControl prints it.

    The app subtracts in float32 (race_start_delay is stored as float32);
    double precision gives off-by-one-second results on some files.
    """
    race_time = _f32(_f32(session_time) - _f32(race_start_delay or 0))
    return race_time, race_time < 0, format_clock(math.floor(race_time))


# ── Incidents ────────────────────────────────────────────────────────────────

def _to_driver(entry: dict) -> Driver:
    lap = entry.get("lap")
    dist = entry.get("dist")
    return Driver(
        car_idx=entry.get("car_id"),
        num=entry.get("car_number") or "",
        name=(entry.get("driver_name") or "").strip(),
        team=entry.get("team_name") or "",
        lap=lap,
        inc=entry.get("x"),
        inc_text=entry.get("text") or "",
        dist=dist if isinstance(dist, (int, float)) else -1,
        # Connect-time dump of each driver's incident total (no track
        # position), not a real incident.
        baseline=lap == -1 and dist == -1,
    )


def _parse_incidents(raw: dict) -> list[Incident]:
    incidents: list[Incident] = []
    log = (raw.get("raceLog") or {}).get("log")

    for key, item in _by_numeric_key(log):
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        kind, entry = item[0], item[1]
        if kind == LOG_KIND_INCIDENT:
            rows = [entry]
        elif kind == LOG_KIND_GROUP:
            rows = [row[1] for _, row in _by_numeric_key(entry.get("entries"))]
        else:
            continue  # lap times, flags, NIW etc.

        session = _get(raw.get("sessionData"), entry.get("session_num")) or {}
        race_time, pre_green, time = race_clock(
            entry.get("time") or 0, session.get("race_start_delay")
        )
        incidents.append(
            Incident(
                id=key,
                session_num=entry.get("session_num"),
                session_name=entry.get("session_name") or "",
                session_type=entry.get("session_type") or "",
                session_time=entry.get("time") or 0,
                race_time=race_time,
                pre_green=pre_green,
                time=time,
                grouped=kind == LOG_KIND_GROUP,
                drivers=[_to_driver(row) for row in rows],
            )
        )

    return incidents


def _lap_fraction(dist: float) -> float:
    return dist - math.floor(dist)


def _track_distance(a: float, b: float) -> float:
    d = abs(_lap_fraction(a) - _lap_fraction(b))
    return min(d, 1 - d)


def _is_grouping_off(incidents: list[Incident]) -> bool:
    """Grouping is an iRaceControl setting; when off, the log has no real groups."""
    return not any(
        i.grouped and any(not d.baseline for d in i.drivers) for i in incidents
    )


def _group_incidents(incidents: list[Incident]) -> list[Incident]:
    """Rebuild multi-car incidents from single-car entries, as iRaceControl does."""
    ordered = sorted(incidents, key=lambda i: (i.session_num, i.session_time, i.id))
    result: list[Incident] = []
    open_groups: list[Incident] = []

    for incident in ordered:
        driver = incident.drivers[0] if incident.drivers else None
        if incident.grouped or driver is None or driver.baseline or driver.dist < 0:
            result.append(incident)
            continue

        open_groups = [
            g
            for g in open_groups
            if g.session_num == incident.session_num
            and incident.session_time - g.session_time <= GROUP_WINDOW_S
        ]

        best: Incident | None = None
        best_distance = math.inf
        for group in open_groups:
            if any(d.car_idx == driver.car_idx for d in group.drivers):
                continue
            distance = _track_distance(group.drivers[0].dist, driver.dist)
            if distance <= GROUP_DISTANCE_LAPS and distance < best_distance:
                best, best_distance = group, distance

        if best is not None:
            best.drivers.append(driver)
        else:
            group = replace(incident, drivers=[driver], auto_grouped=True)
            open_groups.append(group)
            result.append(group)

    return result


def apply_filters(incidents: list[Incident], rules: FilterRules = DEFAULT_RULES) -> list[Incident]:
    """Filter parsed incident blocks. Driver rows are filtered first, then blocks."""
    kept: list[Incident] = []
    for incident in incidents:
        if incident.session_type in rules.exclude_session_types:
            continue
        drivers = [
            d
            for d in incident.drivers
            if not (rules.exclude_baseline and d.baseline)
            and d.inc is not None
            and d.inc >= rules.min_incident_points
        ]
        if len({d.car_idx for d in drivers}) < rules.min_cars_per_incident:
            continue
        if incident.pre_green and not rules.include_pre_green:
            continue
        kept.append(replace(incident, drivers=drivers))
    return kept


# ── Standings ────────────────────────────────────────────────────────────────

_SESSION_INFO_BLOCK = re.compile(r"^SessionInfo:\n.*?(?=^\S)", re.MULTILINE | re.DOTALL)


def _parse_official_results(session_string: str | None) -> dict[int, list[dict]]:
    """iRacing's own results per session from the SessionInfo YAML.

    Only the SessionInfo block is parsed: there are no user-entered strings in
    it, unlike DriverInfo.
    """
    if not session_string:
        return {}
    block = _SESSION_INFO_BLOCK.search(session_string)
    if block is None:
        return {}
    try:
        sessions = (yaml.safe_load(block.group(0)) or {}).get("SessionInfo", {}).get("Sessions") or []
    except yaml.YAMLError as exc:
        logger.warning("Could not parse iRacing results from sessionString: %s", exc)
        return {}
    return {s.get("SessionNum"): s.get("ResultsPositions") or [] for s in sessions}


def _is_classified_car(raw: dict, car_idx) -> bool:
    car = _get(raw.get("cars"), car_idx)
    return bool(car) and car_idx != raw.get("pace_car_idx") and not car.get("is_spectator")


def _car_info(raw: dict, car_idx) -> dict:
    car = _get(raw.get("cars"), car_idx)
    return {
        "car_idx": car_idx,
        "num": car.get("car_number") or "",
        "name": (car.get("driver_name") or "").strip(),
        "team": car.get("team") or "",
        "class_name": car.get("class_name") or "",
    }


def _standings_from_official(raw: dict, results: list[dict]) -> list[Standing]:
    """Order and times include penalties."""
    return [
        Standing(
            pos=r.get("Position"),
            # iRacing class positions are 0-based.
            class_pos=r["ClassPosition"] + 1 if isinstance(r.get("ClassPosition"), int) else None,
            laps=r.get("LapsComplete") or 0,
            status=r.get("ReasonOutStr"),
            **_car_info(raw, r.get("CarIdx")),
        )
        for r in results
        if _is_classified_car(raw, r.get("CarIdx"))
    ]


def _standings_from_iracecontrol(raw: dict, session: dict) -> list[Standing]:
    """Fallback: standings as tracked by iRaceControl itself."""
    cars = [
        c
        for c in (session.get("cars") or {}).values()
        if _is_classified_car(raw, c.get("car_id")) and (c.get("position") or 0) > 0
    ]
    cars.sort(key=lambda c: c["position"])
    return [
        Standing(
            pos=c["position"],
            class_pos=c.get("class_position"),
            laps=c.get("laps_completed") or 0,
            status=c.get("reasonOutStr"),
            **_car_info(raw, c.get("car_id")),
        )
        for c in cars
    ]


def _parse_sessions(raw: dict) -> list[Session]:
    official = _parse_official_results(raw.get("sessionString"))
    sessions: list[Session] = []
    for num, s in _by_numeric_key(raw.get("sessionData")):
        results = official.get(num)
        use_official = bool(results)
        sessions.append(
            Session(
                num=num,
                name=s.get("session_name") or "",
                type=s.get("session_type") or "",
                standings_source="iracing" if use_official else "iracecontrol",
                standings=(
                    _standings_from_official(raw, results)
                    if use_official
                    else _standings_from_iracecontrol(raw, s)
                ),
            )
        )
    return sessions


def _lap_label(incident: Incident) -> str | None:
    lap = incident.drivers[0].lap if incident.drivers else None
    return str(lap) if isinstance(lap, int) and lap >= 0 else None


# ── Entry points ─────────────────────────────────────────────────────────────

def parse_race_file(payload: bytes) -> RaceFile:
    """Decode a .bin into sessions and **all** incident blocks, unfiltered."""
    try:
        raw = msgpack.unpackb(payload, raw=False, strict_map_key=False, timestamp=3)
    except Exception as exc:  # noqa: BLE001 - any undecodable payload lands here
        raise RaceFileError("File is not an iRaceControl race file (iRacing expects .bin)") from exc

    if not isinstance(raw, dict) or not raw.get("raceLog") or not raw.get("sessionData"):
        raise RaceFileError("Not an iRaceControl race file (missing raceLog/sessionData)")

    incidents = _parse_incidents(raw)
    auto_grouped = _is_grouping_off(incidents)
    if auto_grouped:
        incidents = _group_incidents(incidents)

    start_time = raw.get("start_time")
    return RaceFile(
        auto_grouped=auto_grouped,
        track_name=raw.get("track_name"),
        config_name=raw.get("config_name"),
        subsession_id=raw.get("subsession_id"),
        start_time=start_time if isinstance(start_time, datetime) else None,
        sessions=_parse_sessions(raw),
        incidents=incidents,
    )


def parse(payload: bytes, rules: FilterRules = DEFAULT_RULES) -> ParsedRaceFile:
    race_file = parse_race_file(payload)

    # Heats and a feature are all "Race" sessions; the feature, which runs
    # last, is the round's result.
    races = [s for s in race_file.sessions if s.type == "Race"]
    if not races:
        raise RaceFileError(
            "File contains no race session (practice/qualifying exports are not usable)"
        )
    race = races[-1]
    entries = [
        ParsedEntry(
            raw_name=s.name,
            car_class=s.class_name,
            laps=max(s.laps, 0),
            position=s.pos,
            class_position=s.class_pos,
            finish_status=s.status,
        )
        for s in race.standings
        if s.name
    ]
    if not entries:
        raise RaceFileError("Race session contains no classified drivers")

    contacts = [
        ParsedContact(
            session_name=i.session_name,
            session_time_s=i.session_time,
            time=i.time,
            drivers=[d.name for d in i.drivers],
            lap=_lap_label(i),
        )
        for i in apply_filters(race_file.incidents, rules)
    ]

    track = race_file.track_name
    if track and race_file.config_name:
        track = f"{track} - {race_file.config_name}"

    return ParsedRaceFile(
        sim="iracing",
        track_event=track,
        session_started_at=race_file.start_time,
        race_laps=None,
        race_minutes=None,
        entries=entries,
        contacts=contacts,
        external_session_id=race_file.subsession_id,
        auto_grouped=race_file.auto_grouped,
    )

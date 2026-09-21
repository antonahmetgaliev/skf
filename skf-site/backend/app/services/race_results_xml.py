"""Parser for rFactor2 / Le Mans Ultimate server result XML.

The SimGrid REST API exposes no per-race results at all: `partial_standings`
comes back empty for every entry, `races/:id/session_results` answers
`[null, null]`, and the HTML pages that used to be scraped now sit behind a
Cloudflare challenge. Laps completed — the one number the giveaway regulation
needs — is therefore only obtainable from the game server's own result file.

This module turns such a file into the handful of fields the giveaway cares
about. It deliberately drops `<Stream>` (chat, incident and track-limit
messages) and the per-lap `<Lap>` rows: neither is needed to decide
eligibility, and the chat log is private conversation we have no reason to
store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from xml.etree.ElementTree import fromstring

# Result files run ~600 KB for a full grid; 10 MB is roomy enough for a long
# endurance entry list while still refusing anything absurd.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class RaceResultsXmlError(ValueError):
    """Raised when a file is not a usable rFactor2/LMU race result."""


@dataclass(frozen=True)
class ParsedEntry:
    raw_name: str
    car_class: str
    laps: int
    position: int | None
    class_position: int | None
    finish_status: str | None


@dataclass(frozen=True)
class ParsedRace:
    track_event: str | None
    session_started_at: datetime | None
    race_laps: int | None
    race_minutes: int | None
    entries: list[ParsedEntry]


def _int_or_none(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text.strip())
    except (TypeError, ValueError):
        return None


def _text(node, tag: str) -> str | None:
    value = node.findtext(tag)
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_race_results(payload: bytes) -> ParsedRace:
    """Parse a race result file into the fields the giveaway needs.

    Raises `RaceResultsXmlError` for anything that is not a race result — a
    qualifying-only export, a different game's format, or plain garbage.
    """
    if not payload:
        raise RaceResultsXmlError("File is empty")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise RaceResultsXmlError("File is too large")

    # These files open with `<!DOCTYPE rF [<!ENTITY rFEnt "rFactor Entity">]>`,
    # so the parser has to tolerate a doctype on untrusted input. ElementTree
    # is safe here without extra work: it refuses external entities outright
    # (no XXE — verified against expat 2.7.4), and expat's input-amplification
    # limit stops entity-expansion bombs. The size cap above covers the rest.
    try:
        root = fromstring(payload.decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 - any malformed XML lands here
        raise RaceResultsXmlError("File is not valid XML") from exc

    results = root.find("RaceResults") if root.tag != "RaceResults" else root
    if results is None:
        raise RaceResultsXmlError("Not an rFactor2/LMU result file")

    race = results.find("Race")
    if race is None:
        raise RaceResultsXmlError(
            "File contains no race session (practice/qualifying exports are not usable)"
        )

    entries: list[ParsedEntry] = []
    for driver in race.findall("Driver"):
        # Only server-scored entries count. Every real entrant in the sample
        # files has ServerScored=1; spectators and AI fillers would not.
        if (driver.findtext("ServerScored") or "").strip() != "1":
            continue
        name = _text(driver, "Name")
        if not name:
            continue
        entries.append(
            ParsedEntry(
                raw_name=name,
                car_class=_text(driver, "CarClass") or "",
                # A driver who never completed a lap has no Laps element.
                laps=_int_or_none(driver.findtext("Laps")) or 0,
                position=_int_or_none(driver.findtext("Position")),
                class_position=_int_or_none(driver.findtext("ClassPosition")),
                finish_status=_text(driver, "FinishStatus"),
            )
        )

    if not entries:
        raise RaceResultsXmlError("Race session contains no scored drivers")

    return ParsedRace(
        track_event=_text(results, "TrackEvent") or _text(results, "TrackVenue"),
        session_started_at=_parse_datetime(results),
        # Timed races report RaceLaps=0; lap-limited ones report the real count.
        race_laps=_int_or_none(results.findtext("RaceLaps")) or None,
        race_minutes=_int_or_none(results.findtext("RaceTime")) or None,
        entries=entries,
    )


def _parse_datetime(results) -> datetime | None:
    """Read the session timestamp, preferring the unix epoch field.

    `<TimeString>` is local server time with no offset, so it is only a
    fallback for display; `<DateTime>` is an unambiguous epoch.
    """
    epoch = _int_or_none(results.findtext("DateTime"))
    if epoch:
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    raw = _text(results, "TimeString")
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

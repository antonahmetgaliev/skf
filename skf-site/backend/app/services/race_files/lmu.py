"""Parser for rFactor2 / Le Mans Ultimate server result XML.

The SimGrid REST API exposes no per-race results at all: `partial_standings`
comes back empty for every entry, `races/:id/session_results` answers
`[null, null]`, and the HTML pages that used to be scraped now sit behind a
Cloudflare challenge. Laps completed — the one number the giveaway regulation
needs — is therefore only obtainable from the game server's own result file.

From `<Stream>` only the `<Incident>` contact reports are read, to build the
stewards' "Auto" incidents. Chat, track-limit and score messages and the
per-lap `<Lap>` rows are dropped: the chat log is private conversation we
have no reason to store.

Contact grouping follows lmu-steward-companion (`get_race_contacts`), the tool
stewards used before this moved server-side.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from xml.etree.ElementTree import fromstring

from app.services.race_files.types import (
    ParsedContact,
    ParsedEntry,
    ParsedRaceFile,
    RaceFileError,
    format_clock,
)

# Two reports within this many seconds that share a car are one incident.
CONTACT_MERGE_WINDOW_S = 3.0

# "Driver A(7) reported contact (63.41) with another vehicle Driver B(13)".
# Contacts with "Immovable", "Sign" etc. are single-car and never match.
_VEHICLE_CONTACT = re.compile(
    r"^(?P<name1>.+?)\((?P<id1>\d+)\) reported contact \([\d.]+\) "
    r"with another vehicle (?P<name2>.+?)\((?P<id2>\d+)\)\s*$"
)


def _int_or_none(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text.strip())
    except (TypeError, ValueError):
        return None


def _float_or_none(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _text(node, tag: str) -> str | None:
    value = node.findtext(tag)
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse(payload: bytes) -> ParsedRaceFile:
    """Parse a race result file.

    Raises `RaceFileError` for anything that is not a race result — a
    qualifying-only export, a different game's format, or plain garbage.
    """
    # These files open with `<!DOCTYPE rF [<!ENTITY rFEnt "rFactor Entity">]>`,
    # so the parser has to tolerate a doctype on untrusted input. ElementTree
    # is safe here without extra work: it refuses external entities outright
    # (no XXE — verified against expat 2.7.4), and expat's input-amplification
    # limit stops entity-expansion bombs. The caller's size cap covers the rest.
    try:
        root = fromstring(payload.decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 - any malformed XML lands here
        raise RaceFileError("File is not valid XML (Le Mans Ultimate expects .xml)") from exc

    results = root.find("RaceResults") if root.tag != "RaceResults" else root
    if results is None:
        raise RaceFileError("Not an rFactor2/LMU result file")

    race = results.find("Race")
    if race is None:
        raise RaceFileError(
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
        raise RaceFileError("Race session contains no scored drivers")

    return ParsedRaceFile(
        sim="lmu",
        track_event=_text(results, "TrackEvent") or _text(results, "TrackVenue"),
        session_started_at=_parse_datetime(results),
        # Timed races report RaceLaps=0; lap-limited ones report the real count.
        race_laps=_int_or_none(results.findtext("RaceLaps")) or None,
        race_minutes=_int_or_none(results.findtext("RaceTime")) or None,
        entries=entries,
        contacts=parse_contacts(race),
    )


def parse_contacts(race) -> list[ParsedContact]:
    """Multi-car contacts from the race session's `<Stream>`, in stream order.

    Every contact is reported by both cars, often a few tenths apart, and a
    pile-up produces a chain of pairwise reports. A report joins an earlier
    contact that already involves one of its cars and started less than
    `CONTACT_MERGE_WINDOW_S` before it; otherwise it starts a new contact.
    """
    stream = race.find("Stream")
    if stream is None:
        return []

    names: dict[str, str] = {}
    # Slot ids are stable within a session, so later events may name a slot
    # the contact text itself already names; either source is fine.
    for event in stream:
        if event.tag in ("Sector", "TrackLimits"):
            slot, driver = event.get("ID"), event.get("Driver")
            if slot and driver:
                names.setdefault(slot, driver.strip())

    contacts: list[dict] = []
    for event in stream.findall("Incident"):
        match = _VEHICLE_CONTACT.match((event.text or "").strip())
        if match is None:
            continue
        et = _float_or_none(event.get("et")) or 0.0
        pair = (match["id1"], match["id2"])
        names[match["id1"]] = match["name1"].strip()
        names[match["id2"]] = match["name2"].strip()

        existing = next(
            (
                c
                for c in contacts
                if (pair[0] in c["slots"] or pair[1] in c["slots"])
                and abs(c["et"] - et) < CONTACT_MERGE_WINDOW_S
            ),
            None,
        )
        if existing is None:
            contacts.append({"et": et, "slots": list(pair)})
        else:
            for slot in pair:
                if slot not in existing["slots"]:
                    existing["slots"].append(slot)

    return [
        ParsedContact(
            session_name="Race",
            session_time_s=c["et"],
            time=format_clock(round(c["et"])),
            drivers=[names.get(slot, slot) for slot in c["slots"]],
        )
        for c in contacts
    ]


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

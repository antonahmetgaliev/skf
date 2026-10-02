"""Shapes every simulator parser produces, whatever the source format."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Sim = Literal["lmu", "iracing"]

# LMU result XML runs ~600 KB for a full grid, an iRaceControl .bin up to ~4 MB.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class RaceFileError(ValueError):
    """Raised when a file is not a usable race result for its simulator."""


@dataclass(frozen=True)
class ParsedEntry:
    """One driver's outcome in the race session, as the giveaway needs it."""

    raw_name: str
    car_class: str
    laps: int
    position: int | None
    class_position: int | None
    finish_status: str | None


@dataclass(frozen=True)
class ParsedContact:
    """A multi-car incident worth a steward's look (an "Auto" incident)."""

    session_name: str
    session_time_s: float
    time: str
    drivers: list[str]
    lap: str | None = None


@dataclass(frozen=True)
class ParsedRaceFile:
    sim: Sim
    track_event: str | None
    session_started_at: datetime | None
    race_laps: int | None
    race_minutes: int | None
    entries: list[ParsedEntry]
    contacts: list[ParsedContact] = field(default_factory=list)
    # iRacing subsession id; None for LMU, whose files carry no such id.
    external_session_id: int | None = None
    # True when iRaceControl recorded without grouping and we regrouped.
    auto_grouped: bool = False


def format_clock(seconds: int) -> str:
    """Whole seconds as HH:MM:SS; negative values get a leading "-"."""
    sign = "-" if seconds < 0 else ""
    s = abs(seconds)
    return f"{sign}{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"

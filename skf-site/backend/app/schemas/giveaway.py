"""Schemas for the giveaway admin API."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.championship import CamelModel


class RoundBreakdownOut(CamelModel):
    round_key: str
    round_label: str
    car_class: str
    laps: int
    class_leader_laps: int
    distance_pct: float
    qualifies: bool


class EligibleDriverOut(CamelModel):
    identity: str
    display_name: str
    car_class: str
    qualifying_rounds: int
    rounds: list[RoundBreakdownOut]


class EligibilityOut(CamelModel):
    championship_simgrid_id: int
    min_distance_pct: float
    min_rounds: int
    imported_rounds: int
    car_classes: list[str]
    drivers: list[EligibleDriverOut]


class ImportEntryOut(CamelModel):
    raw_name: str
    car_class: str
    laps: int
    position: int | None = None
    finish_status: str | None = None
    matched: bool


class ImportOut(CamelModel):
    id: uuid.UUID
    championship_simgrid_id: int
    race_simgrid_id: int | None = None
    track_event: str | None = None
    session_started_at: datetime | None = None
    source_filename: str | None = None
    created_at: datetime
    entry_count: int
    unmatched_count: int


class ImportDetailOut(ImportOut):
    entries: list[ImportEntryOut]


class UnmatchedNameOut(CamelModel):
    raw_name: str
    normalized_name: str
    rounds: int
    # Ranked hints only. They are never applied automatically: on real data the
    # closest match to "Ars Ilanovich" is "Artur Ivanov", a different driver in
    # the same race.
    suggestions: list[str]


class AliasCreate(CamelModel):
    normalized_alias: str
    canonical_display_name: str
    driver_id: uuid.UUID | None = None


class AliasOut(CamelModel):
    id: uuid.UUID
    normalized_alias: str
    canonical_normalized_name: str
    canonical_display_name: str
    driver_id: uuid.UUID | None = None
    created_at: datetime

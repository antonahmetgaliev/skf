"""Schemas for the race-results admin API."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import UploadFile
from pydantic import Field

from app.schemas.base import CamelModel
from app.services.race_files.types import Sim


class RaceResultImportCreate(CamelModel):
    """``POST /race-result-imports``: the multipart form of one round's upload."""

    file: UploadFile
    championship_id: int
    race_id: int
    create_incidents: bool = True
    window_hours: int = Field(default=24, ge=1, le=168)


class ImportEntryOut(CamelModel):
    raw_name: str
    car_class: str
    laps: int
    position: int | None = None
    finish_status: str | None = None
    matched: bool


class ImportOut(CamelModel):
    """One uploaded round file, as listed per championship."""

    id: uuid.UUID
    championship_simgrid_id: int
    race_simgrid_id: int | None = None
    track_event: str | None = None
    session_started_at: datetime | None = None
    source_filename: str | None = None
    sim: Sim = "lmu"
    created_at: datetime
    entry_count: int
    unmatched_count: int


class RaceImportOut(CamelModel):
    id: uuid.UUID
    sim: Sim
    track_event: str | None = None
    session_started_at: datetime | None = None
    source_filename: str | None = None
    file_size: int | None = None
    has_file: bool
    entry_count: int
    unmatched_count: int
    contacts_count: int
    auto_grouped: bool
    created_at: datetime


class RoundWindowOut(CamelModel):
    id: uuid.UUID
    is_open: bool
    closes_at: datetime
    incidents_count: int


class RoundOut(CamelModel):
    race_id: int
    name: str
    starts_at: str | None = None
    ended: bool = False
    race_import: RaceImportOut | None = None
    window: RoundWindowOut | None = None


class RoundsOut(CamelModel):
    championship_id: int
    championship_name: str
    game_name: str
    # None when the championship's game has no supported result file.
    sim: Sim | None = None
    storage_enabled: bool
    rounds: list[RoundOut]


class ImportResultOut(CamelModel):
    race_import: RaceImportOut
    window_id: uuid.UUID | None = None
    incidents_created: int
    incidents_kept: int
    entries: list[ImportEntryOut]

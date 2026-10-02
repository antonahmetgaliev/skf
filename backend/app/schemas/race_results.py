"""Schemas for the race-results admin API."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import UploadFile
from pydantic import Field

from app.schemas.base import CamelModel, IsoDateTime
from app.schemas.enums import Sim
from app.schemas.incidents import IncidentWindowSummaryOut


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
    finish_status: str | None = Field(
        default=None, description="Finish status exactly as the result file words it."
    )
    matched: bool = Field(description="The name resolves to a driver record.")


class RaceResultImportOut(CamelModel):
    """One uploaded round file."""

    id: uuid.UUID
    championship_id: int
    race_id: int | None = None
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


class RoundOut(CamelModel):
    race_id: int
    name: str
    starts_at: IsoDateTime | None = None
    ended: bool = False
    race_import: RaceResultImportOut | None = None
    window: IncidentWindowSummaryOut | None = None


class RoundsOut(CamelModel):
    championship_id: int
    championship_name: str
    game_name: str
    sim: Sim | None = Field(
        default=None, description="`null` when the championship's game has no supported result file."
    )
    storage_enabled: bool
    rounds: list[RoundOut]


class ImportResultOut(CamelModel):
    race_import: RaceResultImportOut
    window_id: uuid.UUID | None = None
    incidents_created: int
    incidents_kept: int
    entries: list[ImportEntryOut]

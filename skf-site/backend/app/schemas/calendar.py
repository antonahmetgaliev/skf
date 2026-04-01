"""Schemas for the calendar feature."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import ConfigDict, Field

from app.schemas.championship import CamelModel


# ── Enums ────────────────────────────────────────────────────────────────────

class CalendarEventType(str, Enum):
    PAST = "past"
    ONGOING = "ongoing"
    UPCOMING = "upcoming"
    FUTURE = "future"


# ── Custom race CRUD schemas ────────────────────────────────────────────────

class CustomRaceCreate(CamelModel):
    date: datetime | None = None
    track: str | None = Field(default=None, max_length=200)


class CustomRaceUpdate(CamelModel):
    date: datetime | None = None
    track: str | None = Field(default=None, max_length=200)
    sort_order: int | None = None


class CustomRaceOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date: datetime | None
    track: str | None
    sort_order: int
    created_at: datetime


# ── Custom championship CRUD schemas ────────────────────────────────────────

class CustomChampionshipCreate(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    game: str = Field(min_length=1, max_length=100)
    car_class: str | None = Field(default=None, max_length=100)
    description: str | None = None
    races: list[CustomRaceCreate] = []


class CustomChampionshipUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    game: str | None = Field(default=None, min_length=1, max_length=100)
    car_class: str | None = Field(default=None, max_length=100)
    description: str | None = None
    is_visible: bool | None = None


class CustomChampionshipOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    game: str
    car_class: str | None
    description: str | None
    is_visible: bool
    races: list[CustomRaceOut]
    created_by_user_id: uuid.UUID | None
    created_at: datetime


# ── Unified calendar event schemas (merge endpoint) ─────────────────────────

class CalendarRace(CamelModel):
    date: str | None = None
    track: str | None = None
    name: str | None = None


class CalendarEvent(CamelModel):
    """Unified calendar event returned by the merge endpoint."""

    id: str
    name: str
    game: str = ""
    car_class: str | None = None
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    event_type: CalendarEventType
    source: str  # "simgrid" or "custom"
    image: str | None = None
    simgrid_championship_id: int | None = None
    custom_championship_id: str | None = None
    races: list[CalendarRace] = []

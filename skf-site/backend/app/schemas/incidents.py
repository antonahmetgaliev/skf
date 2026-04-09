"""Schemas for incident management."""

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field

from app.schemas.championship import CamelModel


# ── Window schemas ──────────────────────────────────────────────────────────

class IncidentWindowCreate(CamelModel):
    championship_id: int | None = None
    championship_name: str | None = Field(default=None, max_length=200)
    race_id: int | None = None
    race_name: str = Field(min_length=1, max_length=200)
    date: str | None = Field(default=None, max_length=20)
    interval_hours: int = Field(default=24, ge=1, le=168)


class IncidentWindowUpdate(CamelModel):
    is_manually_closed: bool | None = None
    interval_hours: int | None = Field(default=None, ge=1, le=168)


# ── Batch ingestion schemas ─────────────────────────────────────────────────

class IncidentBatchItem(CamelModel):
    session_name: str | None = None
    time: str | None = None
    drivers: list[str] = Field(min_length=1)


class IncidentBatchCreate(CamelModel):
    race_id: int
    championship_id: int
    incidents: list[IncidentBatchItem] = Field(min_length=1)


# ── Manual file incident ────────────────────────────────────────────────────

class IncidentFileCreate(CamelModel):
    session_name: str | None = Field(default=None, max_length=100)
    time: str | None = Field(default=None, max_length=50)
    description: str | None = None
    drivers: list[str] = Field(min_length=1)


# ── Per-driver resolve ──────────────────────────────────────────────────────

class ResolveDriverIncident(CamelModel):
    verdict: str = Field(min_length=1)
    bwp_points: int | None = Field(default=None, ge=0)


# ── Output schemas ──────────────────────────────────────────────────────────

class IncidentResolutionOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_driver_id: uuid.UUID
    judge_user_id: uuid.UUID | None
    verdict: str
    bwp_points: int | None
    bwp_applied: bool
    resolved_at: datetime


class IncidentDriverOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    driver_name: str
    driver_id: uuid.UUID | None
    sort_order: int
    resolution: IncidentResolutionOut | None = None


class IncidentOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    window_id: uuid.UUID
    reporter_user_id: uuid.UUID | None
    session_name: str | None
    time: str | None
    description: str | None
    status: str
    created_at: datetime
    drivers: list[IncidentDriverOut] = []


class IncidentWindowListItem(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    championship_id: int | None
    championship_name: str | None
    race_id: int | None
    race_name: str
    date: str | None
    interval_hours: int
    opened_at: datetime
    closes_at: datetime
    opened_by_user_id: uuid.UUID | None
    is_manually_closed: bool
    is_open: bool


class IncidentWindowOut(IncidentWindowListItem):
    incidents: list[IncidentOut] = []

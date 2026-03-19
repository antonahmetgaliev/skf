"""Schemas for incident management."""

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field

from app.schemas.championship import CamelModel


class IncidentWindowCreate(CamelModel):
    championship_id: int
    championship_name: str = Field(min_length=1, max_length=200)
    race_id: int
    race_name: str = Field(min_length=1, max_length=200)
    interval_hours: int = Field(default=24, ge=1, le=168)


class IncidentWindowUpdate(CamelModel):
    is_manually_closed: bool | None = None
    interval_hours: int | None = Field(default=None, ge=1, le=168)


class IncidentResolutionOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    judge_user_id: uuid.UUID | None
    verdict: str
    time_penalty_seconds: int | None
    bwp_points: int | None
    bwp_applied: bool
    resolved_at: datetime


class IncidentOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    window_id: uuid.UUID
    reporter_user_id: uuid.UUID | None
    driver1_name: str
    driver1_driver_id: uuid.UUID | None
    driver2_name: str | None
    driver2_driver_id: uuid.UUID | None
    lap_number: int | None
    turn: str | None
    description: str
    status: str
    created_at: datetime
    resolution: IncidentResolutionOut | None = None


class IncidentWindowListItem(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    championship_id: int
    championship_name: str
    race_id: int
    race_name: str
    interval_hours: int
    opened_at: datetime
    closes_at: datetime
    opened_by_user_id: uuid.UUID | None
    is_manually_closed: bool
    is_open: bool


class IncidentWindowOut(IncidentWindowListItem):
    incidents: list[IncidentOut] = []


class IncidentCreate(CamelModel):
    driver1_name: str = Field(min_length=1, max_length=200)
    driver1_driver_id: uuid.UUID | None = None
    driver2_name: str | None = Field(default=None, max_length=200)
    driver2_driver_id: uuid.UUID | None = None
    lap_number: int | None = Field(default=None, ge=0)
    turn: str | None = Field(default=None, max_length=100)
    description: str = Field(min_length=1)


class ResolveIncident(CamelModel):
    verdict: str = Field(min_length=1)
    time_penalty_seconds: int | None = Field(default=None, ge=0)
    bwp_points: int | None = Field(default=None, ge=0)

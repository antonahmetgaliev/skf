"""Schemas for incident management."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints

from app.schemas.base import CamelModel, Omittable
from app.schemas.enums import IncidentSource, IncidentStatus

# ── Window schemas ──────────────────────────────────────────────────────────


class IncidentWindowCreate(CamelModel):
    championship_id: int | None = None
    championship_name: str | None = Field(default=None, max_length=200)
    race_id: int | None = None
    race_name: str = Field(min_length=1, max_length=200)
    date: str | None = Field(default=None, max_length=20)
    interval_hours: int = Field(default=24, ge=1, le=168)


class IncidentWindowUpdate(CamelModel):
    is_manually_closed: Omittable[bool] = None
    interval_hours: Omittable[Annotated[int, Field(ge=1, le=168)]] = None


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

# Anyone may file an incident without logging in, so every free-text field is
# bounded: the endpoint must not be a way to store arbitrary amounts of data.
MAX_FILED_DRIVERS = 20
DriverName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class IncidentFileCreate(CamelModel):
    session_name: str | None = Field(default=None, max_length=100)
    lap: str | None = Field(default=None, max_length=20)
    corner: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=2000)
    drivers: list[DriverName] = Field(min_length=1, max_length=MAX_FILED_DRIVERS)


class IncidentDriverAdd(CamelModel):
    driver_name: str = Field(min_length=1, max_length=200)


class IncidentDriverUpdate(CamelModel):
    driver_id: uuid.UUID


class WindowIncidentsUpdate(CamelModel):
    # Publishing is one-way: verdicts that went public cannot be hidden again.
    is_published: Literal[True]


# ── Per-driver resolve ──────────────────────────────────────────────────────


class ResolveDriverIncident(CamelModel):
    verdict: str = Field(min_length=1, max_length=2000)
    bwp_points: int | None = Field(default=None, ge=0)


class ResolveDriverItem(CamelModel):
    incident_driver_id: uuid.UUID
    verdict: str | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
        description="Omit to apply the default verdict rule: name the exceptions, the server fills in the rest.",
    )
    bwp_points: int | None = Field(default=None, ge=0)


class BulkResolveIncident(CamelModel):
    description: str | None = Field(default=None, max_length=2000)
    drivers: list[ResolveDriverItem] = Field(min_length=1)


# ── Verdict rule schemas ────────────────────────────────────────────────────


class VerdictRuleOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    verdict: str
    default_bwp: int
    sort_order: int
    is_default: bool


class VerdictRuleCreate(CamelModel):
    verdict: str = Field(min_length=1, max_length=100)
    default_bwp: int = Field(default=0, ge=0)
    is_default: bool = False


class VerdictRuleUpdate(CamelModel):
    verdict: Omittable[Annotated[str, Field(min_length=1, max_length=100)]] = None
    default_bwp: Omittable[Annotated[int, Field(ge=0)]] = None
    is_default: Omittable[bool] = None


class VerdictRuleReorder(CamelModel):
    ids: list[uuid.UUID]


# ── Description preset schemas ──────────────────────────────────────────────


class DescriptionPresetOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    sort_order: int


class DescriptionPresetCreate(CamelModel):
    text: str = Field(min_length=1, max_length=200)


class DescriptionPresetUpdate(CamelModel):
    text: Omittable[Annotated[str, Field(min_length=1, max_length=200)]] = None


# ── Output schemas ──────────────────────────────────────────────────────────


class IncidentResolutionOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_driver_id: uuid.UUID
    judge_user_id: uuid.UUID | None
    verdict: str
    bwp_points: int | None
    description: str | None
    bwp_applied: bool = Field(description="True once the points were issued to the driver's licence.")
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
    time: str | None = Field(description="Session time of the incident, as text for the judges.")
    lap: str | None
    corner: str | None
    description: str | None
    source: IncidentSource
    status: IncidentStatus
    is_published: bool
    created_at: datetime
    drivers: list[IncidentDriverOut] = []


class IncidentWindowListItem(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    championship_id: int | None
    championship_name: str | None
    race_id: int | None
    race_name: str
    date: str | None = Field(description="The race day as display text, normally `YYYY-MM-DD`.")
    interval_hours: int = Field(description="How long the window accepts incidents after it opens.")
    opened_at: datetime
    closes_at: datetime
    opened_by_user_id: uuid.UUID | None
    is_manually_closed: bool
    is_open: bool


class IncidentWindowOut(IncidentWindowListItem):
    incidents: list[IncidentOut] = []


class ResolveRemainingOut(IncidentWindowOut):
    resolved_count: int = Field(default=0, description="Drivers the default verdict was just applied to.")


class PublishWindowOut(IncidentWindowOut):
    unlinked_count: int = Field(
        default=0,
        description="Penalties that reached no licence because the driver name matches no driver record.",
    )


class BwpBackfillOut(CamelModel):
    fixed: int = Field(description="Penalties that now have a licence point.")
    unmatched: list[str] = Field(description="Names that still match no driver record.")


class BwpAuditEntry(CamelModel):
    incident_driver_id: uuid.UUID
    driver_name: str
    bwp_points: int
    matched_driver_id: uuid.UUID | None = None
    matched_driver_name: str | None = None

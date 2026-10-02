"""Schemas for giveaway eligibility and driver-name aliases."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.base import CamelModel


class RoundBreakdownOut(CamelModel):
    round_key: str
    round_label: str
    car_class: str
    laps: int
    class_leader_laps: int
    distance_pct: float
    qualifies: bool


class EligibleDriverOut(CamelModel):
    identity: str = Field(
        description="Normalized name the driver's rounds are grouped under, aliases applied."
    )
    display_name: str
    car_class: str
    qualifying_rounds: int
    rounds: list[RoundBreakdownOut]


class GiveawayEligibilityOut(CamelModel):
    championship_id: int
    min_distance_pct: float
    min_rounds: int
    imported_rounds: int
    car_classes: list[str]
    drivers: list[EligibleDriverOut]


class UnmatchedDriverNameOut(CamelModel):
    raw_name: str
    normalized_name: str
    rounds: int
    # Never applied automatically: on real data the closest match to
    # "Ars Ilanovich" is "Artur Ivanov", a different driver in the same race.
    suggestions: list[str] = Field(
        description="Ranked spelling hints for the admin; never applied on their own."
    )


class DriverAliasCreate(CamelModel):
    normalized_alias: str = Field(max_length=200)
    canonical_display_name: str = Field(max_length=200)
    driver_id: uuid.UUID | None = None


class DriverAliasOut(CamelModel):
    id: uuid.UUID
    normalized_alias: str
    canonical_normalized_name: str
    canonical_display_name: str
    driver_id: uuid.UUID | None = None
    created_at: datetime

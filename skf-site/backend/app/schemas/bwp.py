import uuid
from datetime import date, datetime

from pydantic import ConfigDict, Field

from app.schemas.championship import CamelModel


# ---------------------------------------------------------------------------
# BwpPoint
# ---------------------------------------------------------------------------
class BwpPointCreate(CamelModel):
    points: int = Field(gt=0)
    issued_on: date
    expires_on: date


class BwpPointOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    points: int
    issued_on: date
    expires_on: date


# ---------------------------------------------------------------------------
# PenaltyClearance
# ---------------------------------------------------------------------------
class PenaltyClearanceOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    driver_id: uuid.UUID
    penalty_rule_id: uuid.UUID
    cleared_at: datetime


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
class DriverCreate(CamelModel):
    name: str = Field(min_length=1, max_length=200)


class DriverOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    points: list[BwpPointOut] = []
    clearances: list[PenaltyClearanceOut] = []


class DriverBrief(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


# ---------------------------------------------------------------------------
# PenaltyRule
# ---------------------------------------------------------------------------
class PenaltyRuleCreate(CamelModel):
    threshold: int = Field(gt=0)
    label: str = ""


class PenaltyRuleUpdate(CamelModel):
    threshold: int | None = Field(default=None, gt=0)
    label: str | None = None


class PenaltyRuleOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    threshold: int
    label: str
    sort_order: int

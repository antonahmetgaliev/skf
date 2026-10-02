import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator

from app.schemas.base import CamelModel, Omittable, Url


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
    note: str | None = None
    expired: bool = Field(default=False, description="True once `expiresOn` is today or earlier.")


class BwpPointUpdate(CamelModel):
    """``PATCH /bwp-points/{id}``: expire a point today (history is kept).

    Only ``expired: true`` is accepted — un-expiring would need the original
    expiry date, which is overwritten.
    """

    expired: Literal[True]
    note: str = Field(default="", max_length=500)


class BwpResetCreate(CamelModel):
    """``POST /drivers/{id}/bwp-resets``: expire every active point."""

    note: str = Field(default="", max_length=500)


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


class DriverUpdate(CamelModel):
    name: Omittable[Annotated[str, Field(min_length=1, max_length=200)]] = None
    # ``null`` unlinks the driver from SimGrid.
    simgrid_driver_id: int | None = None


class DriverBrief(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class DriverPublicOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    simgrid_driver_id: int | None = None
    simgrid_display_name: str | None = None
    country_code: str | None = None
    photo_url: Url | None = None
    created_at: datetime
    active_bwp: int = Field(default=0, description="Sum of the points that have not expired.")
    points: list[BwpPointOut] = []
    clearances: list[PenaltyClearanceOut] = []


class DriverOut(DriverPublicOut):
    """Judge view: the public projection plus the linked site account.

    ``user_id`` has no default on purpose: it keeps the public and judge
    projections distinguishable when ``GET /drivers`` answers with either.
    """

    user_id: uuid.UUID | None


class MyDriverPhotoUpdate(CamelModel):
    """``PATCH /me/driver``: set (https only) or clear the profile photo."""

    photo_url: str | None = Field(default=None, max_length=500, json_schema_extra={"format": "uri"})

    @field_validator("photo_url")
    @classmethod
    def _https_only(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not v.lower().startswith("https://") or len(v) <= len("https://"):
            raise ValueError("Photo URL must start with https://")
        return v


# ---------------------------------------------------------------------------
# PenaltyRule
# ---------------------------------------------------------------------------
class PenaltyRuleCreate(CamelModel):
    threshold: int = Field(gt=0)
    label: str = Field(default="", max_length=500)


class PenaltyRuleUpdate(CamelModel):
    threshold: Omittable[Annotated[int, Field(gt=0)]] = None
    label: Omittable[Annotated[str, Field(max_length=500)]] = None


class PenaltyRuleOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    threshold: int
    label: str
    sort_order: int

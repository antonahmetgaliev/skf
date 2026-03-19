"""Pydantic schemas for DOTD (Driver of the Day) voting."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field

from app.schemas.championship import CamelModel


class DotdCandidateIn(CamelModel):
    simgrid_driver_id: int | None = None
    driver_name: str = Field(..., min_length=1, max_length=200)
    championship_position: int | None = None


class DotdPollCreate(CamelModel):
    championship_id: int
    championship_name: str = Field(..., min_length=1, max_length=200)
    race_id: int | None = None
    race_name: str = Field(..., min_length=1, max_length=200)
    closes_at: datetime
    candidates: list[DotdCandidateIn] = Field(..., min_length=2)


class DotdCandidateOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    simgrid_driver_id: int | None
    driver_name: str
    championship_position: int | None
    vote_count: int | None  # None = hidden (results not visible yet)


class DotdPollOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    championship_id: int
    championship_name: str
    race_id: int | None
    race_name: str
    created_at: datetime
    closes_at: datetime
    is_open: bool
    candidates: list[DotdCandidateOut]
    has_voted: bool
    my_vote_candidate_id: uuid.UUID | None
    total_votes: int

"""Tracks which SimGrid championships are currently active."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bwp import Base


class ActiveChampionship(Base):
    __tablename__ = "active_championships"

    simgrid_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

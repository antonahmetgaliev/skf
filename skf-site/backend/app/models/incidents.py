"""Incident management models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.bwp import Base


class IncidentWindow(Base):
    __tablename__ = "incident_windows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    championship_id: Mapped[int] = mapped_column(Integer, nullable=False)
    championship_name: Mapped[str] = mapped_column(String(200), nullable=False)
    race_id: Mapped[int] = mapped_column(Integer, nullable=False)
    race_name: Mapped[str] = mapped_column(String(200), nullable=False)
    interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opened_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_manually_closed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    incidents: Mapped[list["Incident"]] = relationship(
        back_populates="window",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def is_open(self) -> bool:
        now = datetime.now(timezone.utc)
        closes = self.closes_at
        if closes.tzinfo is None:
            closes = closes.replace(tzinfo=timezone.utc)
        return not self.is_manually_closed and closes > now


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    window_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incident_windows.id", ondelete="CASCADE"),
        nullable=False,
    )
    reporter_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    driver1_name: Mapped[str] = mapped_column(String(200), nullable=False)
    driver1_driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drivers.id", ondelete="SET NULL"),
        nullable=True,
    )
    driver2_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    driver2_driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drivers.id", ondelete="SET NULL"),
        nullable=True,
    )
    lap_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turn: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    window: Mapped["IncidentWindow"] = relationship(back_populates="incidents")

    resolution: Mapped["IncidentResolution | None"] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )


class IncidentResolution(Base):
    __tablename__ = "incident_resolutions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    judge_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    time_penalty_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bwp_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bwp_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    incident: Mapped["Incident"] = relationship(back_populates="resolution")

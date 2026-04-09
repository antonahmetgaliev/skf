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
    championship_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    championship_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    race_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    race_name: Mapped[str] = mapped_column(String(200), nullable=False)
    date: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
    session_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    time: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    window: Mapped["IncidentWindow"] = relationship(back_populates="incidents")

    drivers: Mapped[list["IncidentDriver"]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="IncidentDriver.sort_order",
    )


class IncidentDriver(Base):
    __tablename__ = "incident_drivers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    driver_name: Mapped[str] = mapped_column(String(200), nullable=False)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drivers.id", ondelete="SET NULL"),
        nullable=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    incident: Mapped["Incident"] = relationship(back_populates="drivers")

    resolution: Mapped["IncidentResolution | None"] = relationship(
        back_populates="incident_driver",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )


class IncidentResolution(Base):
    __tablename__ = "incident_resolutions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    incident_driver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incident_drivers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    judge_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    bwp_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    bwp_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    incident_driver: Mapped["IncidentDriver"] = relationship(back_populates="resolution")


class VerdictRule(Base):
    __tablename__ = "verdict_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    verdict: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    default_bwp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DescriptionPreset(Base):
    __tablename__ = "description_presets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    text: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

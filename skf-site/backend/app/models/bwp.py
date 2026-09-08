import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    simgrid_driver_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    simgrid_display_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    country_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    points: Mapped[list["BwpPoint"]] = relationship(
        back_populates="driver", cascade="all, delete-orphan", lazy="selectin"
    )
    clearances: Mapped[list["PenaltyClearance"]] = relationship(
        back_populates="driver", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def active_bwp(self) -> int:
        """Sum of not-yet-expired BWP points (expired = expires_on <= today,
        matching the immediate-expire semantics in the BWP router)."""
        today = date.today()
        return sum(p.points for p in self.points if p.expires_on > today)


# Case-insensitive uniqueness for driver names: "John Smith" and "john smith"
# must not coexist (the sync inserts SimGrid casing directly, bypassing the
# API-level ilike guard).
Index("ux_drivers_name_lower", func.lower(Driver.name), unique=True)


class BwpPoint(Base):
    __tablename__ = "bwp_points"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    driver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False
    )
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    driver: Mapped["Driver"] = relationship(back_populates="points")

    @property
    def expired(self) -> bool:
        return self.expires_on <= date.today()


class PenaltyRule(Base):
    __tablename__ = "penalty_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    clearances: Mapped[list["PenaltyClearance"]] = relationship(
        back_populates="penalty_rule", cascade="all, delete-orphan", lazy="selectin"
    )


class PenaltyClearance(Base):
    __tablename__ = "penalty_clearances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    driver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drivers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    penalty_rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("penalty_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cleared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    driver: Mapped["Driver"] = relationship(back_populates="clearances")
    penalty_rule: Mapped["PenaltyRule"] = relationship(back_populates="clearances")

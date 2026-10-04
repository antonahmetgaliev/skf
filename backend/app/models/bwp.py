import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.user import User


class Base(DeclarativeBase):
    pass


def utc_today() -> date:
    """Today's date in UTC — the reference day for BWP point expiry."""
    return datetime.now(UTC).date()


class Driver(Base):
    """A person who races with us: one SimGrid user, one row.

    ``simgrid_driver_id`` is the identity; two people may share a name. The
    site account of the same person, if they have one, points here through
    ``User.driver_id``.
    """

    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    simgrid_driver_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    simgrid_display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # What SimGrid knows about the person's other accounts; refreshed by the sync.
    discord_uid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    steam64_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )

    points: Mapped[list["BwpPoint"]] = relationship(
        back_populates="driver", cascade="all, delete-orphan", lazy="selectin"
    )
    clearances: Mapped[list["PenaltyClearance"]] = relationship(
        back_populates="driver", cascade="all, delete-orphan", lazy="selectin"
    )
    account: Mapped["User | None"] = relationship(back_populates="driver", uselist=False, lazy="selectin")

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.account.id if self.account else None

    @property
    def active_bwp(self) -> int:
        """Sum of not-yet-expired BWP points (expired = expires_on <= today,
        matching the immediate-expire semantics of ``PATCH /bwp-points``)."""
        today = utc_today()
        return sum(p.points for p in self.points if p.expires_on > today)


# Names are looked up case-insensitively, but are not unique: namesakes exist.
Index("ix_drivers_name_lower", func.lower(Driver.name))


class BwpPoint(Base):
    __tablename__ = "bwp_points"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    driver: Mapped["Driver"] = relationship(back_populates="points")

    @property
    def expired(self) -> bool:
        return self.expires_on <= utc_today()


class PenaltyRule(Base):
    __tablename__ = "penalty_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    clearances: Mapped[list["PenaltyClearance"]] = relationship(
        back_populates="penalty_rule", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )


class PenaltyClearance(Base):
    __tablename__ = "penalty_clearances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    cleared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    driver: Mapped["Driver"] = relationship(back_populates="clearances")
    penalty_rule: Mapped["PenaltyRule"] = relationship(back_populates="clearances")

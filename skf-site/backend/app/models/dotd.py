"""Driver of the Day (DOTD) voting models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.bwp import Base


class DotdPoll(Base):
    __tablename__ = "dotd_polls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    championship_id: Mapped[int] = mapped_column(Integer, nullable=False)
    championship_name: Mapped[str] = mapped_column(String(200), nullable=False)
    race_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    race_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closes_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_manually_closed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    candidates: Mapped[list["DotdCandidate"]] = relationship(
        back_populates="poll",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    votes: Mapped[list["DotdVote"]] = relationship(
        back_populates="poll",
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


class DotdCandidate(Base):
    __tablename__ = "dotd_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    poll_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dotd_polls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    simgrid_driver_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    driver_name: Mapped[str] = mapped_column(String(200), nullable=False)
    championship_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    poll: Mapped["DotdPoll"] = relationship(back_populates="candidates")
    votes: Mapped[list["DotdVote"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class DotdVote(Base):
    __tablename__ = "dotd_votes"

    __table_args__ = (
        UniqueConstraint("poll_id", "user_id", name="uq_dotd_vote_user_poll"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    poll_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dotd_polls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dotd_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    voted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    poll: Mapped["DotdPoll"] = relationship(back_populates="votes")
    candidate: Mapped["DotdCandidate"] = relationship(back_populates="votes")

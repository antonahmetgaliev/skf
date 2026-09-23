"""Race results imported from each round's game-server result file.

SimGrid exposes no per-race results, so laps completed can only come from the
game server's own result file (LMU XML or an iRaceControl .bin for iRacing).
The entries exist purely to decide giveaway eligibility — they are not a
results archive and are never shown publicly. The same upload also seeds the
round's "Auto" incidents, which point back here through `Incident.import_id`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.bwp import Base


def normalize_driver_name(name: str) -> str:
    """Canonical key for a driver name coming out of a result file.

    Game-server names carry inconsistent casing and stray spacing between
    rounds ("Andrii lotochynskyi" vs "Andrii Lotochynskyi"), which would
    otherwise split one person's rounds across two identities and cost them
    the eligibility threshold.
    """
    return " ".join(name.split()).lower()


class RaceResultImport(Base):
    """One uploaded result file, pinned to a championship round."""

    __tablename__ = "race_result_imports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    championship_simgrid_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    race_simgrid_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_event: Mapped[str | None] = mapped_column(String(300), nullable=True)
    session_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # "lmu" or "iracing", from the championship's SimGrid game.
    sim: Mapped[str] = mapped_column(
        String(20), nullable=False, default="lmu", server_default="lmu"
    )
    # Object key of the original file in the bucket; None when storage was
    # not configured at upload time.
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contacts_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # iRacing subsession id, for reference; LMU files carry none.
    external_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # iRaceControl recorded without grouping, so contacts were regrouped here.
    auto_grouped: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    entries: Mapped[list["RaceResultEntry"]] = relationship(
        back_populates="race_import", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        # One import per round, so re-uploading a corrected file replaces the
        # old one instead of double-counting the round.
        UniqueConstraint(
            "championship_simgrid_id",
            "race_simgrid_id",
            name="uq_race_result_imports_round",
        ),
    )


class RaceResultEntry(Base):
    """One driver's outcome in an imported round."""

    __tablename__ = "race_result_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("race_result_imports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    car_class: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    laps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    class_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Kept for reference only: the agreed rule counts distance alone, so a DNF
    # or DQ never removes a round on its own.
    finish_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True
    )

    race_import: Mapped[RaceResultImport] = relationship(back_populates="entries")


Index("ix_race_result_entries_normalized_name", RaceResultEntry.normalized_name)


class GiveawayNameAlias(Base):
    """An admin-confirmed merge of two spellings of the same driver.

    Automatic fuzzy matching is deliberately not applied: on the sample data it
    proposes "Ars Ilanovich" -> "Artur Ivanov", two different people who raced
    each other. Suggestions are offered in the UI, but only an admin decision
    is ever written here.
    """

    __tablename__ = "giveaway_name_aliases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    normalized_alias: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True
    )
    canonical_normalized_name: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True
    )
    canonical_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

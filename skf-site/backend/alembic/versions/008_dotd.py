"""Driver of the Day voting tables

Revision ID: 004
Revises: 003
Create Date: 2026-03-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dotd_polls",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("championship_id", sa.Integer, nullable=False),
        sa.Column("championship_name", sa.String(200), nullable=False),
        sa.Column("race_id", sa.Integer, nullable=True),
        sa.Column("race_name", sa.String(200), nullable=False),
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_manually_closed",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "dotd_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "poll_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dotd_polls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("simgrid_driver_id", sa.Integer, nullable=True),
        sa.Column("driver_name", sa.String(200), nullable=False),
        sa.Column("championship_position", sa.Integer, nullable=True),
    )
    op.create_index("ix_dotd_candidates_poll_id", "dotd_candidates", ["poll_id"])

    op.create_table(
        "dotd_votes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "poll_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dotd_polls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dotd_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "voted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("poll_id", "user_id", name="uq_dotd_vote_user_poll"),
    )
    op.create_index("ix_dotd_votes_poll_id", "dotd_votes", ["poll_id"])
    op.create_index("ix_dotd_votes_user_id", "dotd_votes", ["user_id"])


def downgrade() -> None:
    op.drop_table("dotd_votes")
    op.drop_table("dotd_candidates")
    op.drop_table("dotd_polls")

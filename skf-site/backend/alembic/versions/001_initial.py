"""initial tables

Revision ID: 001
Revises:
Create Date: 2026-02-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drivers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "bwp_points",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "driver_id",
            UUID(as_uuid=True),
            sa.ForeignKey("drivers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("points", sa.Integer, nullable=False),
        sa.Column("issued_on", sa.Date, nullable=False),
        sa.Column("expires_on", sa.Date, nullable=False),
    )
    op.create_index("ix_bwp_points_driver_id", "bwp_points", ["driver_id"])

    op.create_table(
        "penalty_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("threshold", sa.Integer, nullable=False),
        sa.Column("label", sa.Text, nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("penalty_rules")
    op.drop_table("bwp_points")
    op.drop_table("drivers")

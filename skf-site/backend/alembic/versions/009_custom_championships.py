"""Custom championships and races tables for calendar

Revision ID: 009
Revises: 008
Create Date: 2026-03-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "custom_championships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("game", sa.String(100), nullable=False),
        sa.Column("car_class", sa.String(100), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "is_visible",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
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
    )

    op.create_table(
        "custom_races",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "championship_id",
            UUID(as_uuid=True),
            sa.ForeignKey("custom_championships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("track", sa.String(200), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_custom_races_championship_id", "custom_races", ["championship_id"]
    )
    op.create_index("ix_custom_races_date", "custom_races", ["date"])


def downgrade() -> None:
    op.drop_table("custom_races")
    op.drop_table("custom_championships")

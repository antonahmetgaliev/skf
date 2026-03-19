"""Add incident management tables and racing_judge role.

Revision ID: 007
Revises: 006
Create Date: 2026-03-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO roles (name) VALUES ('racing_judge') ON CONFLICT (name) DO NOTHING"
    )

    op.create_table(
        "incident_windows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("championship_id", sa.Integer(), nullable=False),
        sa.Column("championship_name", sa.String(200), nullable=False),
        sa.Column("race_id", sa.Integer(), nullable=False),
        sa.Column("race_name", sa.String(200), nullable=False),
        sa.Column(
            "interval_hours", sa.Integer(), nullable=False, server_default="24"
        ),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "opened_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_manually_closed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "incidents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "window_id",
            UUID(as_uuid=True),
            sa.ForeignKey("incident_windows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reporter_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("driver1_name", sa.String(200), nullable=False),
        sa.Column(
            "driver1_driver_id",
            UUID(as_uuid=True),
            sa.ForeignKey("drivers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("driver2_name", sa.String(200), nullable=True),
        sa.Column(
            "driver2_driver_id",
            UUID(as_uuid=True),
            sa.ForeignKey("drivers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("lap_number", sa.Integer(), nullable=True),
        sa.Column("turn", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "incident_resolutions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            UUID(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "judge_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("time_penalty_seconds", sa.Integer(), nullable=True),
        sa.Column("bwp_points", sa.Integer(), nullable=True),
        sa.Column(
            "bwp_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("incident_resolutions")
    op.drop_table("incidents")
    op.drop_table("incident_windows")
    op.execute("DELETE FROM roles WHERE name = 'racing_judge'")

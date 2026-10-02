"""Rework incidents: N-driver support, per-driver resolution

Revision ID: 012
Revises: 011
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # Drop old tables (clean slate — data intentionally discarded)
    if "incident_resolutions" in existing:
        op.drop_table("incident_resolutions")
    if "incidents" in existing:
        op.drop_table("incidents")

    # Make incident_windows columns nullable for ingestion-created windows
    # (championship_id / championship_name / race_id were NOT NULL before)
    if "incident_windows" in existing:
        op.alter_column(
            "incident_windows", "championship_id",
            existing_type=sa.Integer(), nullable=True,
        )
        op.alter_column(
            "incident_windows", "championship_name",
            existing_type=sa.String(200), nullable=True,
        )
        op.alter_column(
            "incident_windows", "race_id",
            existing_type=sa.Integer(), nullable=True,
        )
        # Add date column only if it doesn't already exist
        cols = {c["name"] for c in inspector.get_columns("incident_windows")}
        if "date" not in cols:
            op.add_column(
                "incident_windows",
                sa.Column("date", sa.String(20), nullable=True),
            )

    # Create new tables unconditionally — we just dropped incidents &
    # incident_resolutions above, and incident_drivers is brand-new.
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
        sa.Column("session_name", sa.String(100), nullable=True),
        sa.Column("time", sa.String(50), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "incident_drivers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            UUID(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("driver_name", sa.String(200), nullable=False),
        sa.Column(
            "driver_id",
            UUID(as_uuid=True),
            sa.ForeignKey("drivers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "incident_resolutions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_driver_id",
            UUID(as_uuid=True),
            sa.ForeignKey("incident_drivers.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "judge_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("verdict", sa.Text, nullable=False),
        sa.Column("bwp_points", sa.Integer, nullable=True),
        sa.Column(
            "bwp_applied",
            sa.Boolean,
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
    op.drop_table("incident_drivers")
    op.drop_table("incidents")

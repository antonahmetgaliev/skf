"""Add end_date column to custom_races for multi-day races.

Revision ID: 023
Revises: 022
"""

from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"


def upgrade() -> None:
    op.add_column(
        "custom_races",
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("custom_races", "end_date")

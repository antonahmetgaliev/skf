"""Add note column to bwp_points

Revision ID: 026
Revises: 025
Create Date: 2026-05-05
"""

from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bwp_points",
        sa.Column("note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bwp_points", "note")

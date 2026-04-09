"""Add source column to incidents.

Revision ID: 017
Revises: 016
"""

from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column("source", sa.String(20), nullable=False, server_default="filed"),
    )


def downgrade() -> None:
    op.drop_column("incidents", "source")

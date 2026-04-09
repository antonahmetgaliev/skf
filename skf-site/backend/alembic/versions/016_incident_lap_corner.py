"""Add lap and corner columns to incidents.

Revision ID: 016
Revises: 015
"""

from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("lap", sa.String(20), nullable=True))
    op.add_column("incidents", sa.Column("corner", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("incidents", "corner")
    op.drop_column("incidents", "lap")

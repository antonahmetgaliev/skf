"""Add description_presets table with seed data.

Revision ID: 015
Revises: 014
"""

from alembic import op
import sqlalchemy as sa
from uuid import uuid4

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None

SEEDS = [
    "Avoidable contact",
    "Avoidable contact (position returned)",
    "Unsafe rejoin",
    "Racing incident",
    "Braking mistake",
    "Forcing off track",
    "Dangerous driving",
]


def upgrade() -> None:
    table = op.create_table(
        "description_presets",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("text", sa.String(200), nullable=False, unique=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.bulk_insert(
        table,
        [{"id": str(uuid4()), "text": text, "sort_order": i} for i, text in enumerate(SEEDS)],
    )


def downgrade() -> None:
    op.drop_table("description_presets")

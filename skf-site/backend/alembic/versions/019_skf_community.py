"""Add is_skf flag to communities and seed SKF community.

Revision ID: 019
Revises: 018
"""

import uuid

from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None

SKF_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    op.add_column(
        "communities",
        sa.Column("is_skf", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # Seed the predefined SKF community (ON CONFLICT for idempotency)
    op.execute(
        sa.text(
            "INSERT INTO communities (id, name, color, is_skf) "
            "VALUES (:id, :name, :color, true) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(
            id=str(SKF_ID),
            name="SKF",
            color="#f5bf24",
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM communities WHERE is_skf = true"))
    op.drop_column("communities", "is_skf")

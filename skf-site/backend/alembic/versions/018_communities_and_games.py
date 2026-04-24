"""Add communities and games tables, link custom championships.

Revision ID: 018
Revises: 017
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "communities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("color", sa.String(20), nullable=True),
        sa.Column("discord_url", sa.String(500), nullable=True),
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "games",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.add_column(
        "custom_championships",
        sa.Column(
            "community_id",
            UUID(as_uuid=True),
            sa.ForeignKey("communities.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_custom_championships_community_id", "custom_championships", ["community_id"])

    op.add_column(
        "custom_championships",
        sa.Column(
            "game_id",
            UUID(as_uuid=True),
            sa.ForeignKey("games.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_custom_championships_game_id", "custom_championships", ["game_id"])


def downgrade() -> None:
    op.drop_index("ix_custom_championships_game_id", "custom_championships")
    op.drop_column("custom_championships", "game_id")
    op.drop_index("ix_custom_championships_community_id", "custom_championships")
    op.drop_column("custom_championships", "community_id")
    op.drop_table("games")
    op.drop_table("communities")

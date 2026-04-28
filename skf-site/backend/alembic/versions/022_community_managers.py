"""Add community_managers table and community_manager role.

Revision ID: 022
Revises: 021
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community_managers",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("community_id", UUID(as_uuid=True), sa.ForeignKey("communities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.execute(
        "INSERT INTO roles (name) VALUES ('community_manager') ON CONFLICT (name) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("community_managers")
    op.execute("DELETE FROM roles WHERE name = 'community_manager'")

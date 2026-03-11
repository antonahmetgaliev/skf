"""Add guild_nickname column to users table.

Revision ID: 005
Revises: 004
Create Date: 2026-03-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("guild_nickname", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "guild_nickname")

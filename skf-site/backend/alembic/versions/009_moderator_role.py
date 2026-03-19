"""Add moderator role

Revision ID: 009
Revises: 008
Create Date: 2026-03-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("INSERT INTO roles (name) VALUES ('moderator') ON CONFLICT (name) DO NOTHING")


def downgrade() -> None:
    op.execute("DELETE FROM roles WHERE name = 'moderator'")

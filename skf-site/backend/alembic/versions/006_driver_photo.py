"""add photo_url to drivers

Revision ID: 004
Revises: 003
Create Date: 2026-03-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("drivers", sa.Column("photo_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("drivers", "photo_url")

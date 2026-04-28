"""Shift custom_races.date by -3 hours (admins entered local UTC+3, stored as UTC).

Revision ID: 021
Revises: 020
"""

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE custom_races
        SET date = date - INTERVAL '3 hours'
        WHERE date IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE custom_races
        SET date = date + INTERVAL '3 hours'
        WHERE date IS NOT NULL
        """
    )

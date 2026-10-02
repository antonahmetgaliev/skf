"""Add verdict_rules table with seed data.

Revision ID: 013
Revises: 012
"""

from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "verdict_rules",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("verdict", sa.String(100), nullable=False, unique=True),
        sa.Column("default_bwp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )

    op.bulk_insert(table, [
        {"verdict": "NFA",                        "default_bwp": 0, "sort_order": 1},
        {"verdict": "Racing incident",            "default_bwp": 0, "sort_order": 2},
        {"verdict": "Warning",                    "default_bwp": 1, "sort_order": 3},
        {"verdict": "TP +5s",                     "default_bwp": 2, "sort_order": 4},
        {"verdict": "TP +10s",                    "default_bwp": 2, "sort_order": 5},
        {"verdict": "TP +15s",                    "default_bwp": 4, "sort_order": 6},
        {"verdict": "TP +20s",                    "default_bwp": 4, "sort_order": 7},
        {"verdict": "TP +30s",                    "default_bwp": 4, "sort_order": 8},
        {"verdict": "DT",                         "default_bwp": 6, "sort_order": 9},
        {"verdict": "SG10",                       "default_bwp": 6, "sort_order": 10},
        {"verdict": "SG30",                       "default_bwp": 6, "sort_order": 11},
        {"verdict": "Need Further Investigation", "default_bwp": 0, "sort_order": 12},
    ])


def downgrade() -> None:
    op.drop_table("verdict_rules")

"""Index foreign keys that pages look up by.

Loading a round reads its incidents by ``window_id`` and their drivers by
``incident_id``; driver pages and the BWP backfill filter by ``driver_id``.
``IF NOT EXISTS`` because older databases were partly built by ``create_all``.

Revision ID: 033
Revises: 032
"""

from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None

INDEXES = [
    ("community_managers", "community_id"),
    ("incident_drivers", "driver_id"),
    ("incident_drivers", "incident_id"),
    ("incidents", "window_id"),
    ("race_result_entries", "driver_id"),
]


def upgrade() -> None:
    for table, column in INDEXES:
        op.create_index(f"ix_{table}_{column}", table, [column], if_not_exists=True)


def downgrade() -> None:
    for table, column in INDEXES:
        op.drop_index(f"ix_{table}_{column}", table_name=table, if_exists=True)

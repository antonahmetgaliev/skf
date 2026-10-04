"""A driver is one SimGrid user; the account points at its driver.

* The account-to-driver link moves from ``drivers.user_id`` to
  ``users.driver_id`` and records who made it.
* Driver names stop being unique: SimGrid's id is the identity, and namesakes
  were silently dropped by the sync.
* Drivers keep the Discord and Steam ids SimGrid reports for them.

``simgrid_driver_id`` becomes mandatory and unique in a later revision, once
the rows without one have been cleaned up in the admin panel.

Revision ID: 035
Revises: 034
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("drivers", sa.Column("discord_uid", sa.String(length=64), nullable=True))
    op.add_column("drivers", sa.Column("steam64_id", sa.String(length=32), nullable=True))
    op.add_column("drivers", sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_drivers_discord_uid", "drivers", ["discord_uid"])

    op.add_column(
        "users",
        sa.Column(
            "driver_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drivers.id", ondelete="SET NULL", name="fk_users_driver_id"),
            nullable=True,
        ),
    )
    op.add_column("users", sa.Column("driver_link_source", sa.String(length=20), nullable=True))
    op.execute(
        """
        UPDATE users
        SET driver_id = d.id, driver_link_source = 'simgrid'
        FROM drivers d
        WHERE d.user_id = users.id
        """
    )
    op.create_unique_constraint("uq_users_driver_id", "users", ["driver_id"])

    # Older databases were partly built by create_all, so names can differ.
    op.execute("ALTER TABLE drivers DROP CONSTRAINT IF EXISTS uq_drivers_user_id")
    op.drop_column("drivers", "user_id")

    op.execute("ALTER TABLE drivers DROP CONSTRAINT IF EXISTS drivers_name_key")
    op.execute("DROP INDEX IF EXISTS ux_drivers_name_lower")
    op.create_index("ix_drivers_name_lower", "drivers", [sa.text("lower(name)")])


def downgrade() -> None:
    # Namesakes may exist by now, so name uniqueness is not restored.
    op.drop_index("ix_drivers_name_lower", table_name="drivers")

    op.add_column(
        "drivers",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute("UPDATE drivers SET user_id = u.id FROM users u WHERE u.driver_id = drivers.id")
    op.create_unique_constraint("uq_drivers_user_id", "drivers", ["user_id"])

    op.drop_constraint("uq_users_driver_id", "users", type_="unique")
    op.drop_column("users", "driver_link_source")
    op.drop_column("users", "driver_id")

    op.drop_index("ix_drivers_discord_uid", table_name="drivers")
    op.drop_column("drivers", "synced_at")
    op.drop_column("drivers", "steam64_id")
    op.drop_column("drivers", "discord_uid")

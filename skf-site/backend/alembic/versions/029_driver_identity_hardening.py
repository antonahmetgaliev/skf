"""Driver identity hardening

- incident_resolutions.applied_bwp_point_id: lets discard undo apply-bwp
- case-insensitive unique index on drivers.name (dedup existing rows first)

Revision ID: 029
Revises: 028
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "incident_resolutions",
        sa.Column("applied_bwp_point_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_incident_resolutions_applied_bwp_point",
        "incident_resolutions",
        "bwp_points",
        ["applied_bwp_point_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Case-variant duplicate names ("John Smith" / "john smith") were possible
    # because the sync inserted raw SimGrid casing past the case-sensitive
    # UNIQUE. Rename later duplicates with a numeric suffix so the
    # case-insensitive unique index can be created.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   name,
                   ROW_NUMBER() OVER (
                       PARTITION BY lower(name) ORDER BY created_at, id
                   ) AS rn
            FROM drivers
        )
        UPDATE drivers d
        SET name = d.name || ' (' || ranked.rn || ')'
        FROM ranked
        WHERE d.id = ranked.id AND ranked.rn > 1
        """
    )
    op.create_index(
        "ux_drivers_name_lower",
        "drivers",
        [sa.text("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_drivers_name_lower", table_name="drivers")
    op.drop_constraint(
        "fk_incident_resolutions_applied_bwp_point",
        "incident_resolutions",
        type_="foreignkey",
    )
    op.drop_column("incident_resolutions", "applied_bwp_point_id")

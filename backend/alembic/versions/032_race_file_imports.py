"""Multi-simulator race-file imports that also seed Auto incidents.

One upload per round now feeds the giveaway and the stewards: the original
file is kept in a bucket, and ingested incidents point back at the import
they came from. A round has at most one incident window.

Revision ID: 032
Revises: 031
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "race_result_imports",
        sa.Column("sim", sa.String(length=20), nullable=False, server_default="lmu"),
    )
    op.add_column(
        "race_result_imports",
        sa.Column("storage_key", sa.String(length=500), nullable=True),
    )
    op.add_column("race_result_imports", sa.Column("file_size", sa.Integer(), nullable=True))
    op.add_column(
        "race_result_imports",
        sa.Column("contacts_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "race_result_imports",
        sa.Column("external_session_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "race_result_imports",
        sa.Column("auto_grouped", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column(
        "incidents",
        sa.Column(
            "import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("race_result_imports.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_incidents_import_id", "incidents", ["import_id"])

    # Production has one window per race already; this makes it a guarantee.
    op.create_index(
        "ix_incident_windows_race_id", "incident_windows", ["race_id"], unique=True
    )
    op.create_index(
        "ix_incident_windows_championship_id", "incident_windows", ["championship_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_incident_windows_championship_id", table_name="incident_windows")
    op.drop_index("ix_incident_windows_race_id", table_name="incident_windows")
    op.drop_index("ix_incidents_import_id", table_name="incidents")
    op.drop_column("incidents", "import_id")
    for column in (
        "auto_grouped",
        "external_session_id",
        "contacts_count",
        "file_size",
        "storage_key",
        "sim",
    ):
        op.drop_column("race_result_imports", column)

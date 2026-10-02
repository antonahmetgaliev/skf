"""Store game-server race results and name merges for the giveaway.

SimGrid exposes no per-race results, so laps completed — the one figure the
giveaway regulation needs — is imported from the game server's own XML.

Revision ID: 031
Revises: 030
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "race_result_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("championship_simgrid_id", sa.Integer(), nullable=False),
        sa.Column("race_simgrid_id", sa.Integer(), nullable=True),
        sa.Column("track_event", sa.String(length=300), nullable=True),
        sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_filename", sa.String(length=300), nullable=True),
        sa.Column(
            "uploaded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Re-uploading a corrected file must replace the round, never add a
        # second copy that would double-count it.
        sa.UniqueConstraint(
            "championship_simgrid_id",
            "race_simgrid_id",
            name="uq_race_result_imports_round",
        ),
    )
    op.create_index(
        "ix_race_result_imports_championship_simgrid_id",
        "race_result_imports",
        ["championship_simgrid_id"],
    )

    op.create_table(
        "race_result_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("race_result_imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("car_class", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("laps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("class_position", sa.Integer(), nullable=True),
        sa.Column("finish_status", sa.String(length=100), nullable=True),
        sa.Column(
            "driver_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drivers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_race_result_entries_import_id", "race_result_entries", ["import_id"]
    )
    op.create_index(
        "ix_race_result_entries_normalized_name",
        "race_result_entries",
        ["normalized_name"],
    )

    op.create_table(
        "giveaway_name_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("normalized_alias", sa.String(length=200), nullable=False, unique=True),
        sa.Column("canonical_normalized_name", sa.String(length=200), nullable=False),
        sa.Column("canonical_display_name", sa.String(length=200), nullable=False),
        sa.Column(
            "driver_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drivers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_giveaway_name_aliases_canonical",
        "giveaway_name_aliases",
        ["canonical_normalized_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_giveaway_name_aliases_canonical", table_name="giveaway_name_aliases"
    )
    op.drop_table("giveaway_name_aliases")
    op.drop_index(
        "ix_race_result_entries_normalized_name", table_name="race_result_entries"
    )
    op.drop_index("ix_race_result_entries_import_id", table_name="race_result_entries")
    op.drop_table("race_result_entries")
    op.drop_index(
        "ix_race_result_imports_championship_simgrid_id",
        table_name="race_result_imports",
    )
    op.drop_table("race_result_imports")

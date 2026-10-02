"""Add is_default to verdict_rules; default new incidents to unpublished.

Revision ID: 030
Revises: 029
"""

from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── The default verdict becomes a first-class concept ───────────────────
    op.add_column(
        "verdict_rules",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Backfill exactly one default. This is the ONLY place in the codebase
    # where the literal 'nfa' is allowed: a one-time data migration, not
    # runtime logic. If a league already renamed it, the fallback picks the
    # cheapest / earliest rule, which is the right guess.
    op.execute(
        """
        UPDATE verdict_rules SET is_default = true WHERE id = (
            SELECT id FROM verdict_rules
            ORDER BY (CASE WHEN lower(verdict) = 'nfa' THEN 0 ELSE 1 END),
                     default_bwp,
                     sort_order
            LIMIT 1
        )
        """
    )

    # "At most one default" guaranteed by the database, not by app code.
    op.create_index(
        "uq_verdict_rules_single_default",
        "verdict_rules",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    # ── Verdict visibility becomes a property of the window ────────────────
    # Ingested incidents already started unpublished while manually filed ones
    # started published, so a single window could hold a mixed state. Nothing
    # is hidden before a verdict exists, so defaulting everything to false
    # loses nothing and lets one banner speak for the whole round.
    op.alter_column(
        "incidents",
        "is_published",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("false"),
    )


def downgrade() -> None:
    op.alter_column(
        "incidents",
        "is_published",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("true"),
    )
    op.drop_index("uq_verdict_rules_single_default", table_name="verdict_rules")
    op.drop_column("verdict_rules", "is_default")

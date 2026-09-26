"""Create tables that used to exist only through Base.metadata.create_all.

roles, languages, translations and penalty_clearances were never created by a
migration, and users.role (string) was replaced by users.role_id outside
Alembic. This revision reproduces that schema so the chain can build a fresh
database. Every step is guarded, so it is a no-op on databases that already
have these objects (production is past this revision and never runs it).

Revision ID: 006a
Revises: 006
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "006a"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLES = ("driver", "admin", "super_admin")


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "roles" not in tables:
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(50), nullable=False, unique=True),
        )
    for name in ROLES:
        op.execute(
            sa.text("INSERT INTO roles (name) VALUES (:n) ON CONFLICT (name) DO NOTHING").bindparams(n=name)
        )

    user_cols = {c["name"] for c in insp.get_columns("users")}
    if "role_id" not in user_cols:
        op.add_column("users", sa.Column("role_id", sa.Integer, nullable=True))
        if "role" in user_cols:
            op.execute("INSERT INTO roles (name) SELECT DISTINCT role FROM users ON CONFLICT (name) DO NOTHING")
            op.execute("UPDATE users SET role_id = roles.id FROM roles WHERE roles.name = users.role")
        op.execute("UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'driver') WHERE role_id IS NULL")
        op.alter_column("users", "role_id", nullable=False)
        op.create_foreign_key("users_role_id_fkey", "users", "roles", ["role_id"], ["id"])
    if "role" in user_cols:
        op.drop_column("users", "role")

    # Production's users/sessions came from create_all, not 003: no column
    # defaults, NOT NULL timestamps, and uniqueness only via ix_users_discord_id.
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_discord_id_key")
    op.alter_column("users", "display_name", server_default=None)
    op.alter_column("users", "blocked", server_default=None)
    op.alter_column("users", "created_at", nullable=False)
    op.alter_column("sessions", "created_at", nullable=False)

    if "languages" not in tables:
        op.create_table(
            "languages",
            sa.Column("code", sa.String(10), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("is_active", sa.Boolean, nullable=False),
        )

    if "translations" not in tables:
        op.create_table(
            "translations",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "lang",
                sa.String(10),
                sa.ForeignKey("languages.code", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("key", sa.String(255), nullable=False),
            sa.Column("value", sa.Text, nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("lang", "key", name="uq_translation_lang_key"),
        )
        op.create_index("ix_translations_lang", "translations", ["lang"])
        op.create_index("ix_translations_key", "translations", ["key"])

    if "penalty_clearances" not in tables:
        op.create_table(
            "penalty_clearances",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "driver_id",
                UUID(as_uuid=True),
                sa.ForeignKey("drivers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "penalty_rule_id",
                UUID(as_uuid=True),
                sa.ForeignKey("penalty_rules.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("cleared_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_penalty_clearances_driver_id", "penalty_clearances", ["driver_id"])
        op.create_index("ix_penalty_clearances_penalty_rule_id", "penalty_clearances", ["penalty_rule_id"])


def downgrade() -> None:
    op.drop_table("penalty_clearances")
    op.drop_table("translations")
    op.drop_table("languages")
    op.alter_column("sessions", "created_at", nullable=True)
    op.alter_column("users", "created_at", nullable=True)
    op.alter_column("users", "blocked", server_default=sa.text("false"))
    op.alter_column("users", "display_name", server_default="")
    op.create_unique_constraint("users_discord_id_key", "users", ["discord_id"])
    op.add_column("users", sa.Column("role", sa.String(20), nullable=False, server_default="driver"))
    op.execute("UPDATE users SET role = roles.name FROM roles WHERE roles.id = users.role_id")
    op.drop_constraint("users_role_id_fkey", "users", type_="foreignkey")
    op.drop_column("users", "role_id")
    op.drop_table("roles")

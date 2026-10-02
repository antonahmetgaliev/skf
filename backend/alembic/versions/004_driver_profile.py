"""driver profile columns

Revision ID: 004
Revises: 003
Create Date: 2026-03-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("drivers", sa.Column("simgrid_driver_id", sa.Integer(), nullable=True))
    op.add_column("drivers", sa.Column("simgrid_display_name", sa.String(200), nullable=True))
    op.add_column("drivers", sa.Column("country_code", sa.String(10), nullable=True))
    op.add_column(
        "drivers",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_drivers_simgrid_driver_id", "drivers", ["simgrid_driver_id"])
    op.create_unique_constraint("uq_drivers_user_id", "drivers", ["user_id"])
    op.create_foreign_key(
        "fk_drivers_user_id",
        "drivers",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_drivers_user_id", "drivers", type_="foreignkey")
    op.drop_constraint("uq_drivers_user_id", "drivers", type_="unique")
    op.drop_index("ix_drivers_simgrid_driver_id", table_name="drivers")
    op.drop_column("drivers", "user_id")
    op.drop_column("drivers", "country_code")
    op.drop_column("drivers", "simgrid_display_name")
    op.drop_column("drivers", "simgrid_driver_id")

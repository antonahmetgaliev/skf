"""Add regulation_pages and regulation_contents tables.

Revision ID: 024
Revises: 023
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "024"
down_revision = "023"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    if "regulation_pages" not in existing:
        op.create_table(
            "regulation_pages",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("slug", sa.String(100), nullable=False, unique=True, index=True),
            sa.Column("sort_order", sa.Integer, default=0),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "regulation_contents" not in existing:
        op.create_table(
            "regulation_contents",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "page_id",
                UUID(as_uuid=True),
                sa.ForeignKey("regulation_pages.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "lang",
                sa.String(10),
                sa.ForeignKey("languages.code", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("subtitle", sa.String(500), nullable=False, server_default=""),
            sa.Column("content", sa.Text, nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("page_id", "lang", name="uq_regulation_content_page_lang"),
        )


def downgrade() -> None:
    op.drop_table("regulation_contents")
    op.drop_table("regulation_pages")

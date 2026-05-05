"""Rename language code uk -> ua

Revision ID: 011
Revises: 010
Create Date: 2026-05-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Temporarily drop FK constraints, rename, then re-add
    op.execute("ALTER TABLE translations DROP CONSTRAINT IF EXISTS translations_lang_fkey")
    op.execute("ALTER TABLE regulation_contents DROP CONSTRAINT IF EXISTS regulation_contents_lang_fkey")
    op.execute("UPDATE translations SET lang = 'ua' WHERE lang = 'uk'")
    op.execute("UPDATE regulation_contents SET lang = 'ua' WHERE lang = 'uk'")
    op.execute("UPDATE languages SET code = 'ua' WHERE code = 'uk'")
    op.execute("ALTER TABLE translations ADD CONSTRAINT translations_lang_fkey FOREIGN KEY (lang) REFERENCES languages(code) ON DELETE CASCADE")
    op.execute("ALTER TABLE regulation_contents ADD CONSTRAINT regulation_contents_lang_fkey FOREIGN KEY (lang) REFERENCES languages(code) ON DELETE CASCADE")


def downgrade() -> None:
    op.execute("ALTER TABLE translations DROP CONSTRAINT IF EXISTS translations_lang_fkey")
    op.execute("ALTER TABLE regulation_contents DROP CONSTRAINT IF EXISTS regulation_contents_lang_fkey")
    op.execute("UPDATE languages SET code = 'uk' WHERE code = 'ua'")
    op.execute("UPDATE translations SET lang = 'uk' WHERE lang = 'ua'")
    op.execute("UPDATE regulation_contents SET lang = 'uk' WHERE lang = 'ua'")
    op.execute("ALTER TABLE translations ADD CONSTRAINT translations_lang_fkey FOREIGN KEY (lang) REFERENCES languages(code) ON DELETE CASCADE")
    op.execute("ALTER TABLE regulation_contents ADD CONSTRAINT regulation_contents_lang_fkey FOREIGN KEY (lang) REFERENCES languages(code) ON DELETE CASCADE")

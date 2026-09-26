"""Schema bootstrap and reference-data seeding run at application startup."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

import app.models  # noqa: F401 – ensure all models are registered
from app.database import async_session, engine
from app.models.bwp import Base
from app.models.regulation import RegulationContent, RegulationPage
from app.models.translation import Language, Translation
from app.models.user import (
    ROLE_ADMIN,
    ROLE_COMMUNITY_MANAGER,
    ROLE_DRIVER,
    ROLE_JUDGE,
    ROLE_MODERATOR,
    ROLE_SUPER_ADMIN,
    Role,
)

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
DEFAULT_LANGUAGES = [("en", "English"), ("ua", "Українська")]
ALL_ROLES = (ROLE_DRIVER, ROLE_MODERATOR, ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_JUDGE, ROLE_COMMUNITY_MANAGER)


async def ensure_tables() -> None:
    # Some tables (roles, languages, translations, penalty_clearances) exist
    # only through this call, not through Alembic. Keep it until the
    # migration chain can build the schema on its own.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured")


async def seed_roles() -> None:
    async with async_session() as session:
        existing = set((await session.execute(select(Role.name))).scalars().all())
        for name in ALL_ROLES:
            if name not in existing:
                session.add(Role(name=name))
                logger.info("Seeded role: %s", name)
        await session.commit()


async def seed_languages() -> None:
    async with async_session() as session:
        for code, name in DEFAULT_LANGUAGES:
            if await session.get(Language, code) is None:
                session.add(Language(code=code, name=name, is_active=True))
                logger.info("Seeded language: %s", code)
        await session.commit()


async def seed_translations() -> None:
    """Insert translation keys the seed files know but the database does not.

    Keys an admin has since edited in the UI are left alone; only genuinely
    missing ones are inserted, so this is safe to run on every start.
    """
    async with async_session() as session:
        for code, _ in DEFAULT_LANGUAGES:
            seed_file = SEED_DIR / f"translations_{code}.json"
            if not seed_file.exists():
                continue
            data = json.loads(seed_file.read_text(encoding="utf-8"))
            existing = await session.execute(select(Translation.key).where(Translation.lang == code))
            missing = set(data) - set(existing.scalars().all())
            if not missing:
                continue
            stmt = pg_insert(Translation).values(
                [{"lang": code, "key": k, "value": data[k]} for k in sorted(missing)]
            )
            await session.execute(stmt.on_conflict_do_nothing())
            logger.info("Seeded %d new translations for '%s'", len(missing), code)
        await session.commit()


async def seed_regulations() -> None:
    """Seed regulation pages from JSON when the table is empty."""
    async with async_session() as session:
        if (await session.execute(select(RegulationPage.id).limit(1))).first() is not None:
            return
        seed_file = SEED_DIR / "regulations_en.json"
        if not seed_file.exists():
            return
        data = json.loads(seed_file.read_text(encoding="utf-8"))
        for slug, entry in data.items():
            page = RegulationPage(id=uuid.uuid4(), slug=slug, sort_order=entry.get("sort_order", 0))
            page.contents.append(
                RegulationContent(
                    lang="en",
                    title=entry["title"],
                    subtitle=entry.get("subtitle", ""),
                    content=entry.get("content", ""),
                )
            )
            session.add(page)
        await session.commit()
        logger.info("Seeded %d regulation pages", len(data))


async def backfill_window_names() -> None:
    """Runs in the background: it calls SimGrid and must not delay startup."""
    from app.services.race_import import backfill_window_championship_names

    try:
        async with async_session() as session:
            updated = await backfill_window_championship_names(session)
        if updated:
            logger.info("Backfilled championship names on %d incident windows", updated)
    except Exception:  # noqa: BLE001 - best effort
        logger.exception("Championship name backfill failed")


async def run() -> None:
    await ensure_tables()
    await seed_roles()
    await seed_languages()
    await seed_translations()
    await seed_regulations()

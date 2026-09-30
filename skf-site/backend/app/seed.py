"""Reference-data seeding run at application startup (schema comes from Alembic)."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

import app.models  # noqa: F401 – ensure all models are registered
from app.database import async_session
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
    """Sync each seeded language's keys with its seed file.

    Missing keys are inserted and keys the file no longer has (removed
    features) are deleted. Values an admin has edited in the UI are left
    alone, so this is safe to run on every start. The seed files are the
    source of truth for which keys exist: the UI only renders keys the code
    references, and those all live in the files.
    """
    async with async_session() as session:
        for code, _ in DEFAULT_LANGUAGES:
            seed_file = SEED_DIR / f"translations_{code}.json"
            if not seed_file.exists():
                continue
            data = json.loads(seed_file.read_text(encoding="utf-8"))
            existing = set(
                (await session.execute(select(Translation.key).where(Translation.lang == code)))
                .scalars()
                .all()
            )
            missing = set(data) - existing
            if missing:
                stmt = pg_insert(Translation).values(
                    [{"lang": code, "key": k, "value": data[k]} for k in sorted(missing)]
                )
                await session.execute(stmt.on_conflict_do_nothing())
                logger.info("Seeded %d new translations for '%s'", len(missing), code)
            obsolete = existing - set(data)
            if obsolete:
                await session.execute(
                    delete(Translation).where(Translation.lang == code, Translation.key.in_(obsolete))
                )
                logger.info("Removed %d obsolete translations for '%s'", len(obsolete), code)
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
    await seed_roles()
    await seed_languages()
    await seed_translations()
    await seed_regulations()

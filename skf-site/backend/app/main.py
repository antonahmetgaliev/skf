import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.middleware import StaleHeaderMiddleware
from app.routers import admin, auth, bwp, calendar, championships, dotd, incidents, profile, regulations, translations, users, youtube

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SKF Racing Hub API", version="1.0.0")

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(StaleHeaderMiddleware)

app.include_router(admin.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(bwp.router, prefix="/api")
app.include_router(championships.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(incidents.router, prefix="/api")
app.include_router(dotd.router, prefix="/api")
app.include_router(calendar.router, prefix="/api")
app.include_router(youtube.router, prefix="/api")
app.include_router(translations.router, prefix="/api")
app.include_router(regulations.router, prefix="/api")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.on_event("startup")
async def on_startup():
    # Auto-create any missing tables (users, sessions, roles, etc.)
    from app.database import engine
    from app.models.bwp import Base
    import app.models  # noqa: F401 – ensure all models are registered

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured")

    # Seed the roles table with the three default roles
    from sqlalchemy import select
    from app.database import async_session
    from app.models.user import Role, ROLE_DRIVER, ROLE_MODERATOR, ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_JUDGE, ROLE_COMMUNITY_MANAGER

    async with async_session() as session:
        for role_name in (ROLE_DRIVER, ROLE_MODERATOR, ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_JUDGE, ROLE_COMMUNITY_MANAGER):
            result = await session.execute(
                select(Role).where(Role.name == role_name)
            )
            if result.scalar_one_or_none() is None:
                session.add(Role(name=role_name))
                logger.info(f"Seeded role: {role_name}")
        await session.commit()
    logger.info("Roles seeded")

    # Seed default languages
    from app.models.translation import Language

    async with async_session() as session:
        for code, name in [("en", "English"), ("ua", "Українська")]:
            existing = await session.get(Language, code)
            if existing is None:
                session.add(Language(code=code, name=name, is_active=True))
                logger.info(f"Seeded language: {code}")
        await session.commit()
    logger.info("Languages seeded")

    # Seed translations from JSON files if empty
    from app.models.translation import Translation
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    import json
    from pathlib import Path

    async with async_session() as session:
        result = await session.execute(select(Translation).limit(1))
        if result.scalar_one_or_none() is None:
            seed_dir = Path(__file__).resolve().parent.parent / "seed"
            for lang_code in ("en", "ua"):
                seed_file = seed_dir / f"translations_{lang_code}.json"
                if seed_file.exists():
                    data = json.loads(seed_file.read_text(encoding="utf-8"))
                    items = [{"lang": lang_code, "key": k, "value": v} for k, v in data.items()]
                    if items:
                        stmt = pg_insert(Translation).values(items)
                        stmt = stmt.on_conflict_do_nothing()
                        await session.execute(stmt)
                    logger.info(f"Seeded {len(items)} translations for '{lang_code}'")
            await session.commit()
    logger.info("Translations seeded")

    # Seed regulation pages from JSON if empty
    from app.models.regulation import RegulationPage, RegulationContent

    async with async_session() as session:
        result = await session.execute(select(RegulationPage).limit(1))
        if result.scalar_one_or_none() is None:
            seed_dir = Path(__file__).resolve().parent.parent / "seed"
            seed_file = seed_dir / "regulations_en.json"
            if seed_file.exists():
                data = json.loads(seed_file.read_text(encoding="utf-8"))
                for slug, entry in data.items():
                    import uuid as _uuid
                    page = RegulationPage(
                        id=_uuid.uuid4(),
                        slug=slug,
                        sort_order=entry.get("sort_order", 0),
                    )
                    session.add(page)
                    page.contents.append(
                        RegulationContent(
                            lang="en",
                            title=entry["title"],
                            subtitle=entry.get("subtitle", ""),
                            content=entry.get("content", ""),
                        )
                    )
                await session.commit()
                logger.info(f"Seeded {len(data)} regulation pages")
    logger.info("Regulations seeded")

    logger.info(f"DATABASE_URL scheme: {settings.database_url.split('@')[0].split('://')[0]}")
    logger.info(f"PORT: {settings.port}")
    logger.info(f"CORS origins: {origins}")
    logger.info("SKF Racing Hub API started")

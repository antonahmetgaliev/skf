import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, bwp, championships, users

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

app.include_router(auth.router, prefix="/api")
app.include_router(bwp.router, prefix="/api")
app.include_router(championships.router, prefix="/api")
app.include_router(users.router, prefix="/api")


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
    from app.models.user import Role, ROLE_DRIVER, ROLE_ADMIN, ROLE_SUPER_ADMIN

    async with async_session() as session:
        for role_name in (ROLE_DRIVER, ROLE_ADMIN, ROLE_SUPER_ADMIN):
            result = await session.execute(
                select(Role).where(Role.name == role_name)
            )
            if result.scalar_one_or_none() is None:
                session.add(Role(name=role_name))
                logger.info(f"Seeded role: {role_name}")
        await session.commit()
    logger.info("Roles seeded")

    logger.info(f"DATABASE_URL scheme: {settings.database_url.split('@')[0].split('://')[0]}")
    logger.info(f"PORT: {settings.port}")
    logger.info(f"CORS origins: {origins}")
    logger.info("SKF Racing Hub API started")

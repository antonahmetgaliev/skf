import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import seed
from app.config import settings
from app.core.errors import register_error_handlers
from app.middleware import StaleHeaderMiddleware
from app.routers import admin, auth, bwp, calendar, championships, giveaway, incidents, profile, race_results, regulations, translations, users, youtube

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    await seed.run()
    logger.info("DATABASE_URL scheme: %s", settings.database_url.split("@")[0].split("://")[0])
    logger.info("CORS origins: %s", origins)
    logger.info("SKF Racing Hub API started")
    yield


app = FastAPI(title="SKF Racing Hub API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "Link", "Location", "X-Data-Stale"],
)
app.add_middleware(StaleHeaderMiddleware)
register_error_handlers(app)

app.include_router(admin.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(bwp.router, prefix="/api")
app.include_router(championships.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(incidents.router, prefix="/api")
app.include_router(calendar.router, prefix="/api")
app.include_router(youtube.router, prefix="/api")
app.include_router(translations.router, prefix="/api")
app.include_router(regulations.router, prefix="/api")
app.include_router(giveaway.router, prefix="/api")
app.include_router(race_results.router, prefix="/api")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

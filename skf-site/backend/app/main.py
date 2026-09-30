import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import seed
from app.api import v1
from app.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.middleware import RequestIdMiddleware, StaleHeaderMiddleware
from app.services.simgrid import simgrid_service
from app.services.youtube import youtube_service

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    await seed.run()
    backfill = asyncio.create_task(seed.backfill_window_names())
    logger.info("DATABASE_URL scheme: %s", settings.database_url.split("@")[0].split("://")[0])
    logger.info("CORS origins: %s", origins)
    logger.info("SKF Racing Hub API started")
    yield
    backfill.cancel()
    await simgrid_service.aclose()
    await youtube_service.aclose()


app = FastAPI(title="SKF Racing Hub API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "Link", "Location", "X-Data-Stale", "X-Request-ID"],
)
app.add_middleware(StaleHeaderMiddleware)
app.add_middleware(RequestIdMiddleware)
register_error_handlers(app)

app.include_router(v1.router)
app.include_router(v1.legacy_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

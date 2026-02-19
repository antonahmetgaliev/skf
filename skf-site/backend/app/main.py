import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import bwp, championships

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

app.include_router(bwp.router, prefix="/api")
app.include_router(championships.router, prefix="/api")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.on_event("startup")
async def on_startup():
    logger.info(f"DATABASE_URL scheme: {settings.database_url.split('@')[0].split('://')[0]}")
    logger.info(f"PORT: {settings.port}")
    logger.info(f"CORS origins: {origins}")
    logger.info("SKF Racing Hub API started")

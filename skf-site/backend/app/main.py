import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import bwp, championships

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

"""YouTube router – channel videos and live stream endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas.youtube import YouTubeVideo
from app.services.youtube import youtube_service

router = APIRouter(prefix="/youtube", tags=["YouTube"])


@router.get("/past-streams", response_model=list[YouTubeVideo])
async def get_past_streams(
    limit: int = Query(50, ge=1, le=200),
):
    """Return past completed live streams."""
    return await youtube_service.get_past_streams(limit=limit)


@router.get("/upcoming-streams", response_model=list[YouTubeVideo])
async def get_upcoming_streams(
    limit: int = Query(10, ge=1, le=50),
):
    """Return upcoming/scheduled live streams."""
    return await youtube_service.get_upcoming_streams(limit=limit)

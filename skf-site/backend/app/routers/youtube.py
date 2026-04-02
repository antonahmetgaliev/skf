"""YouTube router – channel videos and live stream endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas.youtube import YouTubeVideo
from app.services.youtube import youtube_service

router = APIRouter(prefix="/youtube", tags=["YouTube"])


@router.get("/live-streams", response_model=list[YouTubeVideo])
async def get_live_streams(
    limit: int = Query(10, ge=1, le=50),
):
    """Return recent completed live streams."""
    return await youtube_service.get_live_streams(limit=limit)

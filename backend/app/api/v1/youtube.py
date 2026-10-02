"""Past and upcoming live streams of the SKF YouTube channel."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas.youtube import StreamStatus, YouTubeStreamOut
from app.services.youtube import youtube_service

router = APIRouter(tags=["YouTube"])


@router.get("/youtube-streams", response_model=list[YouTubeStreamOut])
async def list_youtube_streams(
    status: StreamStatus = Query(...),
    limit: int = Query(10, ge=1, le=200),
):
    """Completed streams (newest first) or scheduled/live ones (soonest first)."""
    if status is StreamStatus.PAST:
        return await youtube_service.get_past_streams(limit=limit)
    return await youtube_service.get_upcoming_streams(limit=limit)

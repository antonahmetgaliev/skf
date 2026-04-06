"""YouTube Data API service with database caching.

Fetches completed live streams from a YouTube channel and caches
the results in the SimgridCache table to minimise API quota usage.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import httpx

from app.config import settings
from app.services.cache import invalidate_cache_by_prefix, read_cache, read_stale_cache, write_cache

_CACHE_TTL = timedelta(minutes=30)
_YT_BASE = "https://www.googleapis.com/youtube/v3"

logger = logging.getLogger(__name__)


class YouTubeService:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=_YT_BASE, timeout=30.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_live_streams(
        self, *, limit: int = 10, force: bool = False,
    ) -> list[dict[str, Any]]:
        """Return recent completed live streams from the channel."""
        return await self._fetch_by_event_type(
            event_type="completed",
            cache_key="youtube_live_streams",
            limit=limit,
            force=force,
        )

    async def get_upcoming_streams(
        self, *, limit: int = 10, force: bool = False,
    ) -> list[dict[str, Any]]:
        """Return upcoming/scheduled live streams from the channel."""
        return await self._fetch_by_event_type(
            event_type="upcoming",
            cache_key="youtube_upcoming_streams",
            limit=limit,
            force=force,
        )

    async def _fetch_by_event_type(
        self,
        *,
        event_type: str,
        cache_key: str,
        limit: int = 10,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch YouTube search results by eventType with caching."""
        if not force:
            cached = await read_cache(cache_key, _CACHE_TTL)
            if cached is not None and isinstance(cached, list):
                return cached[:limit]

        try:
            resp = await self._client.get(
                "/search",
                params={
                    "part": "snippet",
                    "channelId": settings.youtube_channel_id,
                    "type": "video",
                    "eventType": event_type,
                    "order": "date",
                    "maxResults": limit,
                    "key": settings.youtube_api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.warning("YouTube search (%s) fetch failed", event_type, exc_info=True)
            stale = await read_stale_cache(cache_key)
            if stale is not None and isinstance(stale, list):
                return stale[:limit]
            return []

        videos: list[dict[str, Any]] = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            thumbnails = snippet.get("thumbnails", {})
            thumb = (
                thumbnails.get("high")
                or thumbnails.get("medium")
                or thumbnails.get("default")
                or {}
            )
            videos.append({
                "video_id": item.get("id", {}).get("videoId", ""),
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt", ""),
                "thumbnail_url": thumb.get("url", ""),
            })

        await write_cache(cache_key, videos)
        return videos[:limit]

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    async def invalidate_cache(self) -> None:
        """Delete all YouTube cache entries."""
        await invalidate_cache_by_prefix("youtube_")


youtube_service = YouTubeService()

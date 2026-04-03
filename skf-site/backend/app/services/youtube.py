"""YouTube Data API service with database caching.

Fetches completed live streams from a YouTube channel and caches
the results in the SimgridCache table to minimise API quota usage.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models.simgrid_cache import SimgridCache

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
            cached = await self._read_cache(cache_key)
            if cached is not None:
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
            stale = await self._read_stale_cache(cache_key)
            if stale is not None:
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

        await self._write_cache(cache_key, videos)
        return videos[:limit]

    # ------------------------------------------------------------------
    # Database cache helpers (same pattern as SimgridService)
    # ------------------------------------------------------------------

    async def _read_cache(self, key: str) -> list | None:
        try:
            async with async_session() as session:
                row = (
                    await session.execute(
                        select(SimgridCache).where(SimgridCache.cache_key == key)
                    )
                ).scalar_one_or_none()
                if row is None:
                    return None
                age = datetime.now(timezone.utc) - row.fetched_at.replace(
                    tzinfo=timezone.utc
                )
                if age > _CACHE_TTL:
                    return None
                return row.data if isinstance(row.data, list) else None
        except Exception:
            logger.warning("DB cache read failed for key=%s", key, exc_info=True)
            return None

    async def _read_stale_cache(self, key: str) -> list | None:
        try:
            async with async_session() as session:
                row = (
                    await session.execute(
                        select(SimgridCache).where(SimgridCache.cache_key == key)
                    )
                ).scalar_one_or_none()
                if row is None:
                    return None
                return row.data if isinstance(row.data, list) else None
        except Exception:
            logger.warning("DB stale cache read failed for key=%s", key, exc_info=True)
            return None

    async def _write_cache(self, key: str, data: Any) -> None:
        try:
            async with async_session() as session:
                existing = (
                    await session.execute(
                        select(SimgridCache).where(SimgridCache.cache_key == key)
                    )
                ).scalar_one_or_none()
                now = datetime.now(timezone.utc)
                if existing:
                    existing.data = data
                    existing.fetched_at = now
                else:
                    session.add(SimgridCache(cache_key=key, data=data, fetched_at=now))
                await session.commit()
        except Exception:
            logger.warning("DB cache write failed for key=%s", key, exc_info=True)


    async def invalidate_cache(self) -> None:
        """Delete all YouTube cache entries."""
        from sqlalchemy import delete

        try:
            async with async_session() as session:
                await session.execute(
                    delete(SimgridCache).where(
                        SimgridCache.cache_key.like("youtube_%")
                    )
                )
                await session.commit()
        except Exception:
            logger.warning("YouTube cache invalidation failed", exc_info=True)


youtube_service = YouTubeService()

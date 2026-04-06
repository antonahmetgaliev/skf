"""YouTube Data API service with database caching.

Fetches live streams from a YouTube channel using the PlaylistItems
API (for past broadcasts) and Search API (for upcoming), and caches
the results to minimise API quota usage.
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
_MAX_PAGE_SIZE = 50

logger = logging.getLogger(__name__)


def _uploads_playlist_id(channel_id: str) -> str:
    """Derive the uploads playlist ID from a channel ID (UC… → UU…)."""
    if channel_id.startswith("UC"):
        return "UU" + channel_id[2:]
    return channel_id


class YouTubeService:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=_YT_BASE, timeout=30.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_live_streams(
        self, *, limit: int = 10, force: bool = False,
    ) -> list[dict[str, Any]]:
        """Return past completed live streams from the channel."""
        cache_key = "youtube_live_streams"

        if not force:
            cached = await read_cache(cache_key, _CACHE_TTL)
            if cached is not None and isinstance(cached, list):
                return cached[:limit]

        try:
            videos = await self._fetch_past_streams(limit=limit)
        except Exception:
            logger.warning("YouTube past-streams fetch failed", exc_info=True)
            stale = await read_stale_cache(cache_key)
            if stale is not None and isinstance(stale, list):
                return stale[:limit]
            return []

        await write_cache(cache_key, videos)
        return videos[:limit]

    async def get_upcoming_streams(
        self, *, limit: int = 10, force: bool = False,
    ) -> list[dict[str, Any]]:
        """Return upcoming/scheduled live streams from the channel."""
        cache_key = "youtube_upcoming_streams"

        if not force:
            cached = await read_cache(cache_key, _CACHE_TTL)
            if cached is not None and isinstance(cached, list):
                return cached[:limit]

        try:
            videos = await self._search_by_event_type("upcoming", limit=limit)
        except Exception:
            logger.warning("YouTube upcoming-streams fetch failed", exc_info=True)
            stale = await read_stale_cache(cache_key)
            if stale is not None and isinstance(stale, list):
                return stale[:limit]
            return []

        await write_cache(cache_key, videos)
        return videos[:limit]

    # ------------------------------------------------------------------
    # Past streams via PlaylistItems + Videos detail
    # ------------------------------------------------------------------

    async def _fetch_past_streams(self, *, limit: int) -> list[dict[str, Any]]:
        """Fetch all uploads, then filter to those that were live streams."""
        playlist_id = _uploads_playlist_id(settings.youtube_channel_id)

        # Step 1: paginate through the uploads playlist
        all_video_ids: list[str] = []
        snippets_by_id: dict[str, dict[str, Any]] = {}
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {
                "part": "snippet",
                "playlistId": playlist_id,
                "maxResults": _MAX_PAGE_SIZE,
                "key": settings.youtube_api_key,
            }
            if page_token:
                params["pageToken"] = page_token

            resp = await self._client.get("/playlistItems", params=params)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("items", []):
                vid = item.get("snippet", {}).get("resourceId", {}).get("videoId")
                if vid:
                    all_video_ids.append(vid)
                    snippets_by_id[vid] = item["snippet"]

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        if not all_video_ids:
            return []

        # Step 2: batch-fetch video details to identify live streams
        live_video_ids: set[str] = set()
        for i in range(0, len(all_video_ids), _MAX_PAGE_SIZE):
            batch = all_video_ids[i : i + _MAX_PAGE_SIZE]
            resp = await self._client.get(
                "/videos",
                params={
                    "part": "liveStreamingDetails",
                    "id": ",".join(batch),
                    "key": settings.youtube_api_key,
                },
            )
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                if item.get("liveStreamingDetails"):
                    live_video_ids.add(item["id"])

        # Step 3: build result list preserving upload order (newest first)
        videos: list[dict[str, Any]] = []
        for vid in all_video_ids:
            if vid not in live_video_ids:
                continue
            snippet = snippets_by_id[vid]
            thumbnails = snippet.get("thumbnails", {})
            thumb = (
                thumbnails.get("high")
                or thumbnails.get("medium")
                or thumbnails.get("default")
                or {}
            )
            videos.append({
                "video_id": vid,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt", ""),
                "thumbnail_url": thumb.get("url", ""),
            })
            if len(videos) >= limit:
                break

        return videos

    # ------------------------------------------------------------------
    # Upcoming streams via Search API
    # ------------------------------------------------------------------

    async def _search_by_event_type(
        self, event_type: str, *, limit: int,
    ) -> list[dict[str, Any]]:
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

        videos: list[dict[str, Any]] = []
        for item in resp.json().get("items", []):
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
        return videos

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    async def invalidate_cache(self) -> None:
        """Delete all YouTube cache entries."""
        await invalidate_cache_by_prefix("youtube_")


youtube_service = YouTubeService()

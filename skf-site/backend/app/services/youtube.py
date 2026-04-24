"""YouTube Data API service with database caching.

Scans the channel's uploads playlist once, splits videos into
past (completed) and upcoming (scheduled/live) streams, and caches
both to minimise API quota usage.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import httpx

from app.config import settings
from app.services.cache import invalidate_cache_by_prefix, read_cache, read_stale_cache, write_cache

_CACHE_TTL = timedelta(minutes=30)
_CACHE_KEY = "youtube_streams"
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

    async def get_past_streams(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Return past completed live streams (newest first)."""
        data = await self._get_cached_streams()
        return data["past"][:limit]

    async def get_upcoming_streams(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Return upcoming/scheduled and currently-live streams (soonest first)."""
        data = await self._get_cached_streams()
        return data["upcoming"][:limit]

    async def invalidate_cache(self) -> None:
        """Delete all YouTube cache entries."""
        await invalidate_cache_by_prefix("youtube_")

    # ------------------------------------------------------------------
    # Core: single scan → split into past + upcoming
    # ------------------------------------------------------------------

    async def _get_cached_streams(self) -> dict[str, list[dict[str, Any]]]:
        """Return cached {past, upcoming} dict, refreshing if stale."""
        cached = await read_cache(_CACHE_KEY, _CACHE_TTL)
        if cached is not None and isinstance(cached, dict):
            return cached

        try:
            data = await self._scan_and_split()
        except Exception:
            logger.warning("YouTube scan failed", exc_info=True)
            stale = await read_stale_cache(_CACHE_KEY)
            if stale is not None and isinstance(stale, dict):
                return stale
            return {"past": [], "upcoming": []}

        await write_cache(_CACHE_KEY, data)
        return data

    async def _scan_and_split(self) -> dict[str, list[dict[str, Any]]]:
        """Scan uploads once, fetch liveStreamingDetails, split results."""
        video_ids, snippets = await self._scan_uploads()
        if not video_ids:
            return {"past": [], "upcoming": []}

        details = await self._fetch_stream_details(video_ids)

        past: list[dict[str, Any]] = []
        upcoming: list[dict[str, Any]] = []

        for vid in video_ids:
            stream = details.get(vid)
            if not stream:
                continue

            if stream.get("actualEndTime"):
                # Completed stream — use actual start time as the date
                stream_date = (
                    stream.get("actualStartTime")
                    or stream.get("scheduledStartTime")
                )
                past.append(self._build_video(vid, snippets[vid], published_at=stream_date))
            else:
                # Upcoming or currently live
                scheduled = stream.get("scheduledStartTime")
                upcoming.append(self._build_video(vid, snippets[vid], published_at=scheduled))

        # Upcoming: soonest first
        upcoming.sort(key=lambda v: v["published_at"])

        return {"past": past, "upcoming": upcoming}

    # ------------------------------------------------------------------
    # YouTube API helpers
    # ------------------------------------------------------------------

    async def _scan_uploads(self) -> tuple[list[str], dict[str, dict[str, Any]]]:
        """Paginate the channel's uploads playlist.
        Returns (ordered video IDs newest-first, snippets keyed by ID)."""
        playlist_id = _uploads_playlist_id(settings.youtube_channel_id)
        video_ids: list[str] = []
        snippets: dict[str, dict[str, Any]] = {}
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
                    video_ids.append(vid)
                    snippets[vid] = item["snippet"]

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return video_ids, snippets

    async def _fetch_stream_details(
        self, video_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Batch-fetch liveStreamingDetails for video IDs."""
        result: dict[str, dict[str, Any]] = {}
        for i in range(0, len(video_ids), _MAX_PAGE_SIZE):
            batch = video_ids[i : i + _MAX_PAGE_SIZE]
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
                details = item.get("liveStreamingDetails")
                if details:
                    result[item["id"]] = details
        return result

    @staticmethod
    def _build_video(
        vid: str,
        snippet: dict[str, Any],
        published_at: str | None = None,
    ) -> dict[str, Any]:
        thumbnails = snippet.get("thumbnails", {})
        thumb = (
            thumbnails.get("high")
            or thumbnails.get("medium")
            or thumbnails.get("default")
            or {}
        )
        return {
            "video_id": vid,
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "published_at": published_at or snippet.get("publishedAt", ""),
            "thumbnail_url": thumb.get("url", ""),
        }


youtube_service = YouTubeService()

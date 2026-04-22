"""YouTube Data API service with database caching.

Fetches live streams from a YouTube channel using the PlaylistItems
API, and caches the results to minimise API quota usage.
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

    async def get_past_streams(
        self, *, limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return past completed live streams from the channel."""
        cache_key = "youtube_past_streams"

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
        self, *, limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return upcoming/scheduled and currently-live streams from the channel."""
        cache_key = "youtube_upcoming_streams"

        cached = await read_cache(cache_key, _CACHE_TTL)
        if cached is not None and isinstance(cached, list):
            return cached[:limit]

        try:
            videos = await self._fetch_upcoming_streams()
        except Exception:
            logger.warning("YouTube upcoming-streams fetch failed", exc_info=True)
            stale = await read_stale_cache(cache_key)
            if stale is not None and isinstance(stale, list):
                return stale[:limit]
            return []

        await write_cache(cache_key, videos)
        return videos[:limit]

    # ------------------------------------------------------------------
    # Playlist scan (shared by past + upcoming)
    # ------------------------------------------------------------------

    async def _scan_uploads(self) -> tuple[list[str], dict[str, dict[str, Any]]]:
        """Paginate through the channel's uploads playlist.
        Returns (ordered video IDs, snippet dict keyed by ID)."""
        playlist_id = _uploads_playlist_id(settings.youtube_channel_id)

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

        return all_video_ids, snippets_by_id

    async def _fetch_stream_details(
        self, video_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Batch-fetch liveStreamingDetails for a list of video IDs.
        Returns a dict keyed by video ID."""
        details_by_id: dict[str, dict[str, Any]] = {}
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
                    details_by_id[item["id"]] = details
        return details_by_id

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

    # ------------------------------------------------------------------
    # Past streams
    # ------------------------------------------------------------------

    async def _fetch_past_streams(self, *, limit: int) -> list[dict[str, Any]]:
        """Fetch uploads and filter to completed live streams."""
        all_video_ids, snippets_by_id = await self._scan_uploads()
        if not all_video_ids:
            return []

        details_by_id = await self._fetch_stream_details(all_video_ids)

        videos: list[dict[str, Any]] = []
        for vid in all_video_ids:
            details = details_by_id.get(vid)
            if details and details.get("actualEndTime"):
                # Use actual/scheduled start time so the date reflects
                # when the stream happened, not when the VOD was published.
                stream_date = (
                    details.get("actualStartTime")
                    or details.get("scheduledStartTime")
                    or None
                )
                videos.append(self._build_video(
                    vid, snippets_by_id[vid],
                    published_at=stream_date,
                ))
                if len(videos) >= limit:
                    break
        return videos

    # ------------------------------------------------------------------
    # Upcoming / live streams
    # ------------------------------------------------------------------

    async def _fetch_upcoming_streams(self) -> list[dict[str, Any]]:
        """Fetch uploads and filter to upcoming/live streams (no actualEndTime)."""
        all_video_ids, snippets_by_id = await self._scan_uploads()
        if not all_video_ids:
            return []

        details_by_id = await self._fetch_stream_details(all_video_ids)

        videos: list[dict[str, Any]] = []
        for vid in all_video_ids:
            details = details_by_id.get(vid)
            if details and not details.get("actualEndTime"):
                scheduled = details.get("scheduledStartTime", "")
                videos.append(self._build_video(
                    vid, snippets_by_id[vid],
                    published_at=scheduled or None,
                ))

        # Sort by scheduled time ascending (soonest first)
        videos.sort(key=lambda v: v["published_at"])
        return videos

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    async def invalidate_cache(self) -> None:
        """Delete all YouTube cache entries."""
        await invalidate_cache_by_prefix("youtube_")


youtube_service = YouTubeService()

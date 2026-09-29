"""Server-side proxy for The SimGrid API.

Moves the API key and all parsing logic to the backend so the frontend
never touches SimGrid directly.  Responses are cached in the database
to avoid hammering the SimGrid API.  Everything is sourced from the REST
API, including overall standings (per-race breakdown is not exposed).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import settings
from app.middleware import mark_stale
from app.schemas.championship import (
    ChampionshipDetails,
    ChampionshipListItem,
    ChampionshipStandingsData,
    ParticipatingUser,
    StandingEntry,
    StandingRace,
)
from app.schemas.simgrid_raw import (
    Envelope,
    RawChampionshipCarClass,
    RawChampionshipRef,
    RawModel,
    RawNamed,
    RawParticipant,
    RawRace,
    RawSessionResult,
    RawSessionResultsPage,
    RawStandingsPage,
    collection,
)
from app.services.cache import (
    invalidate_cache_by_keys,
    invalidate_cache_by_prefix,
    read_cache,
    read_stale_cache,
    write_cache,
)

_TTL_STATIC = timedelta(days=1)      # championships list, details, races
_TTL_LIVE = timedelta(minutes=10)    # participants
_TTL_STANDINGS = timedelta(hours=1)  # standings
_TTL_RESULTS = timedelta(days=1)     # session results (stewards may amend them)
_MAX_STANDINGS_PAGES = 50            # safety cap for paged standings fetches
_MAX_CHAMPIONSHIPS = 2000            # safety cap for the championships list
_RACES_LIMIT = 100                   # races endpoint defaults to 10 and ignores offset

# SimGrid enforces a per-minute rate limit and answers
# `429 {"error":"Minute rate limit exceeded"}` once it is crossed - measured at
# roughly twenty requests a minute. Nothing here used to bound concurrency, and
# the calendar fans out over every active championship at once, so a busy
# calendar could trip the limit and fall back to stale data for everyone.
_MAX_CONCURRENT_REQUESTS = 4
_RATE_LIMIT_RETRY_SECONDS = 5.0
_client_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)

logger = logging.getLogger(__name__)


def _cached_list(payload: Any) -> list | None:
    """A cached collection, or None to refetch anything that is not a list."""
    return payload if isinstance(payload, list) else None


class SimgridService:
    def __init__(self) -> None:
        headers: dict[str, str] = {}
        if settings.simgrid_api_key:
            headers["Authorization"] = f"Bearer {settings.simgrid_api_key}"
        self._client = httpx.AsyncClient(
            base_url=settings.simgrid_base_url,
            headers=headers,
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_championships(
        self, limit: int = 200,
    ) -> list[ChampionshipListItem]:
        key = f"championships_list_{limit}"
        cached = await read_cache(key, _TTL_STATIC)
        # An empty list is never a real answer for SKF; refetch instead of
        # serving it for a whole day.
        if cached:
            return [ChampionshipListItem(**item) for item in cached]

        try:
            items: list[dict] = []
            offset = 0
            while True:
                resp = await self._get(
                    "/api/v1/championships",
                    params={"limit": limit, "offset": offset},
                )
                resp.raise_for_status()
                raw = resp.json()
                page = collection(RawChampionshipRef, raw)
                if not page.data:
                    break
                items.extend(raw["data"])
                total = page.pagination.total_count if page.pagination else None
                if total is not None and len(items) >= total:
                    break
                if len(page.data) < limit or len(items) >= _MAX_CHAMPIONSHIPS:
                    break
                offset += limit
            if items:
                await write_cache(key, items)
            return [ChampionshipListItem(**item) for item in items]
        except Exception:
            logger.warning(
                "Championships fetch failed, attempting stale cache fallback",
                exc_info=True,
            )
            stale = await read_stale_cache(key)
            if stale is not None:
                mark_stale()
                return [ChampionshipListItem(**item) for item in stale]
            raise

    async def with_details(
        self, items: list[ChampionshipListItem],
    ) -> list[ChampionshipListItem]:
        """Fill dates and registration state from each championship's details.

        The list endpoint only returns ``id`` and ``name``, so call this on
        the (few) items actually shown rather than on the whole list.
        """
        async def enrich(item: ChampionshipListItem) -> ChampionshipListItem:
            try:
                details = await self.get_championship(item.id)
            except Exception:
                logger.warning("Failed to fetch details for championship %s", item.id, exc_info=True)
                return item
            return item.model_copy(update={
                "start_date": item.start_date or details.start_date,
                "end_date": item.end_date or details.end_date,
                "accepting_registrations": item.accepting_registrations or details.accepting_registrations,
            })

        return list(await asyncio.gather(*(enrich(item) for item in items)))

    async def get_championship(
        self, championship_id: int,
    ) -> ChampionshipDetails:
        key = f"championship_{championship_id}"
        cached = await read_cache(key, _TTL_STATIC)
        if cached is not None:
            return ChampionshipDetails(**cached)

        data = await self._request(
            f"/api/v1/championships/{championship_id}", key,
        )
        return ChampionshipDetails(**data)

    async def get_races(
        self, championship_id: int,
    ) -> list[dict]:
        key = f"races_{championship_id}"
        cached = _cached_list(await read_cache(key, _TTL_STATIC))
        if cached is not None:
            return cached

        data = await self._request(
            "/api/v1/races", key, page=Envelope[RawRace],
            params={"championship_id": championship_id, "limit": _RACES_LIMIT},
        )
        return data if isinstance(data, list) else []

    async def get_session_results(
        self, championship_id: int, race_id: int, session: str,
    ) -> list[RawSessionResult]:
        """One session's results (``race_1`` or ``qualifying``); ``[]`` until published."""
        key = f"session_results_{championship_id}_{race_id}_{session}"
        data = _cached_list(await read_cache(key, _TTL_RESULTS))
        if data is None:
            data = await self._request(
                f"/api/v1/races/{race_id}/session_results", key,
                page=RawSessionResultsPage,
                params={"session_type": session, "result_type": "results", "per_page": 500},
            )
        return [RawSessionResult.model_validate(r) for r in data or []]

    async def get_standings(
        self, championship_id: int,
    ) -> tuple[ChampionshipStandingsData, bool]:
        """Return (standings, fetched_live).

        ``fetched_live`` is False for cache hits and stale fallbacks, so
        callers can skip work (e.g. the driver sync) that only makes sense
        when the data actually changed.
        """
        key = f"standings_{championship_id}"
        cached = await read_cache(key, _TTL_STANDINGS)
        if cached is not None:
            return ChampionshipStandingsData(**cached), False

        try:
            class_ids = await self._championship_car_class_ids(championship_id)
            base = f"/api/v1/championships/{championship_id}/standings"

            if len(class_ids) > 1:
                # Multiclass: the default page only returns the first class, so
                # fetch each class via ``?filter_class=<id>`` and merge entries.
                data = await self._fetch_standings(
                    base, [{"filter_class": ccid} for ccid in class_ids]
                )
            else:
                data = await self._fetch_standings(base, [{}])

            await write_cache(key, data.model_dump())
            return data, True
        except Exception:
            logger.warning(
                "Standings fetch failed for %s, attempting stale cache fallback",
                key, exc_info=True,
            )
            stale = await read_stale_cache(key)
            if stale is not None:
                mark_stale()
                return ChampionshipStandingsData(**stale), False
            raise

    async def _fetch_standings(
        self, base: str, param_sets: list[dict[str, Any]],
    ) -> ChampionshipStandingsData:
        """Fetch every page of every param set and merge unique entries."""
        merged: list[StandingEntry] = []
        seen: set[object] = set()
        races: list[StandingRace] = []

        for params in param_sets:
            page = 1
            while page <= _MAX_STANDINGS_PAGES:
                page_params = dict(params)
                if page > 1:
                    page_params["page"] = page
                resp = await self._get(base, params=page_params)
                resp.raise_for_status()
                raw = RawStandingsPage.model_validate(resp.json())
                parsed = self._parse_standings(raw)
                if not races:
                    races = parsed.races

                new_entries = 0
                for entry in parsed.entries:
                    dedup_key = (
                        entry.id if entry.id is not None
                        else f"name:{entry.display_name.lower()}"
                    )
                    if dedup_key not in seen:
                        seen.add(dedup_key)
                        merged.append(entry)
                        new_entries += 1

                # A repeated page (ignored ``page`` param) adds nothing: stop.
                if page >= self._standings_total_pages(raw) or new_entries == 0:
                    break
                page += 1

        merged.sort(
            key=lambda en: (
                en.position if en.position is not None else float("inf"),
                -en.score,
                en.display_name,
            ),
        )
        return ChampionshipStandingsData(entries=merged, races=races)

    @staticmethod
    def _standings_total_pages(raw: RawStandingsPage) -> int:
        """Page count from ``pagination`` (``limit`` is the page size); 1 when absent."""
        p = raw.pagination
        if p is None or not p.total_count or not p.limit:
            return 1
        return -(-p.total_count // p.limit)

    async def _championship_car_class_ids(
        self, championship_id: int,
    ) -> list[int]:
        """Return the championship's car-class ids (empty on failure)."""
        try:
            resp = await self._get(
                f"/api/v1/championships/{championship_id}"
                "/championship_car_classes"
            )
            resp.raise_for_status()
            return [c.id for c in collection(RawChampionshipCarClass, resp.json()).data]
        except Exception:
            logger.warning(
                "Failed to fetch car classes for %s", championship_id,
                exc_info=True,
            )
            return []

    @staticmethod
    def _parse_standings(raw: RawStandingsPage) -> ChampionshipStandingsData:
        """Map a standings page into ``ChampionshipStandingsData``.

        Per-race results (``partial_standings``) are not populated by the API,
        so ``StandingEntry.race_results`` is always empty.
        """
        entries: list[StandingEntry] = []
        for e in raw.data:
            cc = e.championship_car_class
            entries.append(StandingEntry(
                id=e.user_id or None,
                position=e.position_cache,
                display_name=e.display_name or "",
                country_code=(e.participant.country_code if e.participant else None) or "",
                car=e.car or "",
                car_class=(cc.display_name if cc else None) or e.car_class or "",
                points=e.championship_points or 0,
                penalties=e.championship_penalties or 0,
                score=e.championship_score or 0,
                race_results=[],
            ))

        races = [
            StandingRace(
                id=r.id,
                display_name=r.display_name or r.race_name or "",
                starts_at=r.starts_at,
                results_available=r.results_available,
                ended=r.ended,
            )
            for r in raw.completed_races
        ]
        races.sort(key=lambda r: r.starts_at or "")

        entries.sort(
            key=lambda en: (
                en.position if en.position is not None else float("inf"),
                -en.score,
                en.display_name,
            ),
        )
        return ChampionshipStandingsData(entries=entries, races=races)

    async def get_participating_users(
        self, championship_id: int,
    ) -> list[ParticipatingUser]:
        key = f"participants_{championship_id}"
        cached = _cached_list(await read_cache(key, _TTL_LIVE))
        if cached is not None:
            return [ParticipatingUser(**u) for u in cached]

        data = await self._request(
            f"/api/v1/championships/{championship_id}/participating_users", key,
            page=Envelope[RawParticipant],
        )
        items = data if isinstance(data, list) else []
        return [ParticipatingUser(**u) for u in items]

    async def get_user_by_discord_id(self, discord_uid: str) -> int | None:
        """Resolve a Discord user id to a SimGrid user id (None on failure).

        Uses ``GET /users/{uid}?attribute=discord``. Errors are swallowed —
        this is called from login flows that must never fail on SimGrid.
        """
        key = f"user_by_discord_{discord_uid}"
        try:
            cached = await read_cache(key, _TTL_LIVE)
            if cached is not None:
                user_id = cached.get("user_id") if isinstance(cached, dict) else None
                return user_id if isinstance(user_id, int) else None

            resp = await self._get(
                f"/api/v1/users/{discord_uid}", params={"attribute": "discord"}
            )
            resp.raise_for_status()
            data = resp.json()
            user_id = data.get("user_id") if isinstance(data, dict) else None
            await write_cache(key, {"user_id": user_id})
            return user_id if isinstance(user_id, int) else None
        except Exception:
            logger.info(
                "SimGrid discord lookup failed for %s", discord_uid, exc_info=True
            )
            return None

    async def get_race_name(self, race_id: int) -> str:
        """Fetch a single race's display name from SimGrid."""
        try:
            resp = await self._get(f"/api/v1/races/{race_id}")
            resp.raise_for_status()
            data = resp.json()
            return data.get("display_name") or data.get("race_name") or f"Race {race_id}"
        except Exception:
            logger.warning("Failed to fetch race %s name from SimGrid", race_id, exc_info=True)
            return f"Race {race_id}"

    async def get_games(self) -> list[dict]:
        """Fetch all games from SimGrid."""
        key = "games_list"
        cached = _cached_list(await read_cache(key, _TTL_STATIC))
        if cached is not None:
            return cached

        data = await self._request("/api/v1/games", key, page=Envelope[RawNamed])
        return data if isinstance(data, list) else []

    async def get_car_classes(
        self, game_id: int | None = None,
    ) -> list[dict]:
        """Fetch car classes from SimGrid, optionally filtered by game."""
        suffix = f"_{game_id}" if game_id else ""
        key = f"car_classes{suffix}"
        cached = _cached_list(await read_cache(key, _TTL_STATIC))
        if cached is not None:
            return cached

        params: dict[str, Any] = {}
        if game_id is not None:
            params["game_id"] = game_id

        data = await self._request("/api/v1/car_classes", key, page=Envelope[RawNamed], params=params)
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _get(
        self, url: str, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        """Every SimGrid GET goes through here, throttled and 429-aware.

        One retry only: the limit is per minute, so a request that is still
        refused after honouring `Retry-After` is better served by the stale
        cache than by queueing behind a longer wait.
        """
        async with _client_semaphore:
            resp = await self._client.get(url, params=params)
            if resp.status_code != 429:
                return resp
            delay = _RATE_LIMIT_RETRY_SECONDS
            header = resp.headers.get("Retry-After")
            if header:
                try:
                    delay = min(float(header), 30.0)
                except ValueError:
                    pass
            logger.warning("SimGrid rate limit hit for %s, retrying in %ss", url, delay)
            await asyncio.sleep(delay)
            return await self._client.get(url, params=params)

    async def _request(
        self,
        url: str,
        cache_key: str,
        *,
        page: type[RawModel] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET from SimGrid API with stale-cache fallback on upstream errors.

        With *page* (an envelope model), the response must validate against
        it; its ``data`` (the raw dicts, ``[]`` for a null ``data``) is cached
        and returned. A shape mismatch is treated like an upstream error,
        never as an empty collection.
        """
        try:
            resp = await self._get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if page is not None:
                page.model_validate(data)
                data = data["data"] or []
            await write_cache(cache_key, data)
            return data
        except (httpx.HTTPStatusError, ValidationError):
            logger.warning(
                "SimGrid API error for %s, attempting stale cache fallback",
                cache_key, exc_info=True,
            )
            stale = await read_stale_cache(cache_key)
            if stale is not None and (page is None or isinstance(stale, list)):
                mark_stale()
                return stale
            raise

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    async def invalidate_cache(
        self, championship_id: int | None = None
    ) -> None:
        if championship_id is not None:
            await invalidate_cache_by_keys(
                f"championship_{championship_id}",
                f"standings_{championship_id}",
                f"races_{championship_id}",
                f"participants_{championship_id}",
            )
            await invalidate_cache_by_prefix(f"session_results_{championship_id}_")
        else:
            await invalidate_cache_by_prefix()


simgrid_service = SimgridService()

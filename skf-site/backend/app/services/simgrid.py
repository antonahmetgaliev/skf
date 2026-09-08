"""Server-side proxy for The SimGrid API.

Moves the API key and all parsing logic to the backend so the frontend
never touches SimGrid directly.  Responses are cached in the database
to avoid hammering the SimGrid API.  Everything is sourced from the REST
API, including overall standings (per-race breakdown is not exposed).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import httpx

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
_MAX_STANDINGS_PAGES = 50            # safety cap for paged standings fetches
_MAX_CHAMPIONSHIPS = 2000            # safety cap for the championships list
logger = logging.getLogger(__name__)


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
        if cached is not None:
            return [ChampionshipListItem(**item) for item in cached]

        try:
            items: list[dict] = []
            offset = 0
            while True:
                resp = await self._client.get(
                    "/api/v1/championships",
                    params={"limit": limit, "offset": offset},
                )
                resp.raise_for_status()
                page = resp.json()
                if not isinstance(page, list) or not page:
                    break
                items.extend(page)
                if len(page) < limit or len(items) >= _MAX_CHAMPIONSHIPS:
                    break
                offset += limit
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
        cached = await read_cache(key, _TTL_STATIC)
        if cached is not None:
            return cached if isinstance(cached, list) else []

        data = await self._request(
            "/api/v1/races", key, params={"championship_id": championship_id}
        )
        return data if isinstance(data, list) else []

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
                resp = await self._client.get(base, params=page_params)
                resp.raise_for_status()
                raw = resp.json()
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

                total_pages = self._standings_total_pages(raw)
                if total_pages is not None and page >= total_pages:
                    break
                # Unknown page count: keep going only while pages still add
                # entries (an ignored ``page`` param repeats and stops here).
                if total_pages is None and new_entries == 0:
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
    def _standings_total_pages(raw: Any) -> int | None:
        """Extract the page count from the standings payload's pagination
        element (``raw[4]``); 1 when absent, None when unrecognisable."""
        if not (isinstance(raw, list) and len(raw) > 4 and isinstance(raw[4], dict)):
            return 1
        pagination = raw[4].get("pagination")
        if not isinstance(pagination, dict):
            return 1
        for key in ("total_pages", "pages", "last", "last_page", "page_count"):
            value = pagination.get(key)
            if isinstance(value, int) and value > 0:
                return value
        return None

    async def _championship_car_class_ids(
        self, championship_id: int,
    ) -> list[int]:
        """Return the championship's car-class ids (empty on failure)."""
        try:
            resp = await self._client.get(
                f"/api/v1/championships/{championship_id}"
                "/championship_car_classes"
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                c["id"] for c in data
                if isinstance(c, dict) and c.get("id") is not None
            ]
        except Exception:
            logger.warning(
                "Failed to fetch car classes for %s", championship_id,
                exc_info=True,
            )
            return []

    @staticmethod
    def _parse_standings(raw: Any) -> ChampionshipStandingsData:
        """Map the REST standings payload into ``ChampionshipStandingsData``.

        The endpoint returns a heterogeneous array whose first element is the
        list of standings entries and second element is the race metadata.
        Per-race results (``partial_standings``) are not populated by the API,
        so ``StandingEntry.race_results`` is always empty.
        """
        entries_raw = raw[0] if isinstance(raw, list) and raw else []
        races_raw = raw[1] if isinstance(raw, list) and len(raw) > 1 else []

        entries: list[StandingEntry] = []
        for e in entries_raw if isinstance(entries_raw, list) else []:
            if not isinstance(e, dict):
                continue
            car_class = e.get("class") or ""
            cc = e.get("championship_car_class")
            if isinstance(cc, dict) and cc.get("display_name"):
                car_class = cc["display_name"]
            participant = e.get("participant")
            country = (
                participant.get("country_code", "")
                if isinstance(participant, dict) else ""
            )
            # NOTE: ``e["id"]`` is the *registration* id, a different id space —
            # never use it as a driver id. Entries without user_id keep id=None.
            entries.append(StandingEntry(
                id=e.get("user_id") or None,
                position=e.get("position_cache"),
                display_name=e.get("display_name") or "",
                country_code=country or "",
                car=e.get("car") or "",
                car_class=car_class,
                points=e.get("championship_points") or 0,
                penalties=e.get("championship_penalties") or 0,
                score=e.get("championship_score") or 0,
                race_results=[],
            ))

        races: list[StandingRace] = []
        for r in races_raw if isinstance(races_raw, list) else []:
            if not isinstance(r, dict):
                continue
            races.append(StandingRace(
                id=r.get("id") or 0,
                display_name=r.get("display_name") or r.get("race_name") or "",
                starts_at=r.get("starts_at"),
                results_available=bool(r.get("results_available")),
                ended=bool(r.get("ended")),
            ))
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
        cached = await read_cache(key, _TTL_LIVE)
        if cached is not None:
            return [ParticipatingUser(**u) for u in cached]

        data = await self._request(
            f"/api/v1/championships/{championship_id}/participating_users", key,
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

            resp = await self._client.get(
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
            resp = await self._client.get(f"/api/v1/races/{race_id}")
            resp.raise_for_status()
            data = resp.json()
            return data.get("display_name") or data.get("race_name") or f"Race {race_id}"
        except Exception:
            return f"Race {race_id}"

    async def get_games(self) -> list[dict]:
        """Fetch all games from SimGrid."""
        key = "games_list"
        cached = await read_cache(key, _TTL_STATIC)
        if cached is not None:
            return cached if isinstance(cached, list) else []

        data = await self._request("/api/v1/games", key)
        return data if isinstance(data, list) else []

    async def get_car_classes(
        self, game_id: int | None = None,
    ) -> list[dict]:
        """Fetch car classes from SimGrid, optionally filtered by game."""
        suffix = f"_{game_id}" if game_id else ""
        key = f"car_classes{suffix}"
        cached = await read_cache(key, _TTL_STATIC)
        if cached is not None:
            return cached if isinstance(cached, list) else []

        params: dict[str, Any] = {}
        if game_id is not None:
            params["game_id"] = game_id

        data = await self._request("/api/v1/car_classes", key, params=params)
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # HTTP helper with stale-cache fallback
    # ------------------------------------------------------------------

    async def _request(
        self,
        url: str,
        cache_key: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET from SimGrid API with stale-cache fallback on upstream errors."""
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            await write_cache(cache_key, data)
            return data
        except httpx.HTTPStatusError:
            logger.warning(
                "SimGrid API error for %s, attempting stale cache fallback",
                cache_key, exc_info=True,
            )
            stale = await read_stale_cache(cache_key)
            if stale is not None:
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
        else:
            await invalidate_cache_by_prefix()


simgrid_service = SimgridService()

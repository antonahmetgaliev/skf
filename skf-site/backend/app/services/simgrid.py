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

        data = await self._request(
            "/api/v1/championships", key, params={"limit": limit, "offset": 0}
        )
        items = data if isinstance(data, list) else []
        return [ChampionshipListItem(**item) for item in items]

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
    ) -> ChampionshipStandingsData:
        key = f"standings_{championship_id}"
        cached = await read_cache(key, _TTL_STANDINGS)
        if cached is not None:
            return ChampionshipStandingsData(**cached)

        try:
            class_ids = await self._championship_car_class_ids(championship_id)
            base = f"/api/v1/championships/{championship_id}/standings"

            if len(class_ids) > 1:
                # Multiclass: the default page only returns the first class, so
                # fetch each class via ``?filter_class=<id>`` and merge entries.
                merged: list[StandingEntry] = []
                seen: set[int] = set()
                races: list[StandingRace] = []
                for ccid in class_ids:
                    resp = await self._client.get(
                        base, params={"filter_class": ccid}
                    )
                    resp.raise_for_status()
                    parsed = self._parse_standings(resp.json())
                    if not races:
                        races = parsed.races
                    for entry in parsed.entries:
                        if entry.id not in seen:
                            seen.add(entry.id)
                            merged.append(entry)
                data = ChampionshipStandingsData(entries=merged, races=races)
            else:
                resp = await self._client.get(base)
                resp.raise_for_status()
                data = self._parse_standings(resp.json())

            await write_cache(key, data.model_dump())
            return data
        except Exception:
            logger.warning(
                "Standings fetch failed for %s, attempting stale cache fallback",
                key, exc_info=True,
            )
            stale = await read_stale_cache(key)
            if stale is not None:
                mark_stale()
                return ChampionshipStandingsData(**stale)
            raise

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
            entries.append(StandingEntry(
                id=e.get("user_id") or e.get("id") or 0,
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

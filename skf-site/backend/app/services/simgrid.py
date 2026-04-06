"""Server-side proxy for The SimGrid API.

Moves the API key and all parsing logic to the backend so the frontend
never touches SimGrid directly.  Responses are cached in the database
for 10 minutes to avoid hammering the SimGrid API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx

from app.config import settings
from app.schemas.championship import (
    ChampionshipDetails,
    ChampionshipListItem,
    ChampionshipRace,
    ChampionshipStandingsData,
    DriverRaceResult,
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

_CACHE_TTL = timedelta(minutes=10)
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CachedResponse:
    """Wraps service data with staleness metadata."""

    data: Any
    stale: bool = field(default=False)


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
        self, limit: int = 200, *, force: bool = False
    ) -> CachedResponse:
        key = f"championships_list_{limit}"
        if not force:
            cached = await read_cache(key, _CACHE_TTL)
            if cached is not None:
                return CachedResponse(data=[ChampionshipListItem(**item) for item in cached])

        result = await self._request(
            "/api/v1/championships", key, params={"limit": limit, "offset": 0}
        )
        items = result.data if isinstance(result.data, list) else []
        return CachedResponse(
            data=[ChampionshipListItem(**item) for item in items],
            stale=result.stale,
        )

    async def get_championship(
        self, championship_id: int, *, force: bool = False
    ) -> CachedResponse:
        key = f"championship_{championship_id}"
        if not force:
            cached = await read_cache(key, _CACHE_TTL)
            if cached is not None:
                return CachedResponse(data=ChampionshipDetails(**cached))

        result = await self._request(
            f"/api/v1/championships/{championship_id}", key,
        )
        return CachedResponse(
            data=ChampionshipDetails(**result.data),
            stale=result.stale,
        )

    async def get_races(
        self, championship_id: int, *, force: bool = False
    ) -> CachedResponse:
        key = f"races_{championship_id}"
        if not force:
            cached = await read_cache(key, _CACHE_TTL)
            if cached is not None:
                return CachedResponse(data=cached if isinstance(cached, list) else [])

        result = await self._request(
            "/api/v1/races", key, params={"championship_id": championship_id}
        )
        items = result.data if isinstance(result.data, list) else []
        return CachedResponse(data=items, stale=result.stale)

    async def get_standings(
        self, championship_id: int, *, force: bool = False
    ) -> CachedResponse:
        key = f"standings_{championship_id}"
        if not force:
            cached = await read_cache(key, _CACHE_TTL)
            if cached is not None:
                return CachedResponse(data=ChampionshipStandingsData(**cached))

        try:
            resp = await self._client.get(
                f"/api/v1/championships/{championship_id}/standings"
            )
            resp.raise_for_status()
            data = self._parse_standings(resp.json())
            await write_cache(key, data.model_dump())
            return CachedResponse(data=data)
        except httpx.HTTPStatusError:
            logger.warning(
                "SimGrid API error for %s, attempting stale cache fallback",
                key, exc_info=True,
            )
            stale = await read_stale_cache(key)
            if stale is not None:
                return CachedResponse(
                    data=ChampionshipStandingsData(**stale), stale=True,
                )
            raise

    async def get_participating_users(
        self, championship_id: int, *, force: bool = False
    ) -> CachedResponse:
        key = f"participants_{championship_id}"
        if not force:
            cached = await read_cache(key, _CACHE_TTL)
            if cached is not None:
                return CachedResponse(data=[ParticipatingUser(**u) for u in cached])

        result = await self._request(
            f"/api/v1/championships/{championship_id}/participating_users", key,
        )
        items = result.data if isinstance(result.data, list) else []
        return CachedResponse(
            data=[ParticipatingUser(**u) for u in items],
            stale=result.stale,
        )

    # ------------------------------------------------------------------
    # HTTP helper with stale-cache fallback
    # ------------------------------------------------------------------

    async def _request(
        self,
        url: str,
        cache_key: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> CachedResponse:
        """GET from SimGrid API with stale-cache fallback on upstream errors."""
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            await write_cache(cache_key, data)
            return CachedResponse(data=data)
        except httpx.HTTPStatusError:
            logger.warning(
                "SimGrid API error for %s, attempting stale cache fallback",
                cache_key, exc_info=True,
            )
            stale = await read_stale_cache(cache_key)
            if stale is not None:
                return CachedResponse(data=stale, stale=True)
            raise

    # ------------------------------------------------------------------
    # Standings parsing
    # ------------------------------------------------------------------

    def _parse_standings(self, payload: Any) -> ChampionshipStandingsData:
        if not isinstance(payload, list):
            return ChampionshipStandingsData()

        races = self._parse_races(payload[1] if len(payload) > 1 else None)
        entries_raw = (
            payload[0]
            if len(payload) > 0 and isinstance(payload[0], list)
            else []
        )
        entries = sorted(
            [self._parse_entry(e, races) for e in entries_raw],
            key=lambda e: (
                e.position if e.position is not None else float("inf"),
                -e.score,
                e.display_name,
            ),
        )
        return ChampionshipStandingsData(entries=entries, races=races)

    def _parse_races(self, value: Any) -> list[StandingRace]:
        if not isinstance(value, list):
            return []
        result: list[StandingRace] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            result.append(
                StandingRace(
                    id=int(item.get("id", 0)),
                    display_name=(
                        item.get("display_name")
                        or item.get("race_name")
                        or "Race"
                    ),
                    starts_at=item.get("starts_at"),
                    results_available=bool(item.get("results_available")),
                    ended=bool(item.get("ended")),
                )
            )
        return result

    def _parse_entry(
        self, raw: dict[str, Any], races: list[StandingRace]
    ) -> StandingEntry:
        partial = raw.get("partial_standings")
        if not isinstance(partial, list) or not partial:
            partial = raw.get("overall_partial_standings")

        participant = raw.get("participant") or {}
        champ_class = raw.get("championship_car_class") or {}
        car_class = (
            raw.get("class")
            or raw.get("car_class")
            or raw.get("category")
            or (
                champ_class.get("display_name")
                if isinstance(champ_class, dict)
                else None
            )
            or ""
        )

        points = self._num(raw.get("championship_points"), 0.0)
        penalties = self._num(raw.get("championship_penalties"), 0.0)
        score = self._num(raw.get("championship_score"), 0.0)

        return StandingEntry(
            id=int(raw.get("user_id") or raw.get("id") or 0),
            position=self._opt_int(raw.get("position_cache")),
            display_name=raw.get("display_name") or "Unknown driver",
            country_code=participant.get("country_code") or "",
            car=raw.get("car") or "",
            car_class=car_class,
            points=points,
            penalties=penalties,
            score=score,
            race_results=self._parse_race_results(partial, races),
        )

    def _parse_race_results(
        self, value: Any, races: list[StandingRace]
    ) -> list[DriverRaceResult]:
        if not isinstance(value, list):
            return []
        results: list[DriverRaceResult] = []
        for idx, item in enumerate(value):
            race_id = races[idx].id if idx < len(races) else None

            if isinstance(item, (int, float)):
                results.append(
                    DriverRaceResult(
                        race_id=race_id,
                        race_index=idx,
                        position=int(item) if item == item else None,
                    )
                )
                continue

            if not isinstance(item, dict):
                results.append(
                    DriverRaceResult(race_id=race_id, race_index=idx)
                )
                continue

            pts = item.get("points") or item.get("championship_points")
            pos = item.get("position") or item.get("position_cache")
            rid = item.get("race_id") or item.get("id")
            if rid is None:
                rid = race_id

            results.append(
                DriverRaceResult(
                    race_id=self._opt_int(rid),
                    race_index=idx,
                    points=self._opt_num(pts),
                    position=self._opt_int(pos),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Tiny conversion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _opt_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _num(value: Any, default: float) -> float:
        try:
            v = float(value)
            return v if v == v else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _opt_num(value: Any) -> float | None:
        try:
            v = float(value)
            return v if v == v else None
        except (TypeError, ValueError):
            return None

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

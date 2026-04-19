"""Server-side proxy for The SimGrid API.

Moves the API key and all parsing logic to the backend so the frontend
never touches SimGrid directly.  Responses are cached in the database
for 10 minutes to avoid hammering the SimGrid API.
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
    ChampionshipPodium,
    ChampionshipStandingsData,
    DriverChampionshipResult,
    DriverRaceResult,
    ParticipatingUser,
    PodiumEntry,
    StandingEntry,
    StandingRace,
)
from app.services.cache import (
    invalidate_cache_by_keys,
    invalidate_cache_by_prefix,
    read_all_by_prefix,
    read_cache,
    read_stale_cache,
    write_cache,
)

_TTL_STATIC = timedelta(days=1)     # championships list, details, races
_TTL_LIVE = timedelta(minutes=10)   # standings, participants
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
        cached = await read_cache(key, _TTL_LIVE)
        if cached is not None:
            return ChampionshipStandingsData(**cached)

        try:
            resp = await self._client.get(
                f"/api/v1/championships/{championship_id}/standings"
            )
            resp.raise_for_status()
            data = self._parse_standings(resp.json())
            await write_cache(key, data.model_dump())
            return data
        except httpx.HTTPStatusError:
            logger.warning(
                "SimGrid API error for %s, attempting stale cache fallback",
                key, exc_info=True,
            )
            stale = await read_stale_cache(key)
            if stale is not None:
                mark_stale()
                return ChampionshipStandingsData(**stale)
            raise

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

    # ------------------------------------------------------------------
    # Aggregate views derived from cached standings
    # ------------------------------------------------------------------

    async def build_champions_podiums(
        self, active_ids: set[int],
    ) -> list[ChampionshipPodium]:
        """Return top-3 podiums for finished championships (not in *active_ids*).

        Reads cached standings entries directly so completed seasons remain
        viewable even after the SimGrid API drops them from active rotation.
        """
        cached_standings = await read_all_by_prefix("standings_")
        champ_map = await self._championship_map()

        podiums: list[ChampionshipPodium] = []
        for cache_key, raw in cached_standings:
            champ_id = self._championship_id_from_cache_key(cache_key)
            if champ_id is None or champ_id in active_ids:
                continue
            standings = self._standings_from_cache(raw)
            if standings is None:
                continue

            top3 = sorted(
                (e for e in standings.entries if e.position in (1, 2, 3) and not e.dsq),
                key=lambda e: e.position or 999,
            )
            if not top3:
                continue

            champ = champ_map.get(champ_id)
            podiums.append(ChampionshipPodium(
                championship_id=champ_id,
                championship_name=champ.name if champ else f"Championship #{champ_id}",
                podium=[
                    PodiumEntry(
                        simgrid_driver_id=e.id,
                        display_name=e.display_name,
                        position=e.position or 0,
                    )
                    for e in top3
                ],
            ))

        podiums.sort(key=lambda p: -p.championship_id)
        return podiums

    async def find_driver_championship_results(
        self, simgrid_driver_id: int,
    ) -> list[DriverChampionshipResult]:
        """Return per-championship results for *simgrid_driver_id* across all caches."""
        cached_standings = await read_all_by_prefix("standings_")
        champ_map = await self._championship_map()

        results: list[DriverChampionshipResult] = []
        for cache_key, raw in cached_standings:
            champ_id = self._championship_id_from_cache_key(cache_key)
            if champ_id is None:
                continue
            standings = self._standings_from_cache(raw)
            if standings is None:
                continue

            entry = next(
                (e for e in standings.entries if e.id == simgrid_driver_id), None
            )
            if entry is None:
                continue

            champ = champ_map.get(champ_id)
            results.append(DriverChampionshipResult(
                championship_id=champ_id,
                championship_name=champ.name if champ else f"Championship #{champ_id}",
                position=entry.position,
                score=entry.score,
                dsq=entry.dsq,
                start_date=champ.start_date if champ else None,
                end_date=champ.end_date if champ else None,
                accepting_registrations=champ.accepting_registrations if champ else False,
            ))

        results.sort(
            key=lambda r: (r.position is None, r.position or 999, -r.championship_id)
        )
        return results

    async def _championship_map(self) -> dict[int, ChampionshipListItem]:
        """Build a championship-id → list-item lookup, tolerating upstream failures."""
        try:
            return {c.id: c for c in await self.get_championships()}
        except Exception:
            logger.warning(
                "Failed to fetch championships for cache lookup", exc_info=True
            )
            return {}

    @staticmethod
    def _championship_id_from_cache_key(cache_key: str) -> int | None:
        try:
            return int(cache_key.split("_", 1)[1])
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _standings_from_cache(raw: Any) -> ChampionshipStandingsData | None:
        if not isinstance(raw, dict):
            return None
        try:
            return ChampionshipStandingsData(**raw)
        except Exception:
            return None

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
        sorted_races = sorted(races, key=lambda r: r.starts_at or "")
        return ChampionshipStandingsData(entries=entries, races=sorted_races)

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

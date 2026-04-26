"""Server-side proxy for The SimGrid API.

Moves the API key and all parsing logic to the backend so the frontend
never touches SimGrid directly.  Responses are cached in the database
to avoid hammering the SimGrid API.  Standings are scraped from the
HTML page (see ``simgrid_scraper``) since the REST API no longer
populates ``partial_standings``.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import httpx

from app.config import settings
from app.middleware import mark_stale
from app.services.simgrid_scraper import scrape_standings
from app.schemas.championship import (
    ChampionshipDetails,
    ChampionshipListItem,
    ChampionshipPodium,
    ChampionshipStandingsData,
    DriverChampionshipResult,
    ParticipatingUser,
    PodiumEntry,
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
_TTL_LIVE = timedelta(minutes=10)   # participants
_TTL_SCRAPE = timedelta(hours=1)    # standings (HTML scraping is heavier)
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
        cached = await read_cache(key, _TTL_SCRAPE)
        if cached is not None:
            return ChampionshipStandingsData(**cached)

        try:
            data = await scrape_standings(championship_id)
            if data is None:
                raise RuntimeError("Scraping returned no data")
            data = await self._enrich_races(championship_id, data)
            await write_cache(key, data.model_dump())
            return data
        except Exception:
            logger.warning(
                "Scraping failed for %s, attempting stale cache fallback",
                key, exc_info=True,
            )
            stale = await read_stale_cache(key)
            if stale is not None:
                mark_stale()
                return ChampionshipStandingsData(**stale)
            raise

    async def _enrich_races(
        self,
        championship_id: int,
        data: ChampionshipStandingsData,
    ) -> ChampionshipStandingsData:
        """Fill race metadata (display_name, starts_at, ended) from the API."""
        try:
            api_races = await self.get_races(championship_id)
            lookup = {r["id"]: r for r in api_races if isinstance(r, dict)}
            enriched = []
            for race in data.races:
                info = lookup.get(race.id, {})
                enriched.append(race.model_copy(update={
                    "display_name": (
                        info.get("display_name")
                        or info.get("race_name")
                        or race.display_name
                    ),
                    "starts_at": info.get("starts_at") or race.starts_at,
                    "results_available": info.get(
                        "results_available", race.results_available,
                    ),
                    "ended": info.get("ended", race.ended),
                }))
            return data.model_copy(update={"races": enriched})
        except Exception:
            logger.warning(
                "Race enrichment failed for %d", championship_id,
                exc_info=True,
            )
            return data

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

"""Server-side proxy for The SimGrid API.

Moves the API key and all parsing logic to the backend so the frontend
never touches SimGrid directly.  Responses are cached in the database
for 10 minutes to avoid hammering the SimGrid API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select, delete

from app.config import settings
from app.database import async_session
from app.models.simgrid_cache import SimgridCache
from app.schemas.championship import (
    ChampionshipDetails,
    ChampionshipListItem,
    ChampionshipStandingsData,
    DriverRaceResult,
    StandingEntry,
    StandingRace,
)

_CACHE_TTL = timedelta(minutes=10)
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

    async def get_championships(self, limit: int = 200, *, force: bool = False) -> list[ChampionshipListItem]:
        cache_key = f"championships_list_{limit}"

        if not force:
            cached = await self._read_cache(cache_key)
            if cached is not None:
                return [ChampionshipListItem(**item) for item in cached]

        try:
            resp = await self._client.get(
                "/api/v1/championships",
                params={"limit": limit, "offset": 0},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                stale = await self._read_stale_cache(cache_key)
                if stale is not None:
                    return [ChampionshipListItem(**item) for item in stale]
            raise
        items = resp.json()
        await self._write_cache(cache_key, items)
        return [ChampionshipListItem(**item) for item in items]

    async def get_championship(self, championship_id: int, *, force: bool = False) -> ChampionshipDetails:
        cache_key = f"championship_{championship_id}"

        if not force:
            cached = await self._read_cache(cache_key)
            if cached is not None:
                return ChampionshipDetails(**cached)

        try:
            resp = await self._client.get(f"/api/v1/championships/{championship_id}")
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                stale = await self._read_stale_cache(cache_key)
                if stale is not None:
                    return ChampionshipDetails(**stale)
            raise
        raw = resp.json()
        await self._write_cache(cache_key, raw)
        return ChampionshipDetails(**raw)

    async def get_races(self, championship_id: int, *, force: bool = False) -> list[dict]:
        """Fetch ALL races for a championship (including future ones)."""
        cache_key = f"races_{championship_id}"

        if not force:
            cached = await self._read_cache(cache_key)
            if cached is not None:
                return cached if isinstance(cached, list) else []

        try:
            resp = await self._client.get(
                "/api/v1/races",
                params={"championship_id": championship_id},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                stale = await self._read_stale_cache(cache_key)
                if stale is not None:
                    return stale if isinstance(stale, list) else []
            raise

        data = resp.json()
        items = data if isinstance(data, list) else (data.get("races") if isinstance(data, dict) else [])
        await self._write_cache(cache_key, items)
        return items

    async def get_standings(self, championship_id: int, *, force: bool = False) -> ChampionshipStandingsData:
        cache_key = f"standings_{championship_id}"

        if not force:
            cached = await self._read_cache(cache_key)
            if cached is not None:
                return ChampionshipStandingsData(**cached)

        try:
            resp = await self._client.get(
                f"/api/v1/championships/{championship_id}/standings"
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                stale = await self._read_stale_cache(cache_key)
                if stale is not None:
                    return ChampionshipStandingsData(**stale).model_copy(update={"stale": True})
            raise

        payload = resp.json()
        data = self._parse_standings(payload)

        await self._write_cache(cache_key, data.model_dump())
        return data

    # ------------------------------------------------------------------
    # Standings parsing (ported from Angular SimgridApiService)
    # ------------------------------------------------------------------

    def _parse_standings(self, payload: Any) -> ChampionshipStandingsData:
        if not isinstance(payload, list):
            return ChampionshipStandingsData()

        races = self._parse_races(payload[1] if len(payload) > 1 else None)
        entries_raw = payload[0] if len(payload) > 0 and isinstance(payload[0], list) else []
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
                    id=self._to_int(item.get("id")),
                    display_name=self._to_text(
                        item.get("display_name") or item.get("race_name"), "Race"
                    ),
                    starts_at=self._to_nullable_text(item.get("starts_at")),
                    results_available=bool(item.get("results_available")),
                    ended=bool(item.get("ended")),
                )
            )
        return result

    def _parse_entry(self, raw: dict[str, Any], races: list[StandingRace]) -> StandingEntry:
        partial = (
            raw.get("partial_standings")
            if isinstance(raw.get("partial_standings"), list)
            and len(raw.get("partial_standings", []))
            else raw.get("overall_partial_standings")
        )
        participant = raw.get("participant") or {}
        # "class" is the most common field name in SimGrid responses
        champ_class = raw.get("championship_car_class") or {}
        car_class = self._to_text(
            raw.get("class")
            or raw.get("class_name")
            or raw.get("car_class_name")
            or raw.get("car_class")
            or raw.get("category_name")
            or raw.get("category")
            or (champ_class.get("display_name") if isinstance(champ_class, dict) else None),
            "",
        )
        return StandingEntry(
            id=self._to_int(raw.get("user_id") or raw.get("id")),
            position=self._to_nullable_int(raw.get("position_cache")),
            display_name=self._to_text(raw.get("display_name"), "Unknown driver"),
            country_code=self._to_text(participant.get("country_code"), ""),
            car=self._to_text(raw.get("car"), ""),
            car_class=car_class,
            points=self._to_float(raw.get("championship_points")),
            penalties=self._to_float(raw.get("championship_penalties")),
            score=self._to_float(raw.get("championship_score")),
            race_results=self._parse_race_results(partial, races),
        )

    def _parse_race_results(
        self, value: Any, races: list[StandingRace]
    ) -> list[DriverRaceResult]:
        if not isinstance(value, list):
            return []
        results: list[DriverRaceResult] = []
        for idx, item in enumerate(value):
            if isinstance(item, (int, float)):
                results.append(
                    DriverRaceResult(
                        race_id=races[idx].id if idx < len(races) else None,
                        race_index=idx,
                        points=None,
                        position=int(item) if item == item else None,
                    )
                )
                continue
            if not isinstance(item, dict):
                results.append(
                    DriverRaceResult(race_id=None, race_index=idx, points=None, position=None)
                )
                continue
            pts = (
                item.get("points")
                or item.get("championship_points")
                or item.get("score")
                or item.get("championship_score")
            )
            race_id_candidate = (
                item.get("race_id") or item.get("raceId") or item.get("id")
            )
            if race_id_candidate is None and idx < len(races):
                race_id_candidate = races[idx].id
            pos = item.get("position") or item.get("position_cache") or item.get("rank")
            results.append(
                DriverRaceResult(
                    race_id=self._to_nullable_int(race_id_candidate),
                    race_index=idx,
                    points=self._to_nullable_float(pts),
                    position=self._to_nullable_int(pos),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            v = int(value)
            return v
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_nullable_int(value: Any) -> int | None:
        try:
            v = int(value)
            return v
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            v = float(value)
            return v if v == v else 0.0  # NaN check
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _to_nullable_float(value: Any) -> float | None:
        try:
            v = float(value)
            return v if v == v else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_text(value: Any, fallback: str) -> str:
        if isinstance(value, str) and value.strip():
            return value
        return fallback

    @staticmethod
    def _to_nullable_text(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value
        return None

    # ------------------------------------------------------------------
    # Database cache helpers
    # ------------------------------------------------------------------

    async def _read_cache(self, key: str) -> dict | list | None:
        """Return cached JSON data if present and not expired, else None."""
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
                return row.data  # type: ignore[return-value]
        except Exception:
            logger.warning("DB cache read failed for key=%s", key, exc_info=True)
            return None

    async def _read_stale_cache(self, key: str) -> dict | list | None:
        """Return cached JSON data ignoring TTL (used as fallback on 429)."""
        try:
            async with async_session() as session:
                row = (
                    await session.execute(
                        select(SimgridCache).where(SimgridCache.cache_key == key)
                    )
                ).scalar_one_or_none()
                if row is None:
                    return None
                return row.data  # type: ignore[return-value]
        except Exception:
            logger.warning("DB stale cache read failed for key=%s", key, exc_info=True)
            return None

    async def _write_cache(self, key: str, data: Any) -> None:
        """Upsert a JSON blob into the cache table."""
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

    async def invalidate_cache(self, championship_id: int | None = None) -> None:
        """Delete cached entries. If championship_id given, only that one."""
        try:
            async with async_session() as session:
                if championship_id is not None:
                    await session.execute(
                        delete(SimgridCache).where(
                            SimgridCache.cache_key.in_([
                                f"championship_{championship_id}",
                                f"standings_{championship_id}",
                            ])
                        )
                    )
                else:
                    await session.execute(delete(SimgridCache))
                await session.commit()
        except Exception:
            logger.warning("DB cache invalidation failed", exc_info=True)


simgrid_service = SimgridService()

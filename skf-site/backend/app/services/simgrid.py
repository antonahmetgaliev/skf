"""Server-side proxy for The SimGrid API.

Moves the API key and all parsing logic to the backend so the frontend
never touches SimGrid directly.  Responses are cached in the database
for 10 minutes to avoid hammering the SimGrid API.
"""

from __future__ import annotations

import html as html_mod
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from curl_cffi import requests as cf_requests
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
        # Separate session for HTML page fetches – curl_cffi impersonates
        # a real browser TLS fingerprint so Cloudflare lets us through.
        self._cf_session = cf_requests.Session(impersonate="chrome")

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

        # Scrape the public HTML standings page when we need:
        #  a) race-by-race positions that the API didn't include, OR
        #  b) car-class info (multiclass championships)
        # Use curl_cffi (browser-impersonation) because the SimGrid site
        # sits behind Cloudflare which rejects plain httpx requests.
        needs_race_pos = not self._has_race_positions(data) and len(data.races) > 0
        needs_class   = any(not e.car_class for e in data.entries if e.car)
        if (needs_race_pos or needs_class) and len(data.entries) > 0:
            try:
                html_resp = self._cf_session.get(
                    f"{settings.simgrid_base_url}/championships/{championship_id}/standings",
                    timeout=30,
                )
                if html_resp.status_code == 200:
                    data = self._merge_html_race_positions(data, html_resp.text)
                    # Discover additional class pages (e.g. LMGT3 when default is Hypercar)
                    extra_classes = self._extract_class_filters(html_resp.text)
                    for class_name, filter_id in extra_classes:
                        try:
                            cls_resp = self._cf_session.get(
                                f"{settings.simgrid_base_url}/championships/{championship_id}"
                                f"/standings?filter_class={filter_id}&overall=0",
                                timeout=30,
                            )
                            if cls_resp.status_code == 200:
                                extra_entries = self._extract_entries_from_class_html(
                                    cls_resp.text, data.races, class_name
                                )
                                existing_ids = {e.id for e in data.entries}
                                new_entries = [e for e in extra_entries if e.id not in existing_ids]
                                if new_entries:
                                    data = ChampionshipStandingsData(
                                        entries=data.entries + new_entries,
                                        races=data.races,
                                        stale=data.stale,
                                    )
                        except Exception:
                            pass
            except Exception:
                pass

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
        car_class = self._to_text(
            raw.get("class_name")
            or raw.get("car_class_name")
            or raw.get("car_class")
            or raw.get("category_name")
            or raw.get("category"),
            "",
        )
        return StandingEntry(
            id=self._to_int(raw.get("id")),
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
    # HTML scraping fallback (ported from Angular)
    # ------------------------------------------------------------------

    def _has_race_positions(self, data: ChampionshipStandingsData) -> bool:
        return any(
            r.position is not None
            for e in data.entries
            for r in e.race_results
        )

    def _merge_html_race_positions(
        self, data: ChampionshipStandingsData, html: str
    ) -> ChampionshipStandingsData:
        snapshot = self._extract_html_standings(html)
        if not snapshot or not snapshot["race_columns"] or not snapshot["rows"]:
            return data

        races = list(data.races)
        for idx, col in enumerate(snapshot["race_columns"]):
            if idx >= len(races):
                races.append(
                    StandingRace(
                        id=col["race_id"] or -(idx + 1),
                        display_name=f"Race {idx + 1}",
                    )
                )

        used: set[int] = set()
        entries: list[StandingEntry] = []
        for entry_idx, entry in enumerate(data.entries):
            row_idx = self._find_html_row(entry, entry_idx, snapshot["rows"], used)
            if row_idx < 0:
                entries.append(entry)
                continue
            used.add(row_idx)
            row = snapshot["rows"][row_idx]
            merged_results = self._merge_race_results(
                entry.race_results, row["race_cells"], races
            )
            update: dict[str, Any] = {"race_results": merged_results}
            if row.get("dsq"):
                update["dsq"] = True
            # Fill car_class from HTML when the API didn't supply it
            if not entry.car_class and row.get("car_class"):
                update["car_class"] = row["car_class"]
            entries.append(entry.model_copy(update=update))

        return ChampionshipStandingsData(entries=entries, races=races)

    def _extract_class_filters(self, html: str) -> list[tuple[str, str]]:
        """Return [(class_name, filter_id), ...] for non-default classes found
        in the SimGrid standings class-filter dropdown."""
        matches = re.findall(
            r'filter_class=(\d+)&(?:amp;)?overall=0"[^>]*>\s*([^<]{2,40}?)\s*</a>',
            html, re.I,
        )
        return [(name.strip(), fid) for fid, name in matches]

    def _extract_entries_from_class_html(
        self, html: str, races: list[StandingRace], class_name: str
    ) -> list[StandingEntry]:
        """Build StandingEntry objects from a class-filtered standings HTML page."""
        snapshot = self._extract_html_standings(html)
        if not snapshot or not snapshot["rows"]:
            return []

        entries: list[StandingEntry] = []
        for row in snapshot["rows"]:
            race_results = self._build_race_results_from_html(
                row["race_cells"], row.get("race_points", []), races
            )
            entry = StandingEntry(
                id=row.get("driver_id", 0),
                position=row.get("position"),
                display_name=row.get("display_name") or row.get("normalized_name", "Unknown"),
                country_code=row.get("country_code", ""),
                car=row.get("car", ""),
                car_class=row.get("car_class") or class_name,
                score=row.get("score", 0.0),
                dsq=row.get("dsq", False),
                race_results=race_results,
            )
            entries.append(entry)
        return entries

    def _build_race_results_from_html(
        self,
        race_cells: list[tuple[int | None, bool]],
        race_points: list[float],
        races: list[StandingRace],
    ) -> list[DriverRaceResult]:
        results: list[DriverRaceResult] = []
        for idx, (pos, is_dns) in enumerate(race_cells):
            pts = race_points[idx] if idx < len(race_points) else None
            results.append(
                DriverRaceResult(
                    race_id=races[idx].id if idx < len(races) else None,
                    race_index=idx,
                    points=pts,
                    position=pos,
                    dns=is_dns,
                )
            )
        return results

    def _flag_emoji_to_code(self, text: str) -> str:
        """Convert a flag emoji (e.g. 🇺🇦) to a 2-letter ISO country code."""
        flags = re.findall(r"[\U0001F1E0-\U0001F1FF]{2}", text)
        if not flags:
            return ""
        return "".join(chr(ord(c) - 0x1F1E6 + ord("A")) for c in flags[0])

    def _extract_html_standings(self, html: str) -> dict[str, Any] | None:
        table_match = re.search(
            r'<table[^>]*class="[^"]*table-results[^"]*table-v2[^"]*"[^>]*>[\s\S]*?</table>',
            html,
            re.I,
        )
        if not table_match:
            return None

        table_html = table_match.group(0)
        race_columns: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for m in re.finditer(r"race_id=(\d+)", table_html):
            race_id = int(m.group(1))
            if race_id in seen_ids:
                continue
            seen_ids.add(race_id)
            race_columns.append({"race_id": race_id, "race_index": len(race_columns)})

        rows: list[dict[str, Any]] = []
        for row_match in re.finditer(r"<tr[\s\S]*?</tr>", table_html, re.I):
            row_html = row_match.group(0)
            if "entrant-name" not in row_html:
                continue
            name_match = re.search(
                r'class="entrant-name[^"]*"[^>]*>([\s\S]*?)</a>', row_html, re.I
            )
            normalized = self._normalize_name(self._strip_html(name_match.group(1) if name_match else ""))
            pos_match = re.search(
                r'class="[^"]*result-position[^"]*"[^>]*>[\s\S]*?<strong>\s*([^<]+)\s*</strong>',
                row_html,
                re.I,
            )
            position = self._parse_html_int(pos_match.group(1) if pos_match else None)
            # Each race cell has:
            #   <span class="show_positions">
            #       X<span class="text-secondary mx-1">·</span>Y
            #   </span>
            # where X = qualifying position, Y = race finish position.
            # We use a greedy inner match so the capture reaches the
            # outer </span> rather than stopping at the first nested one.
            race_pos_matches = re.findall(
                r'<span class="show_positions">([\s\S]*?)</span>\s*(?=<span class="show_points|</td>)',
                row_html,
                re.I,
            )
            race_cells = [
                self._parse_html_race_cell(
                    self._strip_html(race_pos_matches[i]) if i < len(race_pos_matches) else ""
                )
                for i in range(len(race_columns))
            ]
            # Championship-level DSQ badge:
            # <span class="upcase badge bg-red" title="Disqualified">DSQ</span>
            is_dsq = bool(re.search(
                r'<span[^>]*title="Disqualified"[^>]*>\s*DSQ\s*</span>',
                row_html, re.I,
            ))
            # Car class: <span class="car-class"> Hypercar </span>
            car_class_match = re.search(
                r'class="car-class"[^>]*>\s*([^<]+?)\s*</span>',
                row_html, re.I,
            )
            car_class = car_class_match.group(1).strip() if car_class_match else ""
            # SimGrid driver ID from href: /drivers/{id}-name/grid_feed
            driver_id_match = re.search(r'href="/drivers/(\d+)-[^/"]+', row_html, re.I)
            driver_id = int(driver_id_match.group(1)) if driver_id_match else 0
            # Display name: text in entrant-name link before the first nested <span>
            display_name_match = re.search(
                r'class="entrant-name[^"]*"[^>]*>([\s\S]*?)(?=<span|</a>)', row_html, re.I
            )
            raw_name = self._strip_html(display_name_match.group(1) if display_name_match else "")
            # Strip flag emoji regional indicators (🇺🇦 etc.) and whitespace
            display_name = re.sub(r"[\U0001F1E0-\U0001F1FF]", "", raw_name).strip()
            country_code = self._flag_emoji_to_code(
                display_name_match.group(1) if display_name_match else ""
            )
            # Car name: <span class="d-lg-inline d-none fs-xs"> BMW M4 GT3 </span>
            car_match = re.search(
                r'class="d-lg-inline d-none fs-xs"\s*>\s*([^<]+?)\s*</span>', row_html, re.I
            )
            car = car_match.group(1).strip() if car_match else ""
            # Total score: <td class="text-center fw-bold"> 41 </td>
            score_match = re.search(
                r'<td[^>]*text-center fw-bold[^>]*>\s*([\d\.]+)\s*</td>', row_html, re.I
            )
            score = float(score_match.group(1)) if score_match else 0.0
            # Per-race points: <span class="show_points d-none"> 25 </span>
            race_points = [
                float(p) for p in re.findall(
                    r'class="show_points[^"]*"[^>]*>\s*([\d\.]+)\s*</span>', row_html, re.I
                )
            ]
            rows.append(
                {
                    "normalized_name": normalized,
                    "display_name": display_name,
                    "country_code": country_code,
                    "driver_id": driver_id,
                    "car": car,
                    "car_class": car_class,
                    "score": score,
                    "race_points": race_points,
                    "position": position,
                    "race_cells": race_cells,
                    "dsq": is_dsq,
                }
            )

        return {"race_columns": race_columns, "rows": rows} if rows else None

    def _find_html_row(
        self,
        entry: StandingEntry,
        entry_idx: int,
        rows: list[dict[str, Any]],
        used: set[int],
    ) -> int:
        norm = self._normalize_name(entry.display_name)
        for i, row in enumerate(rows):
            if i not in used and row["normalized_name"] == norm:
                return i
        if entry.position is not None:
            for i, row in enumerate(rows):
                if i not in used and row["position"] == entry.position:
                    return i
        if entry_idx < len(rows) and entry_idx not in used:
            return entry_idx
        return -1

    def _merge_race_results(
        self,
        current: list[DriverRaceResult],
        html_cells: list[tuple[int | None, bool]],
        races: list[StandingRace],
    ) -> list[DriverRaceResult]:
        by_index: dict[int, DriverRaceResult] = {r.race_index: r for r in current}
        for race_idx, (pos, is_dns) in enumerate(html_cells):
            existing = by_index.get(race_idx)
            if existing:
                by_index[race_idx] = existing.model_copy(
                    update={
                        "race_id": existing.race_id
                        or (races[race_idx].id if race_idx < len(races) else None),
                        "position": existing.position or pos,
                        "dns": existing.dns or is_dns,
                    }
                )
            elif pos is not None or is_dns:
                by_index[race_idx] = DriverRaceResult(
                    race_id=races[race_idx].id if race_idx < len(races) else None,
                    race_index=race_idx,
                    points=None,
                    position=pos,
                    dns=is_dns,
                )
        return sorted(by_index.values(), key=lambda r: r.race_index)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_html(value: str) -> str:
        text = re.sub(r"<[^>]*>", " ", value)
        text = html_mod.unescape(text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _normalize_name(value: str) -> str:
        nfkd = unicodedata.normalize("NFKD", value).lower()
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", nfkd)).strip()

    @staticmethod
    def _parse_html_int(value: str | None) -> int | None:
        if not value:
            return None
        m = re.search(r"-?\d+", value)
        return int(m.group(0)) if m else None

    @staticmethod
    def _parse_html_race_cell(value: str | None) -> tuple[int | None, bool]:
        """Extract the race **finish** position and DNS flag from scraped text.

        SimGrid standings cells show ``"X · Y"`` where X is the
        qualifying position and Y is the race finish position.

        Returns ``(position, is_dns)``:
        - ``(5, False)``  – "3 · 5"  → finished in P5
        - ``(None, True)`` – "DNS · DNS" → Did Not Start
        - ``(None, True)`` – "15 · DNS" → qualified but DNS race
        - ``(7, False)``   – "DNS · 7"  → DNS quali, finished P7
        - ``(None, False)`` – "—" or empty → no data / did not enter
        """
        if not value:
            return (None, False)
        cleaned = re.sub(r"[\u200b-\u200f\ufeff]", "", value).strip()
        if not cleaned or cleaned in ("-", "\u2014"):
            return (None, False)

        # Split on the middle-dot separator to isolate quali vs race parts.
        # The raw (stripped) text looks like "3 · 5", "DNS · DNS", "15 · DNS".
        parts = re.split(r"\s*[·]\s*", cleaned)

        if len(parts) >= 2:
            race_part = parts[-1].strip()
        else:
            race_part = cleaned

        race_is_dns = bool(re.search(r"(?i)\bDNS\b", race_part))
        numbers = re.findall(r"-?\d+", race_part)
        position = int(numbers[-1]) if numbers else None
        return (position, race_is_dns or (position is None and bool(re.search(r"(?i)\bDNS\b", cleaned))))

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

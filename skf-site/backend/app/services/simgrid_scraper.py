"""Scrape SimGrid HTML standings pages for per-race results.

The SimGrid REST API returns empty ``partial_standings``, so the only
way to get per-race positions and points is to scrape the public
standings page.  ``curl_cffi`` is used to impersonate a browser TLS
fingerprint so Cloudflare lets us through.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from bs4 import BeautifulSoup, Tag
from curl_cffi import requests as cf_requests

from app.config import settings
from app.schemas.championship import (
    ChampionshipStandingsData,
    DriverRaceResult,
    StandingEntry,
    StandingRace,
)

logger = logging.getLogger(__name__)

_session = cf_requests.Session(impersonate="chrome")


async def scrape_standings(
    championship_id: int,
) -> ChampionshipStandingsData | None:
    """Fetch and parse the HTML standings page for *championship_id*.

    Returns ``None`` when the page cannot be fetched or parsed.
    """
    url = (
        f"{settings.simgrid_base_url}"
        f"/championships/{championship_id}/standings"
    )
    html = await _fetch_html(url)
    if html is None:
        return None
    return _parse_standings_html(html)


# ------------------------------------------------------------------
# HTML fetching
# ------------------------------------------------------------------

async def _fetch_html(url: str) -> str | None:
    """GET *url* via curl_cffi in a thread (it's synchronous)."""
    try:
        resp = await asyncio.to_thread(_session.get, url, timeout=30)
        if resp.status_code != 200:
            logger.warning("Scrape returned %d for %s", resp.status_code, url)
            return None
        return resp.text
    except Exception:
        logger.warning("Scrape failed for %s", url, exc_info=True)
        return None


# ------------------------------------------------------------------
# HTML parsing
# ------------------------------------------------------------------

def _parse_standings_html(html: str) -> ChampionshipStandingsData | None:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find(
        "table",
        class_=lambda c: c and "table-results" in c,
    )
    if not isinstance(table, Tag):
        logger.warning("No table-results found in HTML")
        return None

    races = _parse_header_races(table)
    race_count = len(races)

    tbody = table.find("tbody")
    if not isinstance(tbody, Tag):
        logger.warning("No tbody found in standings table")
        return None

    entries: list[StandingEntry] = []
    for tr in tbody.find_all("tr", recursive=False):
        entry = _parse_row(tr, races, race_count)
        if entry is not None:
            entries.append(entry)

    entries.sort(
        key=lambda e: (
            e.position if e.position is not None else float("inf"),
            -e.score,
            e.display_name,
        ),
    )
    return ChampionshipStandingsData(entries=entries, races=races)


def _parse_header_races(table: Tag) -> list[StandingRace]:
    """Extract race IDs and labels from header links."""
    races: list[StandingRace] = []
    for link in table.find_all("a", href=re.compile(r"race_id=\d+")):
        m = re.search(r"race_id=(\d+)", link["href"])
        if not m:
            continue
        label = link.get_text(strip=True) or f"R{len(races) + 1}"
        races.append(
            StandingRace(
                id=int(m.group(1)),
                display_name=label,
            ),
        )
    return races


def _parse_row(
    tr: Tag, races: list[StandingRace], race_count: int,
) -> StandingEntry | None:
    tds = tr.find_all("td", recursive=False)
    if len(tds) < 3:
        return None

    # -- Position --
    position = _parse_position(tds[0])

    # -- Driver name, ID, country --
    driver_name, driver_id, country_code = _parse_driver(tds[1])
    if not driver_name:
        return None

    # -- Car class, vehicle, penalties, DSQ --
    # Layout: P | Driver | Rating | CarClass+Num | Vehicle | (empty) | Pen | R1..Rn | PTS
    # The race columns start after the Pen column and end before the PTS column.
    # We locate them by counting from the end: last td = PTS, preceding race_count tds = races.

    car_class = ""
    car = ""
    penalties = 0.0

    # Car class + number cell (index 3 on desktop layout)
    if len(tds) > 3:
        cls_span = tds[3].find("span", class_="car-class")
        if isinstance(cls_span, Tag):
            car_class = cls_span.get_text(strip=True)

    # Vehicle cell (index 4)
    if len(tds) > 4:
        car = tds[4].get_text(strip=True)

    # Penalties cell (index 6)
    if len(tds) > 6:
        pen_text = tds[6].get_text(strip=True)
        if pen_text:
            try:
                penalties = float(pen_text)
            except ValueError:
                pass

    # DSQ badge anywhere in the row
    dsq = tr.find(attrs={"title": "Disqualified"}) is not None

    # -- Total points (last td) --
    total_points = 0.0
    if tds:
        pts_text = tds[-1].get_text(strip=True)
        try:
            total_points = float(pts_text)
        except ValueError:
            pass

    # -- Per-race results --
    # Race tds are the `race_count` cells before the final PTS cell.
    race_results: list[DriverRaceResult] = []
    if race_count > 0 and len(tds) > race_count + 1:
        race_start = len(tds) - 1 - race_count
        for idx in range(race_count):
            td = tds[race_start + idx]
            race_id = races[idx].id if idx < len(races) else None
            pos, pts, dns = _parse_race_cell(td)
            race_results.append(
                DriverRaceResult(
                    race_id=race_id,
                    race_index=idx,
                    position=pos,
                    points=pts,
                    dns=dns,
                ),
            )

    score = total_points

    return StandingEntry(
        id=driver_id,
        position=position,
        display_name=driver_name,
        country_code=country_code,
        car=car,
        car_class=car_class,
        points=total_points + penalties,
        penalties=penalties,
        score=score,
        dsq=dsq,
        race_results=race_results,
    )


# ------------------------------------------------------------------
# Cell parsers
# ------------------------------------------------------------------

def _parse_position(td: Tag) -> int | None:
    text = td.get_text(strip=True)
    try:
        return int(text)
    except ValueError:
        return None


def _parse_driver(td: Tag) -> tuple[str, int, str]:
    """Return (display_name, driver_id, country_code)."""
    driver_id = 0
    link = td.find("a", class_="entrant-name")
    if isinstance(link, Tag):
        href = link.get("href", "")
        m = re.search(r"/drivers/(\d+)", href)
        if m:
            driver_id = int(m.group(1))
        # Only take direct text nodes — skip nested badge spans (rating, etc.)
        raw = "".join(
            child.strip() for child in link.strings
            if child.parent is link
        )
    else:
        raw = td.get_text(strip=True)

    country_code = _flag_to_country(raw)
    name = _strip_flags(raw).strip()
    return name, driver_id, country_code


def _parse_race_cell(td: Tag) -> tuple[int | None, float | None, bool]:
    """Return (race_position, race_points, is_dns) from a race column td.

    Each cell has ``show_positions`` (qual · race) and
    ``show_points`` (qual_pts · race_pts) spans.  We extract the
    *race* value (after the ``·`` separator).
    """
    dns = False
    position: int | None = None
    points: float | None = None

    pos_span = td.find("span", class_="show_positions")
    if isinstance(pos_span, Tag):
        dns = pos_span.find("small", string=re.compile(r"DNS", re.I)) is not None
        if not dns:
            position = _second_value_int(pos_span)

    pts_span = td.find("span", class_=lambda c: c and "show_points" in c)
    if isinstance(pts_span, Tag) and not dns:
        points = _second_value_float(pts_span)

    return position, points, dns


def _second_value_int(span: Tag) -> int | None:
    """Get the second number after the · separator."""
    text = span.get_text(" ", strip=True)
    parts = re.split(r"\s*·\s*", text)
    if len(parts) >= 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    # Single value (no qualifier split)
    try:
        return int(parts[0])
    except ValueError:
        return None


def _second_value_float(span: Tag) -> float | None:
    """Get the second number after the · separator."""
    text = span.get_text(" ", strip=True)
    parts = re.split(r"\s*·\s*", text)
    if len(parts) >= 2:
        try:
            return float(parts[1])
        except ValueError:
            pass
    try:
        return float(parts[0])
    except ValueError:
        return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_FLAG_RE = re.compile(r"[\U0001F1E0-\U0001F1FF]{2}")


def _flag_to_country(text: str) -> str:
    """Convert a flag emoji (e.g. regional indicators) to 2-letter ISO code."""
    m = _FLAG_RE.search(text)
    if not m:
        return ""
    return "".join(chr(ord(c) - 0x1F1E6 + ord("A")) for c in m.group())


def _strip_flags(text: str) -> str:
    """Remove flag emoji from text."""
    return _FLAG_RE.sub("", text)

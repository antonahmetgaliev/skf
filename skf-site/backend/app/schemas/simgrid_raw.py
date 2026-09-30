"""Raw SimGrid response shapes — the contract we rely on, not our API.

SimGrid's OpenAPI spec (``simgrid/openapi.yml``) types every body as a bare
``object``, so these models are hand-written from live responses. They list
only the fields we read and ignore the rest; a missing or mistyped field
raises instead of degrading into an empty page (see the 2026-09-28 switch to
wrapped collections in ``SIMGRID_API.md``).
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class RawModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Pagination(RawModel):
    limit: int | None = None
    offset: int | None = None
    total_count: int | None = None


class Envelope(RawModel, Generic[T]):
    """Every collection endpoint: ``{"data": [...], "pagination": ... | null}``."""

    data: list[T]
    pagination: Pagination | None


class RawChampionshipRef(RawModel):
    """An item of ``GET /championships`` — only id and name."""

    id: int
    name: str


class RawTrack(RawModel):
    name: str | None = None


class RawRace(RawModel):
    """An item of ``GET /races`` and of standings' ``completed_races``."""

    id: int
    race_name: str | None = None
    display_name: str | None = None
    starts_at: str | None = None
    track: RawTrack | str | None = None
    results_available: bool = False
    ended: bool = False


class RawParticipant(RawModel):
    user_id: int
    username: str
    steam64_id: str | None = None
    discord_uid: str | None = None


class RawChampionshipCarClass(RawModel):
    id: int
    display_name: str | None = None


class RawNamed(RawModel):
    """Games and car classes: we only read the name."""

    id: int
    name: str


class RawStandingCarClass(RawModel):
    display_name: str | None = None


class RawStandingParticipant(RawModel):
    country_code: str | None = None


class RawStandingEntry(RawModel):
    # ``id`` is the *registration* id — never a driver id; use ``user_id``.
    user_id: int | None = None
    position_cache: int | None = None
    display_name: str | None = None
    car: str | None = None
    car_class: str | None = Field(default=None, alias="class")
    championship_car_class: RawStandingCarClass | None = None
    participant: RawStandingParticipant | None = None
    championship_points: float | None = None
    championship_penalties: float | None = None
    championship_score: float | None = None


class RawStandingsPage(Envelope[RawStandingEntry]):
    """``GET /championships/{id}/standings``: entries plus the counted races."""

    completed_races: list[RawRace] = []


class RawRfactorResult(RawModel):
    """LMU (rFactor) extras; iRacing results carry none of this."""

    status: str | None = None  # "Finished Normally", "DNF", "DQ"
    finished: str | None = None  # overall finishing position
    starting: str | None = None  # overall grid position
    class_st: str | None = None  # grid position in class
    class_fn: str | None = None  # finishing position in class


class RawResultExternalData(RawModel):
    rfactor: RawRfactorResult | None = None


class RawSessionEntrant(RawModel):
    user_id: int | None = None
    championship_car_class: RawStandingCarClass | None = None


class RawSessionResult(RawModel):
    """An item of ``GET /races/{id}/session_results?result_type=results``.

    Times are milliseconds. ``dnf`` is never set by SimGrid (not even for
    LMU retirements), so only ``external_data.rfactor.status`` tells DNF/DQ.
    """

    session_type: str
    position_cache: int | None = None
    lap_count: int | None = None
    best_lap: int | None = None
    total_time: int | None = None
    points_total: float | None = None
    dns: bool = False
    dnf: bool = False
    total_time_penalty: float | None = None
    championship_car_class_id: int | None = None
    sessionable_name: str | None = None
    imported_name: str | None = None
    sessionable: RawSessionEntrant | None = None
    car_name: str | None = None
    car_number: int | None = None
    grid_rating_change: int | None = None
    external_data: RawResultExternalData | None = None


class RawSessionResultsPage(RawModel):
    """``data`` is ``null`` until results are published (or without ``result_type``)."""

    data: list[RawSessionResult] | None
    pagination: Pagination | None = None


def collection(model: type[T], payload: Any) -> Envelope[T]:
    """Validate a collection payload, raising on any other shape."""
    return Envelope[model].model_validate(payload)  # type: ignore[valid-type]

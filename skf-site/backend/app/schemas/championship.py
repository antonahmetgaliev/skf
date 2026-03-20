from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model that serialises field names as camelCase."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    def model_dump(self, **kwargs):  # type: ignore[override]
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class ChampionshipListItem(CamelModel):
    id: int
    name: str
    start_date: str | None = None
    end_date: str | None = None
    accepting_registrations: bool = False
    event_completed: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalise_date_aliases(cls, data: Any) -> Any:
        """Map alternative SimGrid date field names into our canonical names."""
        if not isinstance(data, dict):
            return data
        if not data.get("start_date") and not data.get("startDate"):
            for alt in ("starts_at", "startsAt", "start_at", "startAt"):
                if data.get(alt):
                    data["start_date"] = data[alt]
                    break
        if not data.get("end_date") and not data.get("endDate"):
            for alt in ("ends_at", "endsAt", "end_at", "endAt"):
                if data.get(alt):
                    data["end_date"] = data[alt]
                    break
        if not data.get("event_completed") and not data.get("eventCompleted"):
            for alt in ("completed", "is_completed", "isCompleted", "ended", "is_ended", "isEnded"):
                if data.get(alt):
                    data["event_completed"] = True
                    break
        return data


class ChampionshipDetails(CamelModel):
    id: int
    name: str
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    capacity: int | None = None
    spots_taken: int | None = None
    accepting_registrations: bool = False
    host_name: str = ""
    game_name: str = ""
    url: str = ""


class DriverRaceResult(CamelModel):
    race_id: int | None = None
    race_index: int
    points: float | None = None
    position: int | None = None
    dns: bool = False


class StandingEntry(CamelModel):
    id: int
    position: int | None = None
    display_name: str
    country_code: str = ""
    car: str = ""
    car_class: str = ""
    points: float = 0
    penalties: float = 0
    score: float = 0
    dsq: bool = False
    race_results: list[DriverRaceResult] = []


class StandingRace(CamelModel):
    id: int
    display_name: str
    starts_at: str | None = None
    results_available: bool = False
    ended: bool = False


class ChampionshipStandingsData(CamelModel):
    entries: list[StandingEntry] = []
    races: list[StandingRace] = []
    stale: bool = False


class DriverChampionshipResult(CamelModel):
    championship_id: int
    championship_name: str
    position: int | None = None
    score: float = 0
    dsq: bool = False
    start_date: str | None = None
    end_date: str | None = None
    accepting_registrations: bool = False


class PodiumEntry(CamelModel):
    simgrid_driver_id: int | None = None
    display_name: str
    position: int  # 1, 2, or 3


class ChampionshipPodium(CamelModel):
    championship_id: int
    championship_name: str
    podium: list[PodiumEntry] = []

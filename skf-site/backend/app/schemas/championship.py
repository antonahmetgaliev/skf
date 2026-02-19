from __future__ import annotations

from pydantic import BaseModel, ConfigDict
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


class ChampionshipDetails(CamelModel):
    id: int
    name: str
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


class StandingEntry(CamelModel):
    id: int
    position: int | None = None
    display_name: str
    country_code: str = ""
    car: str = ""
    points: float = 0
    penalties: float = 0
    score: float = 0
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

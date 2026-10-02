from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, model_validator

from app.schemas.base import BlankAsNone, CamelModel, IsoDateTime, Url
from app.schemas.enums import RaceSessionKind, RaceStatus


class ChampionshipSummaryOut(CamelModel):
    id: int
    name: str
    start_date: IsoDateTime | None = None
    end_date: IsoDateTime | None = None
    accepting_registrations: bool = False
    event_completed: bool = Field(default=False, description="SimGrid marks the championship as finished.")
    is_active: bool = Field(default=False, description="Shown on the site; inactive ones are admin-only.")

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


class ChampionshipUpdate(CamelModel):
    is_active: bool


class ChampionshipOut(CamelModel):
    id: int
    name: str
    description: str | None = None
    image: str | None = None
    start_date: IsoDateTime | None = None
    end_date: IsoDateTime | None = None
    capacity: int | None = None
    spots_taken: int | None = None
    accepting_registrations: bool = False
    host_name: Annotated[str | None, BlankAsNone] = None
    game_name: str = ""
    url: Annotated[Url | None, BlankAsNone] = None
    results_url: Annotated[Url | None, BlankAsNone] = None
    discord_url: Annotated[str | None, BlankAsNone] = None
    round_number: int | None = None
    all_rounds_number: int | None = None


class DriverRaceResultOut(CamelModel):
    """One round of a driver's standings row (class position)."""

    race_id: int
    race_index: int
    points: float | None = None
    position: int | None = None
    status: RaceStatus = RaceStatus.CLASSIFIED


class RaceResultEntryOut(CamelModel):
    user_id: int | None = None
    display_name: str
    car: str = ""
    car_number: int | None = None
    car_class: str = ""
    position: int | None = None
    class_position: int | None = None
    start_position: int | None = None
    laps: int | None = None
    best_lap_ms: int | None = None
    is_class_best_lap: bool = False
    total_time_ms: int | None = None
    gap_ms: int | None = None
    laps_down: int = 0
    penalty_s: float = 0
    points: float | None = None
    status: RaceStatus = RaceStatus.CLASSIFIED
    rating_change: int | None = None


class RaceSessionOut(CamelModel):
    race_id: int
    session: RaceSessionKind
    entries: list[RaceResultEntryOut] = []


class StandingEntryOut(CamelModel):
    # Never fall back to the registration id, which is a different id space.
    id: int | None = Field(default=None, description="SimGrid user id; `null` when SimGrid gives none.")
    position: int | None = None
    display_name: str
    country_code: Annotated[str | None, BlankAsNone] = None
    car: str = ""
    car_class: str = ""
    points: float = 0
    penalties: float = 0
    score: float = 0
    race_results: list[DriverRaceResultOut] = []


class StandingRaceOut(CamelModel):
    id: int
    display_name: str
    starts_at: IsoDateTime | None = None
    results_available: bool = False
    ended: bool = False


class ChampionshipRaceOut(CamelModel):
    id: int
    display_name: str = ""
    starts_at: IsoDateTime | None = None
    track: str | None = None
    results_available: bool = False
    ended: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalise_race_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # display_name aliases
        if not data.get("display_name") and not data.get("displayName"):
            for alt in ("race_name", "raceName", "name"):
                if data.get(alt):
                    data["display_name"] = data[alt]
                    break
        # starts_at aliases
        if not data.get("starts_at") and not data.get("startsAt"):
            for alt in ("start_date", "startDate", "start_at", "startAt"):
                if data.get(alt):
                    data["starts_at"] = data[alt]
                    break
        # track: can be dict with "name" key or a plain string
        track_raw = data.get("track")
        if isinstance(track_raw, dict):
            data["track"] = track_raw.get("name")
        return data


class ChampionshipStandingsOut(CamelModel):
    entries: list[StandingEntryOut] = []
    races: list[StandingRaceOut] = []


class ParticipatingUser(CamelModel):
    user_id: int
    username: str
    steam64_id: str | None = None
    discord_uid: str | None = None

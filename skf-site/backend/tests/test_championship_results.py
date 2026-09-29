"""Per-race results from SimGrid ``session_results``: mapping and endpoints.

Fixtures are real SKF sessions, anonymised: LMU Hyper 70 round 1 (race and
qualifying, two classes) and an iRacing Challenger League race.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.schemas.simgrid_raw import RawSessionResult, RawSessionResultsPage
from app.services.championship_results import map_session
from tests.conftest import LMU_CHAMPIONSHIP_ID

FIXTURES = Path(__file__).parent / "fixtures" / "simgrid"
LMU_RACE_ID = 256741


def _payload(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _raw(name: str) -> list[RawSessionResult]:
    return RawSessionResultsPage.model_validate(_payload(name)).data or []


def _by_class(entries, car_class):
    return [e for e in entries if e.car_class == car_class]


# ── Contract ───────────────────────────────────────────────────────────────


def test_unpublished_results_are_an_empty_page():
    page = RawSessionResultsPage.model_validate({"data": None, "pagination": None, "session_laps": None})
    assert page.data is None


# ── Mapping ────────────────────────────────────────────────────────────────


def test_lmu_race_is_grouped_by_class_in_class_order():
    entries = map_session(_raw("session_results_lmu_race"))
    assert [e.car_class for e in entries] == sorted(e.car_class for e in entries)
    for cls in ("Hypercar", "LMGT3"):
        positions = [e.class_position for e in _by_class(entries, cls)]
        assert positions == list(range(1, len(positions) + 1))


def test_lmu_statuses_come_from_rfactor():
    statuses = Counter((e.car_class, e.status) for e in map_session(_raw("session_results_lmu_race")))
    assert statuses[("LMGT3", "dq")] == 2
    assert statuses[("LMGT3", "dnf")] == 4
    assert statuses[("Hypercar", "dnf")] == 2
    assert statuses[("LMGT3", "dns")] + statuses[("Hypercar", "dns")] == 5


def test_lmu_gaps_laps_down_and_grid():
    hyper = _by_class(map_session(_raw("session_results_lmu_race")), "Hypercar")
    leader, second = hyper[0], hyper[1]
    assert (leader.position, leader.start_position, leader.gap_ms) == (1, 4, None)
    assert second.gap_ms == second.total_time_ms - leader.total_time_ms > 0
    one_lap_down = next(e for e in hyper if e.laps == leader.laps - 1)
    assert (one_lap_down.laps_down, one_lap_down.gap_ms) == (1, None)
    assert all(e.laps_down == 0 and e.gap_ms is None for e in hyper if e.status == "dns")


def test_best_lap_is_flagged_once_per_class():
    entries = map_session(_raw("session_results_lmu_race"))
    for cls in ("Hypercar", "LMGT3"):
        group = _by_class(entries, cls)
        flagged = [e for e in group if e.is_class_best_lap]
        assert len(flagged) == 1
        assert flagged[0].best_lap_ms == min(e.best_lap_ms for e in group if e.best_lap_ms)


def test_iracing_has_no_retirement_status_or_grid():
    entries = map_session(_raw("session_results_iracing_race"))
    assert {e.status for e in entries} == {"classified", "dns"}
    assert all(e.position is None and e.start_position is None for e in entries)
    assert all(e.user_id and e.display_name for e in entries)


def test_qualifying_is_ranked_by_best_lap():
    """SimGrid puts an LMGT3 driver without a timed lap on pole; we don't."""
    raw = _raw("session_results_lmu_qualifying")
    assert any(r.position_cache == 1 and not r.best_lap for r in raw)

    entries = map_session(raw, "qualifying")
    for cls in {e.car_class for e in entries}:
        group = _by_class(entries, cls)
        assert [e.class_position for e in group] == list(range(1, len(group) + 1))
        timed = [e.best_lap_ms for e in group if e.best_lap_ms]
        assert timed == sorted(timed)
        assert group[0].is_class_best_lap
        assert all(e.best_lap_ms is None for e in group[len(timed):])


# ── Endpoints ──────────────────────────────────────────────────────────────


def _stub_lmu_round(simgrid_stub) -> None:
    simgrid_stub.races[LMU_CHAMPIONSHIP_ID] = [{"id": LMU_RACE_ID, "race_name": "Round 1"}]
    for session in ("race_1", "qualifying"):
        name = "race" if session == "race_1" else "qualifying"
        simgrid_stub.results[(LMU_RACE_ID, session)] = _payload(f"session_results_lmu_{name}")["data"]


async def test_race_results_endpoint(client, simgrid_stub):
    _stub_lmu_round(simgrid_stub)
    base = f"/api/v1/championships/{LMU_CHAMPIONSHIP_ID}/races/{LMU_RACE_ID}/results"

    race = (await client.get(base)).json()
    assert race["session"] == "race" and len(race["entries"]) == 31
    assert {"classPosition", "bestLapMs", "gapMs", "lapsDown", "penaltyS", "status"} <= race["entries"][0].keys()

    quali = (await client.get(base, params={"session": "qualifying"})).json()
    assert quali["session"] == "qualifying" and len(quali["entries"]) == 26

    assert (await client.get(base, params={"session": "race_2"})).status_code == 422


async def test_race_of_another_championship_is_404(client, simgrid_stub):
    _stub_lmu_round(simgrid_stub)
    resp = await client.get(f"/api/v1/championships/{LMU_CHAMPIONSHIP_ID}/races/999/results")
    assert resp.status_code == 404


async def test_standings_carry_round_results(client, simgrid_stub, monkeypatch):
    from app.schemas.championship import ChampionshipStandingsData, StandingEntry, StandingRace
    from app.services import simgrid as sg_mod

    _stub_lmu_round(simgrid_stub)
    raw = simgrid_stub.results[(LMU_RACE_ID, "race_1")]
    winner = next(r for r in raw if r["position_cache"] == 1 and not r["dns"])
    dns = next(r for r in raw if r["dns"])

    async def get_standings(championship_id):
        return ChampionshipStandingsData(
            entries=[
                StandingEntry(id=winner["sessionable"]["user_id"], display_name="Winner"),
                StandingEntry(id=dns["sessionable"]["user_id"], display_name="Absent"),
                StandingEntry(id=None, display_name="Unlinked"),
            ],
            races=[
                StandingRace(id=LMU_RACE_ID, display_name="Round 1", results_available=True),
                StandingRace(id=1, display_name="Round 2", results_available=False),
            ],
        ), False

    monkeypatch.setattr(sg_mod.simgrid_service, "get_standings", get_standings)
    resp = await client.get(f"/api/v1/championships/{LMU_CHAMPIONSHIP_ID}/standings")
    assert resp.status_code == 200
    rows = {e["displayName"]: e["raceResults"] for e in resp.json()["entries"]}
    assert rows["Winner"] == [{
        "raceId": LMU_RACE_ID, "raceIndex": 0, "points": winner["points_total"],
        "position": 1, "status": "classified",
    }]
    assert rows["Absent"][0]["status"] == "dns"
    assert rows["Unlinked"] == []


async def test_standings_survive_a_failing_round(client, simgrid_stub, monkeypatch):
    from app.schemas.championship import ChampionshipStandingsData, StandingEntry, StandingRace
    from app.services import simgrid as sg_mod

    async def get_standings(championship_id):
        return ChampionshipStandingsData(
            entries=[StandingEntry(id=5, display_name="Driver")],
            races=[StandingRace(id=LMU_RACE_ID, display_name="Round 1", results_available=True)],
        ), False

    async def failing(*_args):
        raise RuntimeError("SimGrid is down")

    monkeypatch.setattr(sg_mod.simgrid_service, "get_standings", get_standings)
    monkeypatch.setattr(sg_mod.simgrid_service, "get_session_results", failing)
    resp = await client.get(f"/api/v1/championships/{LMU_CHAMPIONSHIP_ID}/standings")
    assert resp.status_code == 200
    assert resp.json()["entries"][0]["raceResults"] == []

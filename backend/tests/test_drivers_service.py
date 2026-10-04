"""Drivers come from SimGrid, keyed on its user id; accounts are linked through Discord."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bwp import BwpPoint, Driver, PenaltyClearance, PenaltyRule
from app.models.incidents import Incident, IncidentDriver, IncidentWindow
from app.models.race_result import GiveawayNameAlias, RaceResultEntry, RaceResultImport
from app.models.user import User
from app.schemas.championship import ParticipatingUser, StandingEntryOut
from app.schemas.enums import DriverLinkStatus
from app.services import drivers as service
from tests.roles import act_as, link_driver, make_user
from tests.test_users_router import admin_client  # noqa: F401

CHAMPIONSHIP_ID = 700


def _entry(**kwargs) -> StandingEntryOut:
    defaults = {"id": 1, "position": 1, "display_name": "Driver One", "country_code": "GB"}
    return StandingEntryOut(**{**defaults, **kwargs})


async def _driver(db: AsyncSession, name: str, age_days: int = 0, **fields) -> Driver:
    driver = Driver(name=name, created_at=datetime.now(UTC) - timedelta(days=age_days), **fields)
    db.add(driver)
    await db.commit()
    return driver


async def _all_drivers(db: AsyncSession) -> list[Driver]:
    db.expire_all()
    return list((await db.execute(select(Driver).order_by(Driver.name))).scalars())


@pytest.fixture
def simgrid(monkeypatch):
    """SimGrid's view of people: participants per championship and Discord lookups."""
    from app.services import simgrid as simgrid_module

    class Stub:
        participants: list[ParticipatingUser] = []
        simgrid_id_by_discord: dict[str, int] = {}

    async def get_participating_users(_self, _championship_id):
        return Stub.participants

    async def get_user_by_discord_id(_self, discord_uid):
        return Stub.simgrid_id_by_discord.get(discord_uid)

    cls = type(simgrid_module.simgrid_service)
    monkeypatch.setattr(cls, "get_participating_users", get_participating_users)
    monkeypatch.setattr(cls, "get_user_by_discord_id", get_user_by_discord_id)
    return Stub


# ---------------------------------------------------------------------------
# Drivers from standings
# ---------------------------------------------------------------------------


async def test_new_simgrid_user_becomes_a_driver(db: AsyncSession):
    created = await service.upsert_from_standings(db, [_entry(id=7, display_name=" New Racer ")])
    await db.commit()

    (driver,) = await _all_drivers(db)
    assert created == 1
    assert (driver.name, driver.simgrid_driver_id, driver.simgrid_display_name) == (
        "New Racer",
        7,
        "New Racer",
    )
    assert driver.country_code == "GB" and driver.synced_at is not None


async def test_known_simgrid_user_is_refreshed_not_renamed(db: AsyncSession):
    await _driver(db, "Hub Name", simgrid_driver_id=7, country_code="UA")

    created = await service.upsert_from_standings(
        db, [_entry(id=7, display_name="SimGrid Name", country_code=None)]
    )
    await db.commit()

    (driver,) = await _all_drivers(db)
    assert created == 0
    assert (driver.name, driver.simgrid_display_name, driver.country_code) == (
        "Hub Name",
        "SimGrid Name",
        "UA",
    )


async def test_a_name_never_identifies_a_driver(db: AsyncSession):
    """A row without a SimGrid id is not handed to a namesake; it is left for an admin to merge."""
    manual = await _driver(db, "John Smith")

    await service.upsert_from_standings(db, [_entry(id=7, display_name="john smith")])
    await db.commit()

    drivers = await _all_drivers(db)
    assert len(drivers) == 2
    await db.refresh(manual)
    assert manual.simgrid_driver_id is None


async def test_namesakes_are_two_drivers(db: AsyncSession):
    await service.upsert_from_standings(
        db, [_entry(id=7, display_name="Ivan Petrenko"), _entry(id=8, display_name="Ivan Petrenko")]
    )
    await db.commit()

    assert sorted(d.simgrid_driver_id for d in await _all_drivers(db)) == [7, 8]


async def test_entries_that_identify_nobody_are_skipped(db: AsyncSession):
    await service.upsert_from_standings(
        db,
        [_entry(id=None, display_name="No Id"), _entry(id=0, display_name="Zero"), _entry(display_name="  ")],
    )
    await db.commit()

    assert await _all_drivers(db) == []


async def test_participants_bring_discord_and_steam_ids(db: AsyncSession):
    await _driver(db, "Known", simgrid_driver_id=7, discord_uid="old")
    await _driver(db, "Gone Quiet", simgrid_driver_id=8, discord_uid="was-connected")

    await service.apply_participants(
        db,
        [
            ParticipatingUser(user_id=7, username="known", discord_uid="d7", steam64_id="s7"),
            ParticipatingUser(user_id=8, username="quiet"),
            ParticipatingUser(user_id=9, username="not ours"),
        ],
    )
    await db.commit()

    known, quiet = sorted(await _all_drivers(db), key=lambda d: d.simgrid_driver_id)
    assert (known.discord_uid, known.steam64_id) == ("d7", "s7")
    assert quiet.discord_uid is None


# ---------------------------------------------------------------------------
# Account ↔ driver
# ---------------------------------------------------------------------------


async def test_sync_links_accounts_by_discord_id(db: AsyncSession, simgrid, test_user):
    simgrid.participants = [
        ParticipatingUser(user_id=7, username="me", discord_uid=test_user.discord_id),
    ]

    created, linked = await service.sync_championship(db, CHAMPIONSHIP_ID, [_entry(id=7)])

    assert (created, linked) == (1, 1)
    user = await db.get(User, test_user.id, populate_existing=True)
    (driver,) = await _all_drivers(db)
    assert (user.driver_id, user.driver_link_source) == (driver.id, "simgrid")
    # Running it again changes nothing.
    assert await service.sync_championship(db, CHAMPIONSHIP_ID, [_entry(id=7)]) == (0, 0)


async def test_sync_leaves_an_admins_decision_alone(db: AsyncSession, simgrid, test_user):
    mine = await _driver(db, "Mine By Hand", simgrid_driver_id=1)
    other_user = await make_user(db, "driver")
    await service.set_user_driver(db, await db.get(User, test_user.id), mine.id)
    service.clear_user_driver(await db.get(User, other_user.id))
    await db.commit()
    simgrid.participants = [
        ParticipatingUser(user_id=7, username="a", discord_uid=test_user.discord_id),
        ParticipatingUser(user_id=8, username="b", discord_uid=other_user.discord_id),
    ]

    _, linked = await service.sync_championship(db, CHAMPIONSHIP_ID, [_entry(id=7), _entry(id=8)])

    assert linked == 0
    assert (await db.get(User, test_user.id, populate_existing=True)).driver_id == mine.id
    assert (await db.get(User, other_user.id, populate_existing=True)).driver_id is None


async def test_one_driver_is_linked_to_one_account(db: AsyncSession, simgrid, test_user):
    """Two accounts cannot share a driver, whatever SimGrid says."""
    driver = await _driver(db, "Shared", simgrid_driver_id=7, discord_uid=test_user.discord_id)
    holder = await make_user(db, "driver")
    await link_driver(db, holder, driver)

    assert await service.link_accounts(db) == 0


@pytest.mark.parametrize(
    ("simgrid_id", "driver_exists", "taken", "expected"),
    [
        (None, True, False, DriverLinkStatus.NO_SIMGRID_ACCOUNT),
        (7, False, False, DriverLinkStatus.DRIVER_NOT_SYNCED),
        (7, True, True, DriverLinkStatus.DRIVER_TAKEN),
        (7, True, False, DriverLinkStatus.LINKED),
    ],
)
async def test_link_user_says_why(db, simgrid, test_user, simgrid_id, driver_exists, taken, expected):
    if simgrid_id:
        simgrid.simgrid_id_by_discord = {test_user.discord_id: simgrid_id}
    if driver_exists:
        driver = await _driver(db, "Me", simgrid_driver_id=7)
        if taken:
            await link_driver(db, await make_user(db, "driver"), driver)

    user = await db.get(User, test_user.id)
    assert await service.link_user(db, user) is expected
    assert (user.driver_id is not None) == (expected is DriverLinkStatus.LINKED)


async def test_link_user_respects_an_admins_unlink(db: AsyncSession, simgrid, test_user):
    await _driver(db, "Me", simgrid_driver_id=7)
    simgrid.simgrid_id_by_discord = {test_user.discord_id: 7}
    user = await db.get(User, test_user.id)
    service.clear_user_driver(user)
    await db.commit()

    assert await service.link_user(db, user) is DriverLinkStatus.UNLINKED_BY_ADMIN
    assert user.driver_id is None


async def test_login_links_in_the_background(engine, db, simgrid, test_user, monkeypatch):
    import app.database as db_module
    from tests.conftest import _factory

    monkeypatch.setattr(db_module, "async_session", _factory(engine))
    driver = await _driver(db, "Me", simgrid_driver_id=7)
    simgrid.simgrid_id_by_discord = {test_user.discord_id: 7}

    await service.link_driver_for_user(test_user.id)

    assert (await db.get(User, test_user.id, populate_existing=True)).driver_id == driver.id


async def test_my_driver_link_endpoint(auth_client: AsyncClient, db: AsyncSession, simgrid):
    resp = await auth_client.post("/api/v1/me/driver-links")
    assert resp.status_code == 200
    assert resp.json() == {"status": "no_simgrid_account", "driverId": None}


async def test_admin_links_and_unlinks_by_hand(admin_client: AsyncClient, db: AsyncSession):  # noqa: F811
    user, other = await make_user(db, "driver"), await make_user(db, "driver")
    driver = await _driver(db, "No Discord On SimGrid", simgrid_driver_id=7)
    url = f"/api/v1/users/{user.id}/driver"

    resp = await admin_client.put(url, json={"driverId": str(driver.id)})
    assert resp.status_code == 200
    assert (resp.json()["driverId"], resp.json()["driverLinkSource"]) == (str(driver.id), "admin")

    taken = await admin_client.put(f"/api/v1/users/{other.id}/driver", json={"driverId": str(driver.id)})
    assert taken.status_code == 409
    assert user.username in taken.json()["detail"]

    assert (await admin_client.delete(url)).status_code == 204
    stored = await db.get(User, user.id, populate_existing=True)
    assert (stored.driver_id, stored.driver_link_source) == (None, "admin")


async def test_linking_by_hand_is_admin_only(admin_client: AsyncClient, db: AsyncSession):  # noqa: F811
    user = await make_user(db, "driver")
    driver = await _driver(db, "D", simgrid_driver_id=7)
    act_as(await make_user(db, "racing_judge"))

    resp = await admin_client.put(f"/api/v1/users/{user.id}/driver", json={"driverId": str(driver.id)})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Cleaning up
# ---------------------------------------------------------------------------


async def test_issues_list_rows_that_are_not_one_simgrid_users_only_row(
    admin_client: AsyncClient,  # noqa: F811
    db: AsyncSession,
):
    await _driver(db, "Fine", simgrid_driver_id=1)
    keeper = await _driver(db, "Twice", age_days=2, simgrid_driver_id=2)
    copy = await _driver(db, "Twice Again", age_days=1, simgrid_driver_id=2)
    orphan = await _driver(db, "john smith")
    lookalike = await _driver(db, "John Smith", simgrid_driver_id=3)
    lone = await _driver(db, "Nobody Knows")

    resp = await admin_client.get("/api/v1/driver-issues")

    assert resp.status_code == 200
    issues = {i["driver"]["id"]: i for i in resp.json()}
    assert set(issues) == {str(d.id) for d in (keeper, copy, orphan, lone)}
    assert issues[str(keeper.id)]["kind"] == "duplicate_simgrid_id"
    assert issues[str(keeper.id)]["suggestedTarget"] is None
    assert issues[str(copy.id)]["suggestedTarget"]["id"] == str(keeper.id)
    assert issues[str(orphan.id)]["kind"] == "no_simgrid_id"
    assert issues[str(orphan.id)]["suggestedTarget"]["id"] == str(lookalike.id)
    assert issues[str(lone.id)]["suggestedTarget"] is None


async def test_merge_moves_everything_and_deletes_the_source(
    admin_client: AsyncClient,  # noqa: F811
    db: AsyncSession,
):
    target = await _driver(db, "John Smith", simgrid_driver_id=7)
    source = await _driver(db, "john smith", photo_url="https://example.com/p.png", discord_uid="d7")
    user = await make_user(db, "driver")
    await link_driver(db, user, source)

    today = datetime.now(UTC).date()
    rule_both, rule_source = PenaltyRule(threshold=3), PenaltyRule(threshold=6)
    window = IncidentWindow(race_name="R1", closes_at=datetime.now(UTC) + timedelta(days=1))
    db.add_all([rule_both, rule_source, window])
    await db.flush()
    incident = Incident(window_id=window.id)
    race_import = RaceResultImport(championship_simgrid_id=1)
    db.add_all([incident, race_import])
    await db.flush()
    db.add_all(
        [
            BwpPoint(driver_id=source.id, points=2, issued_on=today, expires_on=today + timedelta(days=30)),
            BwpPoint(driver_id=target.id, points=1, issued_on=today, expires_on=today + timedelta(days=30)),
            PenaltyClearance(driver_id=source.id, penalty_rule_id=rule_both.id),
            PenaltyClearance(driver_id=target.id, penalty_rule_id=rule_both.id),
            PenaltyClearance(driver_id=source.id, penalty_rule_id=rule_source.id),
            IncidentDriver(incident_id=incident.id, driver_name="john smith", driver_id=source.id),
            RaceResultEntry(
                import_id=race_import.id,
                raw_name="john smith",
                normalized_name="john smith",
                driver_id=source.id,
            ),
            GiveawayNameAlias(
                normalized_alias="j smith",
                canonical_normalized_name="john smith",
                canonical_display_name="John Smith",
                driver_id=source.id,
            ),
        ]
    )
    await db.commit()

    resp = await admin_client.post(
        f"/api/v1/drivers/{target.id}/merges", json={"sourceDriverId": str(source.id)}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["activeBwp"] == 3
    assert body["userId"] == str(user.id)
    assert body["photoUrl"] == "https://example.com/p.png"
    assert sorted(c["penaltyRuleId"] for c in body["clearances"]) == sorted(
        [str(rule_both.id), str(rule_source.id)]
    )

    db.expire_all()
    assert [d.id for d in await _all_drivers(db)] == [target.id]
    assert (await db.get(Driver, target.id)).discord_uid == "d7"
    for model in (IncidentDriver, RaceResultEntry, GiveawayNameAlias):
        assert (await db.execute(select(model.driver_id))).scalars().all() == [target.id]


async def test_merge_refuses_two_different_people(admin_client: AsyncClient, db: AsyncSession):  # noqa: F811
    one = await _driver(db, "One", simgrid_driver_id=1)
    two = await _driver(db, "Two", simgrid_driver_id=2)
    url = f"/api/v1/drivers/{one.id}/merges"

    assert (await admin_client.post(url, json={"sourceDriverId": str(two.id)})).status_code == 409
    assert (await admin_client.post(url, json={"sourceDriverId": str(one.id)})).status_code == 422

    same_a = await _driver(db, "A", simgrid_driver_id=1)
    await link_driver(db, await make_user(db, "driver"), one)
    await link_driver(db, await make_user(db, "driver"), same_a)
    resp = await admin_client.post(url, json={"sourceDriverId": str(same_a.id)})
    assert resp.status_code == 409
    assert "Unlink" in resp.json()["detail"]


async def test_admin_sync_reads_every_active_championship(
    admin_client: AsyncClient,  # noqa: F811
    db: AsyncSession,
    simgrid,
    monkeypatch,
):
    from app.models.active_championship import ActiveChampionship
    from app.schemas.championship import ChampionshipStandingsOut
    from app.services import championships as championships_service

    db.add_all([ActiveChampionship(simgrid_id=1), ActiveChampionship(simgrid_id=2)])
    await db.commit()

    async def get_standings(championship_id):
        if championship_id == 2:
            raise RuntimeError("SimGrid is down")
        return ChampionshipStandingsOut(entries=[_entry(id=7), _entry(id=8, display_name="Two")]), True

    monkeypatch.setattr(championships_service, "get_standings", get_standings)

    resp = await admin_client.post("/api/v1/driver-syncs")

    assert resp.status_code == 200
    assert resp.json() == {"championships": 1, "failed": 1, "created": 2, "linked": 0}

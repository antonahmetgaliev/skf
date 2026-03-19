"""Tests for /api/dotd/* endpoints (Driver of the Day voting)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_BASE = "/api/dotd"


def _now():
    return datetime.now(timezone.utc)


def _future(hours: float = 2.0):
    return _now() + timedelta(hours=hours)


def _past(hours: float = 1.0):
    return _now() - timedelta(hours=hours)


# ── shared poll payload ──────────────────────────────────────────────────────

def _poll_payload(**overrides):
    base = {
        "championshipId": 1,
        "championshipName": "Test Championship",
        "raceId": 42,
        "raceName": "Race 1",
        "closesAt": _future().isoformat(),
        "candidates": [
            {"driverName": "Alice", "championshipPosition": 1},
            {"driverName": "Bob",   "championshipPosition": 2},
        ],
    }
    base.update(overrides)
    return base


# ── helper: create a poll directly in db ────────────────────────────────────

async def _create_poll_in_db(db: AsyncSession, user_id: uuid.UUID) -> tuple:
    """Insert a DotdPoll with two candidates; return (poll_id, [candidate_id, ...])."""
    from app.models.dotd import DotdCandidate, DotdPoll

    poll = DotdPoll(
        championship_id=1,
        championship_name="Test Championship",
        race_id=42,
        race_name="Race 1",
        closes_at=_future(),
        created_by_user_id=user_id,
    )
    db.add(poll)
    await db.flush()

    c1 = DotdCandidate(poll_id=poll.id, driver_name="Alice", championship_position=1)
    c2 = DotdCandidate(poll_id=poll.id, driver_name="Bob",   championship_position=2)
    db.add_all([c1, c2])
    await db.commit()

    return poll.id, [c1.id, c2.id]


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def admin_user(db: AsyncSession, seed_roles):
    """Persisted User with role 'admin'."""
    from app.models.user import Role, User
    from sqlalchemy.orm import joinedload

    result = await db.execute(sa_select(Role).where(Role.name == "admin"))
    admin_role = result.scalar_one_or_none()
    if admin_role is None:
        admin_role = Role(id=3, name="admin")
        db.add(admin_role)
        await db.commit()

    u = User(
        id=uuid.uuid4(),
        discord_id="admin_999",
        username="admin_tester",
        display_name="Admin Tester",
        role_id=admin_role.id,
        created_at=_now(),
    )
    db.add(u)
    await db.commit()

    from app.models.user import User as U
    result2 = await db.execute(sa_select(U).options(joinedload(U.role)).where(U.id == u.id))
    return result2.scalar_one()


@pytest_asyncio.fixture
async def admin_client(engine, admin_user):
    """AsyncClient where every request is authenticated as admin."""
    import app.database as db_module
    from app.auth import get_current_user, get_current_user_optional
    from app.database import get_db
    from app.main import app

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    original = db_module.async_session
    db_module.async_session = factory

    async def _override_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_current_user_optional] = lambda: admin_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_user_optional, None)
    db_module.async_session = original


@pytest_asyncio.fixture
async def driver_client(engine, test_user):
    """AsyncClient where every request is authenticated as the driver test_user."""
    import app.database as db_module
    from app.auth import get_current_user, get_current_user_optional
    from app.database import get_db
    from app.main import app

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    original = db_module.async_session
    db_module.async_session = factory

    async def _override_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_current_user_optional] = lambda: test_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_user_optional, None)
    db_module.async_session = original


# ── tests ─────────────────────────────────────────────────────────────────────

async def test_create_poll_as_admin(admin_client: AsyncClient):
    resp = await admin_client.post(f"{_BASE}/polls", json=_poll_payload())
    assert resp.status_code == 201
    data = resp.json()
    assert data["raceName"] == "Race 1"
    assert data["isOpen"] is True
    assert len(data["candidates"]) == 2
    assert data["hasVoted"] is False
    assert data["totalVotes"] == 0


async def test_create_poll_as_driver_forbidden(driver_client: AsyncClient):
    resp = await driver_client.post(f"{_BASE}/polls", json=_poll_payload())
    assert resp.status_code == 403


async def test_vote_hides_counts_before_vote(driver_client: AsyncClient, db: AsyncSession, test_user):
    """Logged-in driver sees None vote_count before voting."""
    poll_id, _ = await _create_poll_in_db(db, test_user.id)

    resp = await driver_client.get(f"{_BASE}/polls")
    assert resp.status_code == 200
    poll = next(p for p in resp.json() if p["id"] == str(poll_id))
    for c in poll["candidates"]:
        assert c["voteCount"] is None


async def test_vote_shows_counts_after_vote(driver_client: AsyncClient, db: AsyncSession, test_user):
    """After voting, the user sees vote counts and has_voted=True."""
    poll_id, candidate_ids = await _create_poll_in_db(db, test_user.id)
    candidate_id = str(candidate_ids[0])

    resp = await driver_client.post(
        f"{_BASE}/polls/{poll_id}/vote",
        params={"candidate_id": candidate_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["hasVoted"] is True
    assert data["myVoteCandidateId"] == candidate_id
    for c in data["candidates"]:
        assert c["voteCount"] is not None


async def test_admin_always_sees_counts(admin_client: AsyncClient, db: AsyncSession, admin_user):
    """Admin sees vote counts even without voting."""
    poll_id, _ = await _create_poll_in_db(db, admin_user.id)

    resp = await admin_client.get(f"{_BASE}/polls")
    assert resp.status_code == 200
    poll = next(p for p in resp.json() if p["id"] == str(poll_id))
    for c in poll["candidates"]:
        assert c["voteCount"] is not None


async def test_anon_sees_no_counts_while_open(client: AsyncClient, db: AsyncSession, seed_roles):
    """Anonymous user sees None vote_count while poll is open."""
    poll_id, _ = await _create_poll_in_db(db, uuid.uuid4())

    resp = await client.get(f"{_BASE}/polls")
    assert resp.status_code == 200
    poll = next(p for p in resp.json() if p["id"] == str(poll_id))
    for c in poll["candidates"]:
        assert c["voteCount"] is None


async def test_anon_sees_counts_when_closed(client: AsyncClient, admin_client: AsyncClient, db: AsyncSession, admin_user):
    """Anonymous user sees counts after poll is manually closed."""
    poll_id, _ = await _create_poll_in_db(db, admin_user.id)

    close_resp = await admin_client.patch(f"{_BASE}/polls/{poll_id}/close")
    assert close_resp.status_code == 200
    assert close_resp.json()["isOpen"] is False

    resp = await client.get(f"{_BASE}/polls")
    poll = next(p for p in resp.json() if p["id"] == str(poll_id))
    for c in poll["candidates"]:
        assert c["voteCount"] is not None


async def test_cannot_vote_twice(driver_client: AsyncClient, db: AsyncSession, test_user):
    """Second vote attempt for same poll returns 409."""
    poll_id, candidate_ids = await _create_poll_in_db(db, test_user.id)
    candidate_id = str(candidate_ids[0])

    first = await driver_client.post(
        f"{_BASE}/polls/{poll_id}/vote", params={"candidate_id": candidate_id}
    )
    assert first.status_code == 200

    second = await driver_client.post(
        f"{_BASE}/polls/{poll_id}/vote", params={"candidate_id": candidate_id}
    )
    assert second.status_code == 409


async def test_close_poll_manually(admin_client: AsyncClient):
    """PATCH /close makes is_open False."""
    create = await admin_client.post(f"{_BASE}/polls", json=_poll_payload())
    poll_id = create.json()["id"]

    resp = await admin_client.patch(f"{_BASE}/polls/{poll_id}/close")
    assert resp.status_code == 200
    assert resp.json()["isOpen"] is False


async def test_poll_excluded_after_24h(client: AsyncClient, db: AsyncSession, seed_roles):
    """Polls closed more than 24h ago are not returned."""
    from app.models.dotd import DotdPoll as Poll

    poll_id, _ = await _create_poll_in_db(db, uuid.uuid4())

    # Force closes_at to 25 hours ago
    result = await db.execute(sa_select(Poll).where(Poll.id == poll_id))
    poll = result.scalar_one()
    poll.closes_at = _now() - timedelta(hours=25)
    poll.is_manually_closed = True
    await db.commit()

    resp = await client.get(f"{_BASE}/polls")
    ids = [p["id"] for p in resp.json()]
    assert str(poll_id) not in ids


async def test_candidates_ordered_by_championship_position(admin_client: AsyncClient):
    """Candidates come back sorted by championship_position asc."""
    payload = _poll_payload()
    payload["candidates"] = [
        {"driverName": "C Driver", "championshipPosition": 3},
        {"driverName": "A Driver", "championshipPosition": 1},
        {"driverName": "B Driver", "championshipPosition": 2},
    ]
    create = await admin_client.post(f"{_BASE}/polls", json=payload)
    assert create.status_code == 201
    positions = [c["championshipPosition"] for c in create.json()["candidates"]]
    assert positions == [1, 2, 3]

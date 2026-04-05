"""Shared pytest fixtures for backend tests.

The DATABASE_URL env var is set to an in-memory SQLite URL *before* any app
module is imported, so that ``app.database.engine`` is created against SQLite
(which is available locally) instead of PostgreSQL+asyncpg (which is not).
"""
from __future__ import annotations

import os

# ── Must be set before any app imports ─────────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Engine / Session helpers
# ---------------------------------------------------------------------------

def _make_engine():
    """Return a fresh in-memory SQLite async engine with StaticPool.

    StaticPool keeps a single connection, so every session created from this
    engine shares the same in-memory database.  That lets the test ``db``
    session and the service's own session (patched into app.database) both
    read each other's committed data.

    The ``simgrid_cache`` table is excluded because it uses ``JSONB``
    (a PostgreSQL-only type that has no SQLite equivalent).
    """
    import app.models.user  # noqa: F401 – registers Role/User/Session on Base
    import app.models.simgrid_cache  # noqa: F401 – ensure table is registered
    import app.models.incidents  # noqa: F401 – registers IncidentWindow/Incident/IncidentResolution
    import app.models.dotd  # noqa: F401 – registers DotdPoll/DotdCandidate/DotdVote
    from app.models.bwp import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Only create tables that SQLite can handle (excludes JSONB-typed tables)
    sqlite_tables = [
        t for t in Base.metadata.sorted_tables if t.name != "simgrid_cache"
    ]
    return engine, sqlite_tables


def _factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory SQLite engine for one test; tables created once."""
    _engine, tables = _make_engine()

    async with _engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: [t.create(sync_conn, checkfirst=True) for t in tables])

    yield _engine
    await _engine.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    """Open async session against the test engine."""
    async with _factory(engine)() as session:
        yield session


# ── Seed / entity helpers ---------------------------------------------------

@pytest_asyncio.fixture
async def seed_roles(db: AsyncSession):
    from app.models.user import Role
    db.add_all([Role(id=1, name="driver"), Role(id=2, name="admin")])
    await db.commit()


@pytest_asyncio.fixture
async def test_user(db: AsyncSession, seed_roles):
    """A persisted User with role 'driver' and display_name 'Test Driver'."""
    from app.models.user import User

    u = User(
        id=uuid.uuid4(),
        discord_id="111222333",
        username="tester",
        display_name="Test Driver",
        role_id=1,
        created_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.commit()

    # Re-load with the role relationship eagerly joined so that
    # user.role.name is accessible even after the session is released.
    result = await db.execute(
        select(User).options(joinedload(User.role)).where(User.id == u.id)
    )
    return result.scalar_one()


# ── HTTP clients ------------------------------------------------------------

@pytest_asyncio.fixture
async def client(engine):
    """Unauthenticated AsyncClient wired to the test database."""
    import app.database as db_module
    from app.database import get_db
    from app.main import app

    factory = _factory(engine)
    original = db_module.async_session
    db_module.async_session = factory

    async def _override_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)
    db_module.async_session = original


@pytest_asyncio.fixture
async def auth_client(engine, test_user):
    """Authenticated AsyncClient that injects ``test_user`` as current user."""
    import app.database as db_module
    from app.auth import get_current_user, get_current_user_optional
    from app.database import get_db
    from app.main import app

    factory = _factory(engine)
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

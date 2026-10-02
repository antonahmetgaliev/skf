"""Guards against relationship loading that grows with the size of the data."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import event
from starlette.requests import Request

from app.auth import SESSION_COOKIE, get_current_user_optional
from app.models.user import Session, User


def _request_with_session(session_id: uuid.UUID) -> Request:
    cookie = f"{SESSION_COOKIE}={session_id}".encode()
    return Request({"type": "http", "headers": [(b"cookie", cookie)]})


async def test_session_lookup_does_not_load_other_users(engine, db, seed_roles):
    now = datetime.now(UTC)
    users = [
        User(id=uuid.uuid4(), discord_id=str(i), username=f"u{i}", display_name=f"U{i}", role_id=1)
        for i in range(20)
    ]
    db.add_all(users)
    sessions = [Session(user_id=u.id, expires_at=now + timedelta(days=1)) for u in users]
    db.add_all(sessions)
    await db.commit()
    db.expunge_all()

    statements: list[str] = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        user = await get_current_user_optional(_request_with_session(sessions[0].id), db)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert user is not None and user.role.name == "driver"
    # Session + user (+ role joined); nothing that scales with other users.
    assert len(statements) <= 2, statements

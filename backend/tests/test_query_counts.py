"""Guards against relationship loading that grows with the size of the data."""

from __future__ import annotations

import uuid

from sqlalchemy import event
from starlette.requests import Request

from app.auth import get_current_user_optional
from app.models.user import User
from app.services import tokens


def _request_with_token(user_id: uuid.UUID) -> Request:
    token, _ = tokens.issue_access_token(user_id)
    return Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})


async def test_token_lookup_is_one_statement(engine, db, seed_roles):
    users = [
        User(id=uuid.uuid4(), discord_id=str(i), username=f"u{i}", display_name=f"U{i}", role_id=1)
        for i in range(20)
    ]
    db.add_all(users)
    await db.commit()
    db.expunge_all()

    statements: list[str] = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        user = await get_current_user_optional(_request_with_token(users[0].id), db)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert user is not None and user.role.name == "driver"
    # The user with its role joined; nothing else, and nothing that scales.
    assert len(statements) == 1, statements

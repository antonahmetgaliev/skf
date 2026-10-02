"""Helpers for acting as users of a given role in router tests."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import joinedload


async def make_user(db, role_name: str):
    """Persist a user with *role_name* (creating the role if needed)."""
    from app.models.user import Role, User

    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one_or_none()
    if role is None:
        role = Role(name=role_name)
        db.add(role)
        await db.flush()
    uid = uuid.uuid4()
    db.add(User(id=uid, discord_id=str(uid.int)[:18], username=f"{role_name}-{uid.hex[:6]}", role_id=role.id))
    await db.commit()
    return (await db.execute(select(User).options(joinedload(User.role)).where(User.id == uid))).scalar_one()


def act_as(user) -> None:
    """Make every following request authenticate as *user* (``None`` = anonymous)."""
    from app.auth import get_current_user, get_current_user_optional
    from app.main import app

    if user is None:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_user_optional, None)
        return
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_user_optional] = lambda: user


async def assign_manager(db, user, community_id) -> None:
    from app.models.community_manager import CommunityManager

    db.add(CommunityManager(user_id=user.id, community_id=community_id))
    await db.commit()

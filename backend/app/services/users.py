"""User serialisation and admin user management."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, Unprocessable
from app.models.bwp import Driver
from app.models.community import Community
from app.models.community_manager import CommunityManager
from app.models.user import ROLE_ADMIN, ROLE_COMMUNITY_MANAGER, ROLE_SUPER_ADMIN, Role, User
from app.repository import get_or_404
from app.schemas.auth import UserOut, UserUpdate
from app.services import tokens


def _user_out(user: User, driver_id: uuid.UUID | None, managed_ids: list[uuid.UUID]) -> UserOut:
    return UserOut(
        id=user.id,
        discord_id=user.discord_id,
        username=user.username,
        display_name=user.display_name,
        discord_nickname=user.guild_nickname,
        avatar_url=user.avatar_url,
        role=user.role.name,
        blocked=user.blocked,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        driver_id=driver_id,
        managed_community_ids=managed_ids,
    )


async def build_user_out(user: User, db: AsyncSession) -> UserOut:
    """Single source of truth for serialising one user — every endpoint
    must return the same shape (driver link and managed communities
    included), otherwise the frontend's cached user silently loses fields."""
    driver_id = (await db.execute(select(Driver.id).where(Driver.user_id == user.id))).scalars().first()
    managed_ids: list[uuid.UUID] = []
    if user.role.name == ROLE_COMMUNITY_MANAGER:
        managed_ids = await get_managed_communities(db, user.id)
    return _user_out(user, driver_id, managed_ids)


async def build_user_outs(users: Iterable[User], db: AsyncSession) -> list[UserOut]:
    """Serialise a page of users with two batched lookups."""
    users = list(users)
    ids = [u.id for u in users]
    if not ids:
        return []

    user_communities: dict[uuid.UUID, list[uuid.UUID]] = {}
    rows = await db.execute(
        select(CommunityManager.user_id, CommunityManager.community_id).where(
            CommunityManager.user_id.in_(ids)
        )
    )
    for user_id, community_id in rows.all():
        user_communities.setdefault(user_id, []).append(community_id)

    rows = await db.execute(select(Driver.user_id, Driver.id).where(Driver.user_id.in_(ids)))
    driver_by_user: dict[uuid.UUID, uuid.UUID] = {}
    for user_id, driver_id in rows.all():
        driver_by_user.setdefault(user_id, driver_id)

    return [_user_out(u, driver_by_user.get(u.id), user_communities.get(u.id, [])) for u in users]


def list_users_stmt():
    return select(User).order_by(User.username)


def _ensure_may_manage(admin: User, target: User) -> None:
    """A super-admin's account is out of reach for everyone but a super-admin."""
    if target.role.name == ROLE_SUPER_ADMIN and admin.role.name != ROLE_SUPER_ADMIN:
        raise Forbidden("Only a super-admin can modify another super-admin.")


async def update_user(db: AsyncSession, admin: User, user_id: uuid.UUID, body: UserUpdate) -> User:
    target = await get_or_404(db, User, user_id, detail="User not found.")
    _ensure_may_manage(admin, target)
    is_super_admin = admin.role.name == ROLE_SUPER_ADMIN

    # The role the target ends up with, for the block rules below.
    role_name = target.role.name
    if body.role is not None:
        new_role = (await db.execute(select(Role).where(Role.name == body.role))).scalar_one_or_none()
        if new_role is None:
            raise Unprocessable(f"Invalid role: {body.role}")
        if new_role.name == ROLE_SUPER_ADMIN and not is_super_admin:
            raise Forbidden("Only a super-admin can grant or revoke the super-admin role.")
        # Admins cannot change the role of other admins or themselves
        if target.role.name == ROLE_ADMIN and not is_super_admin:
            raise Forbidden("Only a super-admin can change an admin's role.")
        target.role_id = new_role.id
        role_name = new_role.name

    if body.blocked is not None:
        if role_name == ROLE_SUPER_ADMIN:
            raise Forbidden("Cannot block a super-admin.")
        if role_name == ROLE_ADMIN and not is_super_admin:
            raise Forbidden("Only a super-admin can block an admin.")
        target.blocked = body.blocked
        if body.blocked:
            await tokens.revoke_all(db, target)

    await db.commit()
    await db.refresh(target)
    return target


async def revoke_tokens(db: AsyncSession, admin: User, user_id: uuid.UUID) -> None:
    """End every login of a user (force logout)."""
    target = await get_or_404(db, User, user_id, detail="User not found.")
    _ensure_may_manage(admin, target)
    await tokens.revoke_all(db, target)
    await db.commit()


async def get_managed_communities(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await db.execute(select(CommunityManager.community_id).where(CommunityManager.user_id == user_id))
    return list(rows.scalars().all())


async def set_managed_communities(
    db: AsyncSession, admin: User, user_id: uuid.UUID, community_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Replace the full set of communities a user manages."""
    target = await get_or_404(db, User, user_id, detail="User not found.")
    _ensure_may_manage(admin, target)
    wanted = list(dict.fromkeys(community_ids))
    if wanted:
        existing = set(
            (await db.execute(select(Community.id).where(Community.id.in_(wanted)))).scalars().all()
        )
        missing = [str(cid) for cid in wanted if cid not in existing]
        if missing:
            raise Unprocessable(f"Unknown community: {', '.join(missing)}.")

    await db.execute(delete(CommunityManager).where(CommunityManager.user_id == user_id))
    db.add_all(CommunityManager(user_id=user_id, community_id=cid) for cid in wanted)
    await db.commit()
    return wanted

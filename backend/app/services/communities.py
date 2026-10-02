"""Communities shown on the calendar, their managers' access and join requests."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import is_admin
from app.core.errors import (
    BadGateway,
    BadRequest,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
)
from app.models.community import Community
from app.models.community_manager import CommunityManager
from app.models.user import ROLE_COMMUNITY_MANAGER, User
from app.repository import get_or_404
from app.schemas.calendar import CommunityCreate, CommunityRequestCreate, CommunityUpdate
from app.services.discord import (
    DiscordNotConfigured,
    DiscordSendFailed,
    send_community_request,
)

logger = logging.getLogger(__name__)

NO_ACCESS = "No access to this community."


# ── Access ───────────────────────────────────────────────────────────────────


def is_community_manager(user: User) -> bool:
    return user.role is not None and user.role.name == ROLE_COMMUNITY_MANAGER


async def managed_community_ids(db: AsyncSession, user: User) -> set[uuid.UUID]:
    result = await db.execute(
        select(CommunityManager.community_id).where(CommunityManager.user_id == user.id)
    )
    return set(result.scalars().all())


async def can_access_community(db: AsyncSession, user: User, community_id: uuid.UUID | None) -> bool:
    """Admins reach every community; managers only the ones assigned to them.

    ``None`` (a championship not tied to any community) is admin-only.
    """
    if is_admin(user):
        return True
    if community_id is None or not is_community_manager(user):
        return False
    return community_id in await managed_community_ids(db, user)


async def ensure_community_access(db: AsyncSession, user: User, community_id: uuid.UUID | None) -> None:
    if not await can_access_community(db, user, community_id):
        raise Forbidden(NO_ACCESS)


# ── CRUD ─────────────────────────────────────────────────────────────────────


async def list_visible(db: AsyncSession) -> list[Community]:
    """Visible communities, SKF first."""
    result = await db.execute(
        select(Community)
        .where(Community.is_visible.is_(True))
        .order_by(Community.is_skf.desc(), Community.name)
    )
    return list(result.scalars().all())


_NOT_FOUND = "Community not found."


async def get_visible(db: AsyncSession, user: User | None, community_id: uuid.UUID) -> Community:
    """The community at *community_id*; a hidden one exists only for those who manage it."""
    community = await get_or_404(db, Community, community_id, detail=_NOT_FOUND)
    if not community.is_visible and (user is None or not await can_access_community(db, user, community_id)):
        raise NotFound(_NOT_FOUND)
    return community


async def list_managed(db: AsyncSession, user: User) -> list[Community]:
    """Every community (incl. hidden) for admins, only assigned ones for managers."""
    stmt = select(Community).order_by(Community.is_skf.desc(), Community.name)
    if not is_admin(user):
        if not is_community_manager(user):
            raise Forbidden("Insufficient permissions.")
        stmt = stmt.where(Community.id.in_(await managed_community_ids(db, user)))
    return list((await db.execute(stmt)).scalars().all())


async def create(db: AsyncSession, body: CommunityCreate) -> Community:
    community = Community(
        name=body.name.strip(),
        color=body.color.strip() if body.color else None,
        discord_url=body.discord_url.strip() if body.discord_url else None,
    )
    db.add(community)
    await db.commit()
    await db.refresh(community)
    return community


async def update(db: AsyncSession, user: User, community_id: uuid.UUID, body: CommunityUpdate) -> Community:
    await ensure_community_access(db, user, community_id)
    community = await get_or_404(db, Community, community_id, detail="Community not found.")
    for field, value in body.model_dump(exclude_unset=True, by_alias=False).items():
        setattr(community, field, value.strip() if isinstance(value, str) else value)
    await db.commit()
    await db.refresh(community)
    return community


async def delete(db: AsyncSession, community_id: uuid.UUID) -> None:
    community = await get_or_404(db, Community, community_id, detail="Community not found.")
    if community.is_skf:
        raise BadRequest("The SKF community cannot be deleted.")
    await db.delete(community)
    await db.commit()


# ── Join requests ────────────────────────────────────────────────────────────

REQUEST_COOLDOWN = timedelta(minutes=10)
# In-process only: resets on restart and is per-worker. That is enough to blunt
# double-submits and casual spam, which is all this needs to do.
_last_request_at: dict[uuid.UUID, datetime] = {}


async def submit_request(body: CommunityRequestCreate, user: User) -> None:
    """Forward a logged-in user's community request to the SKF Discord.

    Nothing is persisted – the Discord message is the record.
    """
    now = datetime.now(UTC)

    # Drop expired entries so the dict cannot grow unbounded.
    for uid, sent_at in list(_last_request_at.items()):
        if now - sent_at > REQUEST_COOLDOWN:
            del _last_request_at[uid]

    last_sent = _last_request_at.get(user.id)
    if last_sent is not None and now - last_sent < REQUEST_COOLDOWN:
        raise TooManyRequests("You have already sent a request recently. Please wait a little.")

    discord_url = body.discord_url.strip() if body.discord_url else None
    try:
        await send_community_request(
            name=body.name.strip(),
            description=body.description.strip(),
            discord_url=discord_url or None,
            user=user,
        )
    except DiscordNotConfigured as exc:
        logger.error("Community request webhook is not configured")
        raise ServiceUnavailable("Community requests are temporarily unavailable.") from exc
    except DiscordSendFailed as exc:
        raise BadGateway("Could not deliver the request to Discord. Please try again later.") from exc

    _last_request_at[user.id] = now

"""User, Role & RefreshToken models for Discord OAuth."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.bwp import Base

if TYPE_CHECKING:
    from app.models.bwp import Driver


# ── Role lookup table ────────────────────────────────────────────────
class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    users: Mapped[list[User]] = relationship(back_populates="role", lazy="raise")

    def __repr__(self) -> str:
        return f"Role(id={self.id}, name={self.name!r})"


# Pre-defined role names (used for seeding & comparisons)
ROLE_DRIVER = "driver"
ROLE_MODERATOR = "moderator"
ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"
ROLE_JUDGE = "racing_judge"
ROLE_COMMUNITY_MANAGER = "community_manager"


class User(Base):
    """A site account: a Discord login with a role. Who the person is on track is ``driver``."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("driver_id", name="uq_users_driver_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    discord_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    guild_nickname: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role_id: Mapped[int] = mapped_column(Integer, ForeignKey("roles.id"), nullable=False)
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Access tokens issued up to this moment are refused (force logout, block).
    tokens_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The driver this person is. Staff who do not race have none.
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True
    )
    # Who made the link (a ``DriverLinkSource``); the sync never overrides an admin's.
    driver_link_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    role: Mapped[Role] = relationship(back_populates="users", lazy="joined")
    driver: Mapped[Driver | None] = relationship(back_populates="account", lazy="raise")

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )

    @property
    def avatar_url(self) -> str | None:
        if self.avatar_hash:
            return f"https://cdn.discordapp.com/avatars/{self.discord_id}/{self.avatar_hash}.png"
        return None


class RefreshToken(Base):
    """One refresh token of a login. Only its SHA-256 is stored.

    Every refresh replaces the token with a new one of the same ``family_id``;
    the old row stays, marked ``used_at``, so a replayed token is recognised
    and takes the whole family down with it.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

"""Auth & User schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field

from app.schemas.base import CamelModel, Omittable, Url
from app.schemas.enums import DriverLinkSource, DriverLinkStatus, UserRole


class UserOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    discord_id: str
    username: str
    display_name: str
    # Stored as users.guild_nickname.
    discord_nickname: str | None = Field(default=None, description="Nickname on the SKF Discord server.")
    avatar_url: Url | None = None
    role: UserRole
    blocked: bool
    created_at: datetime
    last_login_at: datetime | None = None
    driver_id: uuid.UUID | None = None
    driver_link_source: DriverLinkSource | None = None
    managed_community_ids: list[uuid.UUID] = []


class UserUpdate(CamelModel):
    role: Omittable[UserRole] = None
    blocked: Omittable[bool] = None


class UserDriverUpsert(CamelModel):
    driver_id: uuid.UUID


class DriverLinkOut(CamelModel):
    status: DriverLinkStatus
    driver_id: uuid.UUID | None = None


class AuthUrlOut(CamelModel):
    url: Url


class TokenCreate(CamelModel):
    refresh_token: str = Field(min_length=1, max_length=200)


class TokenRevocationCreate(CamelModel):
    refresh_token: str = Field(min_length=1, max_length=200)


class TokenOut(CamelModel):
    access_token: str = Field(description="Send as `Authorization: Bearer <accessToken>`.")
    refresh_token: str = Field(description="Replaces the one that was sent; each can be used once.")
    expires_in: int = Field(description="Lifetime of the access token, in seconds.")


class ManagedCommunitiesUpdate(CamelModel):
    community_ids: list[uuid.UUID]


class ManagedCommunitiesOut(CamelModel):
    community_ids: list[uuid.UUID]

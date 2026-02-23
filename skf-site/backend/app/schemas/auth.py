"""Auth & User schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict

from app.schemas.championship import CamelModel


class UserOut(CamelModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    discord_id: str
    username: str
    display_name: str
    avatar_url: str | None = None
    role: str
    blocked: bool
    created_at: datetime
    last_login_at: datetime | None = None


class UserUpdate(CamelModel):
    role: str | None = None
    blocked: bool | None = None


class AuthUrlOut(CamelModel):
    url: str

"""Access and refresh tokens.

An access token is a short-lived JWT that only names the user; role and block
state are read from the database on every request, so they take effect at
once. A refresh token is an opaque random string, stored as a hash and
replaced on every use.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import ServiceUnavailable, Unauthorized
from app.models.user import RefreshToken, User

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"

# Two tabs share one stored refresh token and may both spend it at the same
# moment. Within this window a second use is a race, not a theft.
REUSE_GRACE = timedelta(seconds=30)


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    issued_at: datetime


def _secret() -> str:
    if not settings.jwt_secret:
        raise ServiceUnavailable("Sign-in is not available.")
    return settings.jwt_secret


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _delete_tokens(*where):
    # Nothing in the session depends on the deleted rows, so skip evaluating
    # the criteria against loaded objects.
    return delete(RefreshToken).where(*where).execution_options(synchronize_session=False)


def as_utc(value: datetime) -> datetime:
    """SQLite hands datetimes back without a zone; they are stored as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def issue_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    """A signed access token for *user_id* and its lifetime in seconds."""
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.access_token_ttl_minutes)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + lifetime},
        _secret(),
        algorithm=ALGORITHM,
    )
    return token, int(lifetime.total_seconds())


def read_access_token(token: str) -> AccessClaims | None:
    """The claims of a valid, unexpired access token; ``None`` otherwise."""
    if not settings.jwt_secret:
        return None
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
        return AccessClaims(
            user_id=uuid.UUID(claims["sub"]),
            issued_at=datetime.fromtimestamp(claims["iat"], UTC),
        )
    except (jwt.InvalidTokenError, ValueError, TypeError):
        return None


def _new_refresh_token(user_id: uuid.UUID, family_id: uuid.UUID) -> tuple[str, RefreshToken]:
    raw = secrets.token_urlsafe(48)
    row = RefreshToken(
        user_id=user_id,
        family_id=family_id,
        token_hash=_hash(raw),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
    )
    return raw, row


def start_login(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Add the first refresh token of a new login; the caller commits."""
    _secret()
    raw, row = _new_refresh_token(user_id, uuid.uuid4())
    db.add(row)
    return raw


async def refresh(db: AsyncSession, raw: str) -> TokenPair:
    """Spend a refresh token: return a new access token and the next refresh token."""
    invalid = Unauthorized("The refresh token is not valid. Please sign in again.", code="invalid_token")
    now = datetime.now(UTC)

    row = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw)))
    ).scalar_one_or_none()
    if row is None or as_utc(row.expires_at) <= now:
        raise invalid

    if row.used_at is not None and now - as_utc(row.used_at) > REUSE_GRACE:
        # A token that was already replaced is being replayed: somebody else
        # holds a copy. End the whole login.
        logger.warning("Refresh token reuse for user %s; revoking the login", row.user_id)
        await db.execute(_delete_tokens(RefreshToken.family_id == row.family_id))
        await db.commit()
        raise invalid

    user = await db.get(User, row.user_id)
    if user is None or user.blocked:
        raise invalid

    access_token, expires_in = issue_access_token(user.id)
    next_raw, next_row = _new_refresh_token(user.id, row.family_id)
    if row.used_at is None:
        row.used_at = now
    db.add(next_row)
    await db.execute(_delete_tokens(RefreshToken.expires_at <= now))
    await db.commit()
    return TokenPair(access_token=access_token, refresh_token=next_raw, expires_in=expires_in)


async def revoke(db: AsyncSession, raw: str) -> None:
    """Sign out: end the login the refresh token belongs to, if it exists."""
    family_id = (
        await db.execute(select(RefreshToken.family_id).where(RefreshToken.token_hash == _hash(raw)))
    ).scalar_one_or_none()
    if family_id is None:
        return
    await db.execute(_delete_tokens(RefreshToken.family_id == family_id))
    await db.commit()


async def revoke_all(db: AsyncSession, user: User) -> None:
    """End every login of *user*, access tokens included; the caller commits."""
    await db.execute(_delete_tokens(RefreshToken.user_id == user.id))
    user.tokens_revoked_at = datetime.now(UTC)

"""Shared database cache helpers backed by the SimgridCache table."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select

from app.database import async_session
from app.models.simgrid_cache import SimgridCache

logger = logging.getLogger(__name__)


async def read_cache(
    key: str, ttl: timedelta
) -> dict | list | None:
    """Return cached data if fresher than *ttl*, else ``None``."""
    try:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(SimgridCache).where(SimgridCache.cache_key == key)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            age = datetime.now(timezone.utc) - row.fetched_at.replace(
                tzinfo=timezone.utc
            )
            if age > ttl:
                return None
            return row.data
    except Exception:
        logger.warning("Cache read failed for key=%s", key, exc_info=True)
        return None


async def read_stale_cache(key: str) -> dict | list | None:
    """Return cached data regardless of age (fallback for API failures)."""
    try:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(SimgridCache).where(SimgridCache.cache_key == key)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return row.data
    except Exception:
        logger.warning("Stale cache read failed for key=%s", key, exc_info=True)
        return None


async def write_cache(key: str, data: Any) -> None:
    """Insert or update a cache entry."""
    try:
        async with async_session() as session:
            existing = (
                await session.execute(
                    select(SimgridCache).where(SimgridCache.cache_key == key)
                )
            ).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if existing:
                existing.data = data
                existing.fetched_at = now
            else:
                session.add(
                    SimgridCache(cache_key=key, data=data, fetched_at=now)
                )
            await session.commit()
    except Exception:
        logger.warning("Cache write failed for key=%s", key, exc_info=True)


async def invalidate_cache_by_keys(*keys: str) -> None:
    """Delete cache entries with exact matching keys."""
    try:
        async with async_session() as session:
            await session.execute(
                delete(SimgridCache).where(SimgridCache.cache_key.in_(keys))
            )
            await session.commit()
    except Exception:
        logger.warning("Cache invalidation failed for keys=%s", keys, exc_info=True)


async def invalidate_cache_by_prefix(*prefixes: str) -> None:
    """Delete cache entries matching any of the given key prefixes.

    If no prefixes are given, deletes **all** cache entries.
    """
    try:
        async with async_session() as session:
            if prefixes:
                for prefix in prefixes:
                    await session.execute(
                        delete(SimgridCache).where(
                            SimgridCache.cache_key.like(f"{prefix}%")
                        )
                    )
            else:
                await session.execute(delete(SimgridCache))
            await session.commit()
    except Exception:
        logger.warning("Cache invalidation failed", exc_info=True)

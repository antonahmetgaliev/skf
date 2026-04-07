"""Admin router – site-wide management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.auth import require_admin
from app.models.user import User
from app.services.simgrid import simgrid_service
from app.services.youtube import youtube_service

router = APIRouter(prefix="/admin", tags=["Admin"])

_CACHE_DOMAINS = {
    "simgrid": lambda: simgrid_service.invalidate_cache(),
    "youtube": lambda: youtube_service.invalidate_cache(),
}


@router.post("/clear-cache", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cache(
    domain: str | None = Query(None, description="Cache domain to clear (simgrid, youtube). Clears all if omitted."),
    _: User = Depends(require_admin),
):
    """Invalidate cached external data, optionally filtered by domain."""
    if domain:
        handler = _CACHE_DOMAINS.get(domain)
        if handler:
            await handler()
    else:
        for handler in _CACHE_DOMAINS.values():
            await handler()

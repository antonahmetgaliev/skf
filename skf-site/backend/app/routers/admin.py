"""Admin router – site-wide management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.auth import require_admin
from app.models.user import User
from app.services.simgrid import simgrid_service
from app.services.youtube import youtube_service

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/clear-cache", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cache(_: User = Depends(require_admin)):
    """Invalidate all cached external data (SimGrid + YouTube)."""
    await simgrid_service.invalidate_cache()
    await youtube_service.invalidate_cache()

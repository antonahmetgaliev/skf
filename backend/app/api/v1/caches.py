"""Caches of external data (admin only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.auth import require_admin
from app.core.errors import NotFound
from app.services.simgrid import simgrid_service
from app.services.youtube import youtube_service

router = APIRouter(prefix="/caches", tags=["Caches"], dependencies=[Depends(require_admin)])

# Looked up at call time so the services' ``invalidate_cache`` can be patched.
_DOMAINS = {
    "simgrid": lambda: simgrid_service.invalidate_cache(),
    "youtube": lambda: youtube_service.invalidate_cache(),
}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_all_caches():
    for clear in _DOMAINS.values():
        await clear()


@router.delete("/{domain}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cache(domain: str):
    clear = _DOMAINS.get(domain)
    if clear is None:
        raise NotFound(f"Unknown cache: {domain}.")
    await clear()

"""Which SimGrid championships are shown to the public."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.user import User
from app.schemas.championship import ActiveChampionshipOut
from app.services import championships as service

router = APIRouter(prefix="/active-championships", tags=["Championships"])


@router.get("", response_model=list[int])
async def list_active_championships(db: AsyncSession = Depends(get_db)):
    """SimGrid ids of the active championships."""
    return await service.active_ids(db)


@router.put(
    "/{simgrid_id}",
    response_model=ActiveChampionshipOut,
    responses={201: {"model": ActiveChampionshipOut}},
)
async def activate_championship(
    simgrid_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Idempotent: 201 when the championship became active, 200 if it already was."""
    record, created = await service.activate(db, simgrid_id)
    if created:
        response.status_code = status.HTTP_201_CREATED
        response.headers["Location"] = f"/api/v1/active-championships/{simgrid_id}"
    return record


@router.delete("/{simgrid_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_championship(
    simgrid_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    await service.deactivate(db, simgrid_id)

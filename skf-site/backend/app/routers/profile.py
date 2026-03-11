"""Profile endpoints – links Discord users to their driver entries."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.bwp import Driver
from app.models.user import User
from app.schemas.bwp import DriverOut, DriverPublicOut, LinkCandidateOut

router = APIRouter(prefix="/profile", tags=["Profile"])


class LinkDriverBody(BaseModel):
    driver_id: uuid.UUID


@router.get("/link-candidates", response_model=list[LinkCandidateOut])
async def get_link_candidates(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return unlinked drivers whose name overlaps the user's SKF server nickname
    (guild_nickname), falling back to global display name or username."""
    search_name = (
        user.guild_nickname or user.display_name or user.username or ""
    ).strip()
    if not search_name:
        return []

    term = f"%{search_name}%"
    result = await db.execute(
        select(Driver).where(
            Driver.user_id.is_(None),
            or_(
                Driver.name.ilike(term),
                and_(
                    Driver.simgrid_display_name.isnot(None),
                    Driver.simgrid_display_name.ilike(term),
                ),
            ),
        )
    )
    return result.scalars().all()


@router.post("/link-driver", status_code=status.HTTP_204_NO_CONTENT)
async def link_driver(
    body: LinkDriverBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Link the authenticated user to a driver entry."""
    # Check if this user already has a linked driver
    result = await db.execute(select(Driver).where(Driver.user_id == user.id))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a linked driver.",
        )

    result = await db.execute(select(Driver).where(Driver.id == body.driver_id))
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found.")
    if driver.user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This driver is already linked to another account.",
        )

    driver.user_id = user.id
    await db.commit()


@router.delete("/unlink-driver", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_driver(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove the link between the authenticated user and their driver."""
    result = await db.execute(select(Driver).where(Driver.user_id == user.id))
    driver = result.scalar_one_or_none()
    if driver:
        driver.user_id = None
        await db.commit()


@router.get("/me/driver", response_model=DriverOut)
async def get_my_driver(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the driver linked to the authenticated user."""
    result = await db.execute(select(Driver).where(Driver.user_id == user.id))
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No linked driver.")
    return driver


@router.get("/drivers/{driver_id}", response_model=DriverPublicOut)
async def get_public_driver(
    driver_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return a public driver profile (no authentication required)."""
    result = await db.execute(select(Driver).where(Driver.id == driver_id))
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found.")
    return driver

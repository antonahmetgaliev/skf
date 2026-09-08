"""Profile endpoints – driver profiles for users and the public.

Account↔driver linking is fully automatic (via SimGrid's discord_uid, see
app.services.drivers) — there is no manual claim flow.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.bwp import Driver
from app.models.user import User
from app.schemas.bwp import DriverIndexEntry, DriverOut, DriverPublicOut
from app.schemas.championship import CamelModel

router = APIRouter(prefix="/profile", tags=["Profile"])


class PhotoUrlBody(CamelModel):
    photo_url: str | None = None


@router.get("/me/driver", response_model=DriverOut)
async def get_my_driver(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the driver linked to the authenticated user."""
    result = await db.execute(select(Driver).where(Driver.user_id == user.id))
    driver = result.scalars().first()
    if not driver:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No linked driver.")
    return driver


@router.get("/drivers", response_model=list[DriverPublicOut])
async def list_public_drivers(db: AsyncSession = Depends(get_db)):
    """Public driver directory (no user linkage exposed)."""
    result = await db.execute(select(Driver).order_by(Driver.name))
    return result.scalars().all()


@router.get("/drivers-index", response_model=list[DriverIndexEntry])
async def drivers_index(db: AsyncSession = Depends(get_db)):
    """Slim public list for mapping SimGrid ids to driver UUIDs."""
    result = await db.execute(
        select(Driver).where(Driver.simgrid_driver_id.isnot(None))
    )
    return result.scalars().all()


@router.get("/drivers/{driver_id}", response_model=DriverPublicOut)
async def get_public_driver(
    driver_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return a public driver profile by internal UUID or SimGrid numeric ID."""
    driver = None

    # Try as UUID first
    try:
        uid = uuid.UUID(driver_id)
        result = await db.execute(select(Driver).where(Driver.id == uid))
        driver = result.scalar_one_or_none()
    except ValueError:
        pass

    # Fall back to SimGrid numeric ID
    if driver is None and driver_id.isdigit():
        simgrid_id = int(driver_id)
        result = await db.execute(
            select(Driver).where(Driver.simgrid_driver_id == simgrid_id)
        )
        driver = result.scalars().first()

    if not driver:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found.")
    return driver


@router.patch("/me/driver-photo", response_model=DriverPublicOut)
async def update_driver_photo(
    body: PhotoUrlBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Allow the linked user to set or clear their driver profile photo URL."""
    result = await db.execute(select(Driver).where(Driver.user_id == user.id))
    driver = result.scalars().first()
    if not driver:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No linked driver.")
    if body.photo_url:
        url = body.photo_url.strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Photo URL must start with http:// or https://",
            )
        if len(url) > 500:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Photo URL must be at most 500 characters.",
            )
        driver.photo_url = url
    else:
        driver.photo_url = None
    await db.commit()
    await db.refresh(driver)
    return driver

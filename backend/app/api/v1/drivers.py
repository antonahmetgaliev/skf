"""Drivers, their BWP points and penalty clearances, and the caller's own driver.

``GET /drivers`` and ``GET /drivers/{id}`` answer with the public projection
(:class:`DriverPublicOut`, no account linkage). ``?include=account`` switches
to the judge view (:class:`DriverOut`, adds ``userId``) and needs the judge
role. In OpenAPI both are documented as ``DriverPublicOut | DriverOut``; the
judge view is the one that carries ``userId``.

Account↔driver linking is automatic (SimGrid ``discord_uid``, see
:mod:`app.services.drivers`); there is no manual claim flow.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import JUDGE_ROLES, get_current_user, get_current_user_optional, require_admin, require_judge
from app.core.errors import Forbidden, Unauthorized
from app.core.openapi import problem_responses
from app.core.pagination import PageParams, page_params, paginate
from app.database import get_db
from app.models.bwp import Driver
from app.models.user import User
from app.schemas.bwp import (
    BwpPointCreate,
    BwpPointOut,
    BwpPointUpdate,
    BwpResetCreate,
    DriverCreate,
    DriverOut,
    DriverPublicOut,
    DriverUpdate,
    MyDriverPhotoUpdate,
    PenaltyClearanceOut,
)
from app.services import bwp as service

router = APIRouter(tags=["Drivers"])

Include = Literal["account"]
include_query = Query(
    None,
    description="`account` adds the linked site account (`userId`); judges only.",
)


def _project(
    drivers: list[Driver], include: Include | None, user: User | None
) -> list[DriverPublicOut] | list[DriverOut]:
    if include != "account":
        return [DriverPublicOut.model_validate(d) for d in drivers]
    if user is None:
        raise Unauthorized("Not authenticated.")
    if user.role is None or user.role.name not in JUDGE_ROLES:
        raise Forbidden("Insufficient permissions.")
    return [DriverOut.model_validate(d) for d in drivers]


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------


@router.get(
    "/drivers",
    response_model=list[DriverPublicOut | DriverOut],
    responses=problem_responses(401, 403),
)
async def list_drivers(
    request: Request,
    response: Response,
    simgrid_id: int | None = Query(None, alias="simgridId"),
    include: Include | None = include_query,
    page: PageParams = Depends(page_params),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Driver directory, ordered by name. ``?simgridId=`` finds a SimGrid driver."""
    if include is not None:
        _project([], include, user)  # authorise before touching the DB
    drivers = await paginate(db, service.drivers_query(simgrid_id), page, request, response)
    return _project(drivers, include, user)


@router.get(
    "/drivers/{driver_id}",
    response_model=DriverPublicOut | DriverOut,
    responses=problem_responses(401, 403),
)
async def get_driver(
    driver_id: uuid.UUID,
    include: Include | None = include_query,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    if include is not None:
        _project([], include, user)
    driver = await service.get_driver(db, driver_id)
    return _project([driver], include, user)[0]


@router.post(
    "/drivers",
    response_model=DriverOut,
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(409),
)
async def create_driver(
    body: DriverCreate,
    response: Response,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    driver = await service.create_driver(db, body)
    response.headers["Location"] = f"/api/v1/drivers/{driver.id}"
    return driver


@router.patch("/drivers/{driver_id}", response_model=DriverOut, responses=problem_responses(409))
async def update_driver(
    driver_id: uuid.UUID,
    body: DriverUpdate,
    _: User = Depends(require_judge),
    db: AsyncSession = Depends(get_db),
):
    return await service.update_driver(db, driver_id, body)


@router.delete("/drivers/{driver_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_driver(
    driver_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_driver(db, driver_id)


# ---------------------------------------------------------------------------
# BWP points and resets
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/{driver_id}/bwp-points",
    response_model=BwpPointOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_bwp_point(
    driver_id: uuid.UUID,
    body: BwpPointCreate,
    response: Response,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    point = await service.add_point(db, driver_id, body)
    response.headers["Location"] = f"/api/v1/bwp-points/{point.id}"
    return point


@router.patch("/bwp-points/{point_id}", response_model=BwpPointOut)
async def update_bwp_point(
    point_id: uuid.UUID,
    body: BwpPointUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Expire a point today (``{"expired": true}``); already expired points are unchanged."""
    return await service.expire_point(db, point_id, body)


@router.delete("/bwp-points/{point_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bwp_point(
    point_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_point(db, point_id)


@router.post(
    "/drivers/{driver_id}/bwp-resets",
    response_model=DriverOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_bwp_reset(
    driver_id: uuid.UUID,
    body: BwpResetCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Expire every active point of the driver and remove their clearances."""
    return await service.reset_driver(db, driver_id, body)


# ---------------------------------------------------------------------------
# Penalty clearances
# ---------------------------------------------------------------------------


@router.put(
    "/drivers/{driver_id}/clearances/{rule_id}",
    response_model=PenaltyClearanceOut,
    responses={201: {"description": "Clearance created", "model": PenaltyClearanceOut}},
)
async def set_clearance(
    driver_id: uuid.UUID,
    rule_id: uuid.UUID,
    response: Response,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a penalty rule as cleared: 201 when created, 200 when it already was."""
    clearance, created = await service.put_clearance(db, driver_id, rule_id)
    if created:
        response.status_code = status.HTTP_201_CREATED
        response.headers["Location"] = f"/api/v1/drivers/{driver_id}/clearances/{rule_id}"
    return clearance


@router.delete(
    "/drivers/{driver_id}/clearances/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_clearance(
    driver_id: uuid.UUID,
    rule_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_clearance(db, driver_id, rule_id)


# ---------------------------------------------------------------------------
# The caller's own driver
# ---------------------------------------------------------------------------


@router.get("/me/driver", response_model=DriverOut, tags=["Me"])
async def get_my_driver(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The driver linked to the signed-in user (404 when none is linked)."""
    return await service.get_driver_for_user(db, user.id)


@router.patch("/me/driver", response_model=DriverOut, tags=["Me"])
async def update_my_driver(
    body: MyDriverPhotoUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set (``https://`` only) or clear (``null``) the profile photo."""
    return await service.set_my_driver_photo(db, user.id, body.photo_url)

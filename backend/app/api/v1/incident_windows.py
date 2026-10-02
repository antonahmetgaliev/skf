"""Incident windows and the incidents filed into them."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_optional, require_admin, require_judge
from app.core.openapi import problem_responses
from app.core.pagination import PageParams, page_params, paginate
from app.core.rate_limit import RateLimiter, client_ip
from app.database import get_db
from app.models.user import User
from app.schemas.incidents import (
    DefaultResolutionsOut,
    IncidentFileCreate,
    IncidentOut,
    IncidentWindowCreate,
    IncidentWindowListItem,
    IncidentWindowOut,
    IncidentWindowUpdate,
    WindowPublicationOut,
)
from app.services import incidents as svc

router = APIRouter(prefix="/incident-windows", tags=["Incidents"])

# Anonymous filings per client address; logged-in reporters are accountable
# and are not limited.
filing_limiter = RateLimiter(10, 600, detail="Too many incidents filed. Try again later.")


def _window_path(window_id: uuid.UUID) -> str:
    return f"/api/v1/incident-windows/{window_id}"


@router.get("", response_model=list[IncidentWindowListItem])
async def list_incident_windows(
    request: Request,
    response: Response,
    championship_id: int | None = Query(None, alias="championshipId"),
    page: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
):
    return await paginate(db, svc.list_windows_query(championship_id), page, request, response)


@router.post(
    "",
    response_model=IncidentWindowOut,
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(409),
)
async def create_incident_window(
    payload: IncidentWindowCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    window = await svc.create_window(db, payload, user)
    response.headers["Location"] = _window_path(window.id)
    return window


@router.get("/{window_id}", response_model=IncidentWindowOut)
async def get_incident_window(
    window_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    out = IncidentWindowOut.model_validate(await svc.load_window(db, window_id))
    svc.hide_unpublished_verdicts(out.incidents, current_user)
    return out


@router.patch("/{window_id}", response_model=IncidentWindowOut)
async def update_incident_window(
    window_id: uuid.UUID,
    payload: IncidentWindowUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    return await svc.update_window(db, window_id, payload)


@router.delete("/{window_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_incident_window(
    window_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    await svc.delete_window(db, window_id)


@router.post(
    "/{window_id}/incidents",
    response_model=IncidentOut,
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(409, 429),
)
async def file_incident(
    window_id: uuid.UUID,
    payload: IncidentFileCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """File an incident. Open to anonymous reporters, within limits."""
    if current_user is None:
        filing_limiter.hit(client_ip(request))
    incident = await svc.file_incident(db, window_id, payload, current_user)
    response.headers["Location"] = f"/api/v1/incidents/{incident.id}"
    return incident


@router.put(
    "/{window_id}/publication",
    response_model=WindowPublicationOut,
    responses=problem_responses(409),
)
async def publish_incident_window(
    window_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    """Make the round's verdicts public and issue the BWP they carry.

    One action for the whole window, and one-way: there is no way to hide
    verdicts again. Repeating it is safe — it publishes whatever was added
    since and never issues a penalty twice.
    """
    window, unlinked = await svc.publish_window(db, window_id)
    return WindowPublicationOut(window=IncidentWindowOut.model_validate(window), unlinked_count=unlinked)


@router.post(
    "/{window_id}/default-resolutions",
    response_model=DefaultResolutionsOut,
    responses=problem_responses(409),
)
async def create_default_resolutions(
    window_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_judge),
):
    """Apply the default verdict to every driver in the window still awaiting one."""
    window, resolved = await svc.resolve_remaining(db, window_id, user)
    return DefaultResolutionsOut(window=IncidentWindowOut.model_validate(window), resolved_count=resolved)

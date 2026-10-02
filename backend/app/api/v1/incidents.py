"""Incidents, the drivers involved in them, and BWP repair tools.

Also hosts the deprecated ``POST /api/incidents/ingest`` on ``legacy_router``:
an external client still calls that exact path.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.params import IncidentDriverId, IncidentId
from app.auth import get_current_user_optional, require_admin, require_api_token, require_judge
from app.core.openapi import problem_responses
from app.database import get_db
from app.models.user import User
from app.schemas.incidents import (
    BwpAuditEntryOut,
    BwpBackfillOut,
    IncidentBatchCreate,
    IncidentDriverCreate,
    IncidentDriverOut,
    IncidentDriverResolutionUpdate,
    IncidentDriverUpdate,
    IncidentOut,
    IncidentResolutionUpdate,
    IncidentWindowOut,
)
from app.services import incident_audit
from app.services import incidents as svc
from app.services.race_incidents import add_ingested_incidents, find_or_create_window

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Incidents"])


# ── Incidents ────────────────────────────────────────────────────────────────


@router.get("/incidents/{incidentId}", response_model=IncidentOut)
async def get_incident(
    incident_id: IncidentId,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    out = IncidentOut.model_validate(await svc.load_incident(db, incident_id))
    svc.hide_unpublished_verdicts([out], user)
    return out


@router.post(
    "/incidents/{incidentId}/copies", response_model=IncidentOut, status_code=status.HTTP_201_CREATED
)
async def copy_incident(
    incident_id: IncidentId,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_judge),
):
    """Copy an incident with its drivers; the copy is unresolved and unpublished."""
    copy = await svc.copy_incident(db, incident_id, user)
    response.headers["Location"] = f"/api/v1/incidents/{copy.id}"
    return copy


@router.post(
    "/incidents/{incidentId}/drivers",
    response_model=IncidentDriverOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_incident_driver(
    incident_id: IncidentId,
    payload: IncidentDriverCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    entry = await svc.add_driver(db, incident_id, payload.driver_name)
    response.headers["Location"] = f"/api/v1/incident-drivers/{entry.id}"
    return entry


@router.put(
    "/incidents/{incidentId}/resolution",
    response_model=IncidentOut,
    responses=problem_responses(400, 409),
)
async def resolve_incident(
    incident_id: IncidentId,
    payload: IncidentResolutionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_judge),
):
    """Set verdicts for several drivers of the incident; omitted verdicts get the default."""
    return await svc.resolve_incident(db, incident_id, payload, user)


# ── Incident drivers ─────────────────────────────────────────────────────────


@router.get("/incident-drivers/{incidentDriverId}", response_model=IncidentDriverOut)
async def get_incident_driver(
    incident_driver_id: IncidentDriverId,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    return await svc.incident_driver_out(db, incident_driver_id, user)


@router.delete("/incident-drivers/{incidentDriverId}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_incident_driver(
    incident_driver_id: IncidentDriverId,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    await svc.remove_driver(db, incident_driver_id)


@router.patch("/incident-drivers/{incidentDriverId}", response_model=IncidentDriverOut)
async def update_incident_driver(
    incident_driver_id: IncidentDriverId,
    payload: IncidentDriverUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    """Link the free-text incident driver to a driver record."""
    return await svc.link_driver(db, incident_driver_id, payload.driver_id)


@router.put("/incident-drivers/{incidentDriverId}/resolution", response_model=IncidentDriverOut)
async def resolve_incident_driver(
    incident_driver_id: IncidentDriverId,
    payload: IncidentDriverResolutionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_judge),
):
    return await svc.resolve_driver(db, incident_driver_id, payload, user)


# ── BWP audit / backfill ─────────────────────────────────────────────────────


@router.get("/bwp-audit-entries", response_model=list[BwpAuditEntryOut])
async def list_bwp_audit_entries(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Penalties marked applied whose driver was never linked, so no point exists."""
    return await incident_audit.bwp_audit(db)


@router.post("/bwp-backfills", response_model=BwpBackfillOut)
async def create_bwp_backfill(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Link audit entries whose name now matches a driver and issue their points."""
    return await incident_audit.bwp_backfill(db)


# ── Legacy batch ingestion (token-auth'd) ────────────────────────────────────

legacy_router = APIRouter(tags=["Legacy"])

SUCCESSOR_LINK = '</api/v1/incident-windows>; rel="successor-version"'


@legacy_router.post(
    "/incidents/ingest",
    response_model=IncidentWindowOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_token)],
    deprecated=True,
    responses=problem_responses(403, 409, 503),
)
async def ingest_incidents(
    payload: IncidentBatchCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Deprecated: kept at its old path for the external desktop parsers.

    Admins now upload the round's result file and the backend parses the
    contacts itself (``services/race_import.py``).
    """
    logger.warning(
        "Deprecated POST /api/incidents/ingest called (race %s, championship %s)",
        payload.race_id,
        payload.championship_id,
    )
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = SUCCESSOR_LINK
    window = await find_or_create_window(db, race_id=payload.race_id, championship_id=payload.championship_id)
    await add_ingested_incidents(db, window, payload.incidents)
    await db.commit()
    response.headers["Location"] = f"/api/v1/incident-windows/{window.id}"
    return await svc.load_window(db, window.id)

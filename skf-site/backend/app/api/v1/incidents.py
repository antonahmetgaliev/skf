"""Incidents, the drivers involved in them, and BWP repair tools.

Also hosts the deprecated ``POST /api/incidents/ingest`` on ``legacy_router``:
an external client still calls that exact path.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin, require_api_token, require_judge
from app.database import get_db
from app.models.user import User
from app.schemas.incidents import (
    BulkResolveIncident,
    BwpAuditEntry,
    BwpBackfillOut,
    IncidentBatchCreate,
    IncidentDriverAdd,
    IncidentDriverOut,
    IncidentDriverUpdate,
    IncidentOut,
    IncidentWindowOut,
    ResolveDriverIncident,
)
from app.services import incidents as svc
from app.services.race_import import add_ingested_incidents, find_or_create_window

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Incidents"])


# ── Incidents ────────────────────────────────────────────────────────────────


@router.post(
    "/incidents/{incident_id}/copies", response_model=IncidentOut, status_code=status.HTTP_201_CREATED
)
async def copy_incident(
    incident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_judge),
):
    """Copy an incident with its drivers; the copy is unresolved and unpublished."""
    return await svc.copy_incident(db, incident_id, user)


@router.post(
    "/incidents/{incident_id}/drivers",
    response_model=IncidentDriverOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_incident_driver(
    incident_id: uuid.UUID,
    payload: IncidentDriverAdd,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    return await svc.add_driver(db, incident_id, payload.driver_name)


@router.put("/incidents/{incident_id}/resolution", response_model=IncidentOut)
async def resolve_incident(
    incident_id: uuid.UUID,
    payload: BulkResolveIncident,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_judge),
):
    """Set verdicts for several drivers of the incident; omitted verdicts get the default."""
    return await svc.resolve_incident(db, incident_id, payload, user)


# ── Incident drivers ─────────────────────────────────────────────────────────


@router.delete("/incident-drivers/{incident_driver_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_incident_driver(
    incident_driver_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    await svc.remove_driver(db, incident_driver_id)


@router.patch("/incident-drivers/{incident_driver_id}", response_model=IncidentDriverOut)
async def update_incident_driver(
    incident_driver_id: uuid.UUID,
    payload: IncidentDriverUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_judge),
):
    """Link the free-text incident driver to a driver record."""
    return await svc.link_driver(db, incident_driver_id, payload.driver_id)


@router.put("/incident-drivers/{incident_driver_id}/resolution", response_model=IncidentDriverOut)
async def resolve_incident_driver(
    incident_driver_id: uuid.UUID,
    payload: ResolveDriverIncident,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_judge),
):
    return await svc.resolve_driver(db, incident_driver_id, payload, user)


# ── BWP audit / backfill ─────────────────────────────────────────────────────


@router.get("/bwp-audit-entries", response_model=list[BwpAuditEntry])
async def list_bwp_audit_entries(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Penalties marked applied whose driver was never linked, so no point exists."""
    return await svc.bwp_audit(db)


@router.post("/bwp-backfills", response_model=BwpBackfillOut)
async def create_bwp_backfill(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Link audit entries whose name now matches a driver and issue their points."""
    return await svc.bwp_backfill(db)


# ── Legacy batch ingestion (token-auth'd) ────────────────────────────────────

legacy_router = APIRouter(tags=["Legacy"])

SUCCESSOR_LINK = '</api/v1/incident-windows>; rel="successor-version"'


@legacy_router.post(
    "/incidents/ingest",
    response_model=IncidentWindowOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_token)],
    deprecated=True,
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
    return await svc.load_window(db, window.id)

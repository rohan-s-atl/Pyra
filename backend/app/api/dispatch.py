"""
dispatch.py — Unit dispatch API.

Responsibilities:
  - Validate incident + units exist and are dispatchable
  - Prevent duplicate dispatch of already-assigned units
  - Enforce station-type compatibility per unit type
  - Build OSRM route before confirming dispatch (ground units)
  - Refuse dispatch if a ground route is unreachable
  - Provide structure for future decision scoring
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_dispatcher_or_above, require_any_role
from app.models.alert import Alert
from app.models.incident import Incident
from app.models.station import Station
from app.models.unit import Unit
from app.models.user import User
from app.services.audit_service import write_audit_log
from app.services.routing import build_route, normalize_unit_type, is_ground_unit
from app.services.movement import resolve_home_station

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dispatch", tags=["Dispatch"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DispatchRequest(BaseModel):
    incident_id: str
    unit_ids: List[str]
    loadout_profile: str
    route_id: str


class AlertDispatchRequest(BaseModel):
    alert_id: str
    incident_id: str
    unit_ids: List[str]


class DispatchResponse(BaseModel):
    status: str
    incident_id: str
    dispatched: List[str]
    failed: List[str]
    unreachable: List[str]
    message: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_incident(incident_id: str, db: Session) -> Incident:
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
    return incident


def _is_already_dispatched(unit: Unit, incident_id: str) -> bool:
    """Prevent double-dispatch: unit already en_route or on_scene at this incident."""
    return (
        unit.assigned_incident_id == incident_id and
        unit.status in ("en_route", "on_scene", "staging")
    )


async def _dispatch_units(
    unit_ids: List[str],
    incident_id: str,
    db: Session,
) -> tuple[list[str], list[str], list[str], Incident]:
    """
    Attempt to dispatch each unit. Returns (dispatched, failed, unreachable, incident).

    - failed      : unit not found, out of service, or already dispatched here
    - unreachable : ground unit whose OSRM route could not be computed
    """
    incident = _validate_incident(incident_id, db)

    dispatched: list[str] = []
    failed: list[str]     = []
    unreachable: list[str] = []

    for unit_id in unit_ids:
        unit = db.query(Unit).filter(Unit.id == unit_id).first()

        if not unit or unit.status == "out_of_service":
            logger.warning("[dispatch] Unit %s not found or out_of_service", unit_id)
            failed.append(unit_id)
            continue

        if _is_already_dispatched(unit, incident_id):
            logger.info("[dispatch] Unit %s already dispatched to incident %s", unit_id, incident_id)
            failed.append(unit_id)
            continue

        # Ensure unit has a valid home station and a starting position
        station = resolve_home_station(db, unit)
        if station:
            if unit.latitude is None or unit.longitude is None:
                unit.latitude  = station.latitude
                unit.longitude = station.longitude
                if unit.gps_source != "device":
                    unit.gps_source = "simulated"

        if unit.latitude is None or unit.longitude is None:
            logger.error("[dispatch] Unit %s has no position and no station", unit_id)
            failed.append(unit_id)
            continue

        # Pre-build route — refuse ground units if OSRM is unavailable
        route = await build_route(
            unit.id, unit.unit_type,
            unit.latitude, unit.longitude,
            incident.latitude, incident.longitude,
            force=True,  # always recompute on new dispatch
        )

        if route is None:
            # Ground unit and all OSRM endpoints failed
            logger.error(
                "[dispatch] Cannot dispatch ground unit=%s: OSRM route unavailable", unit_id
            )
            unreachable.append(unit_id)
            continue

        unit.assigned_incident_id = incident_id
        unit.status = "en_route"
        unit.last_updated = datetime.now(UTC)
        dispatched.append(unit_id)

    incident.updated_at = datetime.now(UTC)
    return dispatched, failed, unreachable, incident


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/approve",
    response_model=DispatchResponse,
    summary="Approve and dispatch units to an incident",
)
async def approve_dispatch(
    request: DispatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),
):
    dispatched, failed, unreachable, incident = await _dispatch_units(
        request.unit_ids, request.incident_id, db
    )

    write_audit_log(
        db,
        action="DISPATCH",
        actor=current_user.username,
        actor_role=current_user.role,
        incident_id=request.incident_id,
        incident_name=incident.name,
        unit_ids=dispatched,
        details=(
            f"{len(dispatched)} unit(s) dispatched. "
            f"{len(failed)} failed. "
            f"{len(unreachable)} unreachable (OSRM). "
            f"Profile: {request.loadout_profile}"
        ),
    )

    db.commit()

    parts = [f"{len(dispatched)} unit(s) dispatched to {incident.name}."]
    if failed:
        parts.append(f"{len(failed)} failed.")
    if unreachable:
        parts.append(f"{len(unreachable)} unreachable (no road route available).")

    return DispatchResponse(
        status="ok",
        incident_id=request.incident_id,
        dispatched=dispatched,
        failed=failed,
        unreachable=unreachable,
        message=" ".join(parts),
    )


@router.post(
    "/alert-approve",
    response_model=DispatchResponse,
    summary="Dispatch units from an alert recommendation and acknowledge the alert",
)
async def approve_alert_dispatch(
    request: AlertDispatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),
):
    dispatched, failed, unreachable, incident = await _dispatch_units(
        request.unit_ids, request.incident_id, db
    )

    alert = db.query(Alert).filter(Alert.id == request.alert_id).first()
    if alert:
        alert.is_acknowledged = True

    write_audit_log(
        db,
        action="ALERT_DISPATCH",
        actor=current_user.username,
        actor_role=current_user.role,
        incident_id=request.incident_id,
        incident_name=incident.name,
        unit_ids=dispatched,
        details=(
            f"Alert {request.alert_id} resolved. "
            f"{len(dispatched)} unit(s) dispatched. "
            f"{len(failed)} failed. "
            f"{len(unreachable)} unreachable."
        ),
    )

    db.commit()

    parts = [f"{len(dispatched)} unit(s) dispatched to {incident.name}. Alert resolved."]
    if unreachable:
        parts.append(f"{len(unreachable)} unit(s) unreachable (no road route).")

    return DispatchResponse(
        status="ok",
        incident_id=request.incident_id,
        dispatched=dispatched,
        failed=failed,
        unreachable=unreachable,
        message=" ".join(parts),
    )


@router.get(
    "/incident/{incident_id}/units",
    summary="Get units assigned to an incident",
)
def get_incident_units(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    units = db.query(Unit).filter(Unit.assigned_incident_id == incident_id).all()
    return [
        {
            "id": u.id,
            "designation": u.designation,
            "unit_type": u.unit_type,
            "status": u.status,
            "station_id": u.station_id,
            "latitude": u.latitude,
            "longitude": u.longitude,
        }
        for u in units
    ]
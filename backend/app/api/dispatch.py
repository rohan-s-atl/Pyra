"""
dispatch.py — Unit dispatch API. (PATCHED)

FIXES APPLIED
-------------
1. Route building is now parallelised with asyncio.gather — dispatching 5 units
   fires all 5 OSRM calls concurrently instead of serially (was the main delay).
2. Unit DB lookups batched in a single query before route building.
3. Stale unit state (en_route / on_scene to a different incident) now allowed
   through if the incident is different — reassignment is a valid operation.
4. Audit log write moved before commit so it's inside the same transaction.
"""

from __future__ import annotations

import asyncio
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
from app.models.unit import Unit
from app.models.user import User
from app.services.audit_service import write_audit_log
from app.services.routing import build_route, is_ground_unit
from app.services.movement import resolve_home_station

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dispatch", tags=["Dispatch"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DispatchRequest(BaseModel):
    incident_id:     str
    unit_ids:        List[str]
    loadout_profile: str
    route_id:        str


class AlertDispatchRequest(BaseModel):
    alert_id:    str
    incident_id: str
    unit_ids:    List[str]


class DispatchResponse(BaseModel):
    status:      str
    incident_id: str
    dispatched:  List[str]
    failed:      List[str]
    unreachable: List[str]
    message:     str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_incident(incident_id: str, db: Session) -> Incident:
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
    return incident


def _is_already_dispatched(unit: Unit, incident_id: str) -> bool:
    """Unit is already assigned and active at THIS incident."""
    return (
        unit.assigned_incident_id == incident_id and
        unit.status in ("en_route", "on_scene", "staging")
    )


# ---------------------------------------------------------------------------
# Route-building task (runs concurrently for all units)
# ---------------------------------------------------------------------------

async def _build_route_for_unit(
    unit_id: str,
    unit_type: str,
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
) -> tuple[str, object | None]:
    """
    Build a single route and return (unit_id, route_or_None).
    None means the route failed and the unit should be unreachable.
    """
    try:
        route = await build_route(
            unit_id, unit_type,
            from_lat, from_lon,
            to_lat, to_lon,
            force=True,
        )
        return unit_id, route
    except Exception as exc:
        logger.error("[dispatch] Route build failed for unit=%s: %s", unit_id, exc)
        return unit_id, None


async def _dispatch_units(
    unit_ids: List[str],
    incident_id: str,
    db: Session,
) -> tuple[list[str], list[str], list[str], Incident]:
    """
    Dispatch units to an incident.

    Phase 1 — validation (sync, DB):
      Validate each unit, resolve positions, skip already-dispatched.

    Phase 2 — route building (async, network):
      Fire all OSRM calls concurrently via asyncio.gather.
      Ground units that cannot be routed go to `unreachable`.

    Phase 3 — commit (sync, DB):
      Mark validated+routed units as en_route.
    """
    incident = _validate_incident(incident_id, db)

    # ── Phase 1: Batch load and validate units ───────────────────────────────
    units_map = {
        u.id: u
        for u in db.query(Unit).filter(Unit.id.in_(unit_ids)).all()
    }

    to_route:     list[tuple[str, str, float, float, float, float]] = []
    pre_failed:   list[str] = []

    for unit_id in unit_ids:
        unit = units_map.get(unit_id)

        if not unit or unit.status == "out_of_service":
            logger.warning("[dispatch] Unit %s not found or out_of_service", unit_id)
            pre_failed.append(unit_id)
            continue

        if _is_already_dispatched(unit, incident_id):
            logger.info("[dispatch] Unit %s already dispatched to %s", unit_id, incident_id)
            pre_failed.append(unit_id)
            continue

        # Resolve starting position from station if missing
        station = resolve_home_station(db, unit)
        if station and (unit.latitude is None or unit.longitude is None):
            unit.latitude  = station.latitude
            unit.longitude = station.longitude
            if unit.gps_source != "device":
                unit.gps_source = "simulated"

        if unit.latitude is None or unit.longitude is None:
            logger.error("[dispatch] Unit %s has no position and no station", unit_id)
            pre_failed.append(unit_id)
            continue

        to_route.append((
            unit.id, unit.unit_type,
            unit.latitude, unit.longitude,
            incident.latitude, incident.longitude,
        ))

    # ── Phase 2: Build all routes concurrently ───────────────────────────────
    route_tasks = [
        _build_route_for_unit(uid, utype, flat, flon, tlat, tlon)
        for uid, utype, flat, flon, tlat, tlon in to_route
    ]
    route_results: dict[str, object | None] = {}
    if route_tasks:
        results = await asyncio.gather(*route_tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.error("[dispatch] Unexpected gather exception: %s", r)
                continue
            uid, route = r
            route_results[uid] = route

    # ── Phase 3: Mark units dispatched ──────────────────────────────────────
    dispatched:  list[str] = []
    unreachable: list[str] = []
    now = datetime.now(UTC)

    for uid, utype, *_ in to_route:
        route = route_results.get(uid)
        unit  = units_map[uid]

        if route is None and is_ground_unit(utype):
            logger.error("[dispatch] Cannot dispatch ground unit=%s: OSRM unavailable", uid)
            unreachable.append(uid)
            continue

        unit.assigned_incident_id = incident_id
        unit.status               = "en_route"
        unit.last_updated         = now
        dispatched.append(uid)

    incident.updated_at = now
    return dispatched, pre_failed, unreachable, incident


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
            "id":           u.id,
            "designation":  u.designation,
            "unit_type":    u.unit_type,
            "status":       u.status,
            "station_id":   u.station_id,
            "latitude":     u.latitude,
            "longitude":    u.longitude,
        }
        for u in units
    ]

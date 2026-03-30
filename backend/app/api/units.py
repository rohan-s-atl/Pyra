"""
units.py — Unit REST API.

PATCH: Fixed N+1 station query.
Previously _enrich_unit fired a separate SELECT per unit for its station.
list_units with 60 units = 61 DB round-trips. Now stations are batch-loaded
once in a single WHERE id IN (...) query — always exactly 2 queries total.
"""
from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.unit import Unit as UnitModel
from app.models.station import Station
from app.models.user import User
from app.services.routing import get_cached_route

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/units", tags=["Units"])


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _load_stations(db: Session, units: list[UnitModel]) -> dict:
    """Batch-load all stations referenced by `units` — single query."""
    station_ids = {u.station_id for u in units if u.station_id}
    if not station_ids:
        return {}
    return {s.id: s for s in db.query(Station).filter(Station.id.in_(station_ids)).all()}


def _enrich_unit(unit: UnitModel, stations: dict) -> dict:
    """
    Serialise a unit. `stations` must be pre-fetched via _load_stations —
    this function never issues a DB query itself.
    """
    data = {c.name: getattr(unit, c.name) for c in unit.__table__.columns}

    data["station_lat"]  = None
    data["station_lon"]  = None
    data["station_type"] = None
    if unit.station_id:
        station = stations.get(unit.station_id)
        if station:
            data["station_lat"]  = station.latitude
            data["station_lon"]  = station.longitude
            data["station_type"] = station.station_type

    route = get_cached_route(unit.id)
    data["route_waypoint_index"]  = route.index if route else None
    data["route_total_waypoints"] = len(route.waypoints) if route else None
    return data


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@router.get("/", summary="List all units")
def list_units(
    status: Optional[str] = None,
    incident_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    query = db.query(UnitModel)
    if status:
        query = query.filter(UnitModel.status == status)
    if incident_id:
        query = query.filter(UnitModel.assigned_incident_id == incident_id)
    units = query.all()
    stations = _load_stations(db, units)
    return [_enrich_unit(u, stations) for u in units]


@router.get("/{unit_id}", summary="Get unit by ID")
def get_unit(
    unit_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    unit = db.query(UnitModel).filter(UnitModel.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail=f"Unit '{unit_id}' not found")
    stations = _load_stations(db, [unit])
    return _enrich_unit(unit, stations)


@router.get("/{unit_id}/route", summary="Get current waypoints for a unit")
def get_unit_route(
    unit_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    unit = db.query(UnitModel).filter(UnitModel.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail=f"Unit '{unit_id}' not found")
    route = get_cached_route(unit_id)
    if not route:
        return {"unit_id": unit_id, "waypoints": [], "index": 0, "is_road_routed": False}
    return {
        "unit_id": unit_id,
        "waypoints": route.waypoints,
        "index": route.index,
        "is_road_routed": route.is_road_routed,
    }


class RouteRequest(BaseModel):
    to_lat: float
    to_lon: float


@router.post("/{unit_id}/route", summary="Build route on demand for map preview")
async def build_unit_route(
    unit_id: str,
    body: RouteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    from app.services.routing import build_route as _build_route

    unit = db.query(UnitModel).filter(UnitModel.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail=f"Unit '{unit_id}' not found")
    if unit.latitude is None or unit.longitude is None:
        raise HTTPException(status_code=422, detail="Unit has no current position")

    route = await _build_route(
        unit_id=unit_id,
        unit_type=unit.unit_type,
        from_lat=unit.latitude,
        from_lon=unit.longitude,
        to_lat=body.to_lat,
        to_lon=body.to_lon,
        force=True,
    )
    return {
        "unit_id":        unit_id,
        "waypoints":      route.waypoints,
        "index":          route.index,
        "is_road_routed": route.is_road_routed,
    }


# ---------------------------------------------------------------------------
# GPS update endpoint
# ---------------------------------------------------------------------------

class GpsUpdate(BaseModel):
    latitude:  float
    longitude: float
    accuracy_m: Optional[float] = None
    source: str = "device"
    timestamp: Optional[datetime] = None

    @field_validator("latitude")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not (-90 <= v <= 90):
            raise ValueError("latitude must be between -90 and 90")
        return round(v, 6)

    @field_validator("longitude")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not (-180 <= v <= 180):
            raise ValueError("longitude must be between -180 and 180")
        return round(v, 6)


@router.post("/{unit_id}/location", summary="Update unit GPS position (real device)")
def update_unit_location(
    unit_id: str,
    body: GpsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    unit = db.query(UnitModel).filter(UnitModel.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail=f"Unit '{unit_id}' not found")

    unit.latitude       = body.latitude
    unit.longitude      = body.longitude
    unit.gps_accuracy_m = body.accuracy_m
    unit.gps_source     = body.source
    unit.gps_updated_at = body.timestamp or datetime.now(UTC)
    unit.last_updated   = datetime.now(UTC)

    db.commit()
    db.refresh(unit)
    stations = _load_stations(db, [unit])
    return _enrich_unit(unit, stations)
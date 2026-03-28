"""
movement.py — Unit position advancement during simulation.

Responsibilities:
  - Advance en_route / returning units along their cached route
  - Detect arrival and transition unit status accordingly
  - Snap units to their home station when idle
  - Write position updates to the DB (in-memory session; caller commits)

This module is purely synchronous; it does NOT build routes.
Route building is in routing.py; orchestration is in simulation_service.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import Optional

from sqlalchemy.orm import Session

from app.models.unit import Unit
from app.models.incident import Incident
from app.models.station import Station
from app.services.routing import (
    advance_waypoint,
    get_cached_route,
    invalidate_route,
    normalize_unit_type,
    is_air_unit,
    GROUND_TYPES,
)

logger = logging.getLogger(__name__)

# Degrees within which a unit is considered "arrived" at its destination
ARRIVAL_THRESHOLD_DEG = 0.015

# Waypoints to advance per simulation tick
# Waypoints advanced per 2-second tick, by unit type.
# Ground units: 1 step (realistic road speed)
# Air units: 4 steps (helicopters/tankers travel ~3-4x faster than engines)
WAYPOINT_STEP_GROUND = 1
WAYPOINT_STEP_AIR    = 4


# ---------------------------------------------------------------------------
# Station helpers
# ---------------------------------------------------------------------------

_GROUND_STATION_TYPES = frozenset({"FSB", "FIRE_STATION", "FS"})
_HELI_STATION_TYPES   = frozenset({"HB", "HELIBASE", "HELIPAD", "PAD"})
_AIR_STATION_TYPES    = frozenset({"AAB", "AIRPORT", "AIR_ATTACK_BASE"})


def _station_matches_unit(station: Station, unit_type: str) -> bool:
    stype = (station.station_type or "").upper()
    ntype = normalize_unit_type(unit_type)
    if ntype == "helicopter":
        return stype in _HELI_STATION_TYPES
    if ntype == "air_tanker":
        return stype in _AIR_STATION_TYPES
    # Ground types must NOT be dispatched from air bases
    return stype not in (_HELI_STATION_TYPES | _AIR_STATION_TYPES)


def resolve_home_station(db: Session, unit: Unit) -> Optional[Station]:
    """
    Return the unit's assigned station if it is type-compatible.
    If not, find the nearest compatible station and correct unit.station_id.
    Returns None only if no stations exist.
    """
    if unit.station_id:
        station = db.query(Station).filter(Station.id == unit.station_id).first()
        if station and _station_matches_unit(station, unit.unit_type):
            return station

    all_stations = db.query(Station).all()
    if not all_stations:
        return None

    compatible = [s for s in all_stations if _station_matches_unit(s, unit.unit_type)]
    candidates = compatible or all_stations

    if unit.latitude is not None and unit.longitude is not None:
        best = min(candidates, key=lambda s: (
            (s.latitude - unit.latitude) ** 2 + (s.longitude - unit.longitude) ** 2
        ))
    else:
        best = candidates[0]

    if unit.station_id != best.id:
        logger.info("[movement] Corrected station_id for unit=%s: %s -> %s",
                    unit.id, unit.station_id, best.id)
        unit.station_id = best.id

    return best


# ---------------------------------------------------------------------------
# Position helpers
# ---------------------------------------------------------------------------

def _set_position(unit: Unit, lat: float, lon: float) -> None:
    unit.latitude  = round(lat, 5)
    unit.longitude = round(lon, 5)
    unit.last_updated = datetime.now(UTC)
    if unit.gps_source != "device":
        unit.gps_source = "simulated"


def _dist(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return ((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2) ** 0.5


def snap_to_station(db: Session, unit: Unit) -> bool:
    """Snap unit position to its home station. Returns True if successful."""
    station = resolve_home_station(db, unit)
    if not station:
        return False
    _set_position(unit, station.latitude, station.longitude)
    return True


# ---------------------------------------------------------------------------
# Movement: en_route
# ---------------------------------------------------------------------------

def advance_en_route(db: Session, unit: Unit) -> None:
    """
    Move an en_route unit one step along its cached route.
    Transitions to on_scene when the route end is reached.
    """
    step = WAYPOINT_STEP_AIR if is_air_unit(unit.unit_type) else WAYPOINT_STEP_GROUND
    new_pos = advance_waypoint(unit.id, step)
    if new_pos is None:
        # No cached route — unit may be stale (no assigned incident) or waiting for builder
        if not unit.assigned_incident_id:
            logger.warning("[movement] Unit=%s en_route with no incident — resetting", unit.id)
            unit.status = "available"
        # else: route builder job will populate cache within 10s, suppress repeated log
        return

    _set_position(unit, new_pos[0], new_pos[1])

    route = get_cached_route(unit.id)
    if route and route.at_end:
        _arrive_on_scene(db, unit)


def _arrive_on_scene(db: Session, unit: Unit) -> None:
    incident = (
        db.query(Incident)
        .filter(Incident.id == unit.assigned_incident_id)
        .first()
    ) if unit.assigned_incident_id else None

    if incident:
        _set_position(unit, incident.latitude, incident.longitude)

    unit.status = "on_scene"
    unit.on_scene_since = datetime.now(UTC)
    unit.last_updated = datetime.now(UTC)
    invalidate_route(unit.id)
    logger.info("[movement] Unit=%s arrived on_scene at incident=%s",
                unit.id, unit.assigned_incident_id)


# ---------------------------------------------------------------------------
# Movement: returning
# ---------------------------------------------------------------------------

def advance_returning(db: Session, unit: Unit) -> None:
    """
    Move a returning unit one step toward its home station.
    Transitions to available when the route end is reached.
    """
    station = resolve_home_station(db, unit)
    if not station:
        return

    step = WAYPOINT_STEP_AIR if is_air_unit(unit.unit_type) else WAYPOINT_STEP_GROUND
    new_pos = advance_waypoint(unit.id, step)
    if new_pos is None:
        logger.warning("[movement] No cached route for returning unit=%s", unit.id)
        return

    _set_position(unit, new_pos[0], new_pos[1])

    route = get_cached_route(unit.id)
    arrived = route is None or route.at_end or _dist(
        new_pos[0], new_pos[1], station.latitude, station.longitude
    ) < ARRIVAL_THRESHOLD_DEG

    if arrived:
        _arrive_at_base(db, unit, station)


def _arrive_at_base(db: Session, unit: Unit, station: Station) -> None:
    _set_position(unit, station.latitude, station.longitude)
    unit.status = "available"
    unit.assigned_incident_id = None
    unit.on_scene_since = None
    unit.last_updated = datetime.now(UTC)
    invalidate_route(unit.id)
    logger.info("[movement] Unit=%s returned to base station=%s", unit.id, station.id)


# ---------------------------------------------------------------------------
# Idle units: keep them pinned to their station
# ---------------------------------------------------------------------------

def pin_idle_unit(db: Session, unit: Unit) -> None:
    """
    Ensure available units with no assignment stay at their home station.
    Only corrects if the drift exceeds a negligible threshold.
    """
    station = resolve_home_station(db, unit)
    if not station:
        return

    if (unit.latitude is None or unit.longitude is None or
            _dist(unit.latitude, unit.longitude, station.latitude, station.longitude) > 0.001):
        _set_position(unit, station.latitude, station.longitude)
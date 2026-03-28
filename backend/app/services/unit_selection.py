"""
unit_selection.py — Unit scoring and selection helpers.

Used by the recommendation engine and dispatch advice to rank candidate units
for a given incident. Keeps routing concerns out of this module — travel time
is fetched via routing.get_travel_time_minutes.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.station import Station
from app.models.unit import Unit
from app.services.routing import normalize_unit_type, is_ground_unit, is_air_unit

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Distance
# ---------------------------------------------------------------------------

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in km between two WGS-84 points."""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(d_lon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Unit capability scoring
# ---------------------------------------------------------------------------

# Rough speed estimates (mph) by unit type, used for ETA when OSRM is unavailable
UNIT_SPEED_MPH: dict[str, float] = {
    "engine":       45,
    "hand_crew":    35,
    "dozer":        25,
    "water_tender": 40,
    "helicopter":   100,
    "air_tanker":   180,
    "command_unit": 50,
    "rescue":       55,
}


def estimate_eta_minutes(unit: Unit, incident: Incident) -> float:
    """Straight-line ETA estimate in minutes (no OSRM; for scoring only)."""
    if unit.latitude is None or unit.longitude is None:
        return 9999.0
    km = haversine_distance(unit.latitude, unit.longitude,
                            incident.latitude, incident.longitude)
    miles = km * 0.621371
    speed = UNIT_SPEED_MPH.get(normalize_unit_type(unit.unit_type), 40)
    return (miles / speed) * 60


def score_unit_for_incident(unit: Unit, incident: Incident) -> float:
    """
    Return a numeric score (higher = better) for dispatching `unit` to `incident`.

    Scoring factors:
      - Proximity (lower ETA = higher score)
      - Unit capability match for fire type
      - ICS type preference (Type 1 preferred for critical/extreme incidents)
      - Availability penalty for non-available status
    """
    if unit.status == "out_of_service":
        return -1.0

    eta = estimate_eta_minutes(unit, incident)
    proximity_score = max(0.0, 100.0 - eta)  # 0–100, higher is closer

    # Capability bonus
    ntype = normalize_unit_type(unit.unit_type)
    capability_bonus = 0.0
    if incident.fire_type in ("wildland", "wildland_urban_interface"):
        if ntype in ("engine", "hand_crew", "dozer", "water_tender"):
            capability_bonus = 20.0
        elif ntype in ("helicopter", "air_tanker"):
            capability_bonus = 15.0
    elif incident.fire_type == "structure":
        if ntype in ("engine", "rescue"):
            capability_bonus = 25.0
        elif ntype == "water_tender":
            capability_bonus = 10.0

    # Structure protection bonus
    if incident.structures_threatened and incident.structures_threatened > 0:
        if unit.has_structure_protection:
            capability_bonus += 10.0

    # ICS type bonus — prefer higher-typed (lower number) units for severe incidents
    ics_bonus = 0.0
    ics_type = (unit.ics_type or "").strip()
    severity = (incident.severity or "low").lower()
    spread   = (incident.spread_risk or "low").lower()
    if ics_type:
        # Map "Type 1" → 1, "Type 2" → 2, etc.
        type_num = None
        for part in ics_type.split():
            try:
                type_num = int(part)
                break
            except ValueError:
                continue

        if type_num is not None:
            if severity in ("critical", "high") or spread in ("extreme", "high"):
                # Strong preference for Type 1 on high-severity incidents
                ics_bonus = max(0.0, (4 - type_num) * 8.0)   # Type1=24, Type2=16, Type3=8
            else:
                # Moderate preference on lower-severity — don't waste Type 1 resources
                ics_bonus = max(0.0, (4 - type_num) * 3.0)

    # Penalise units not immediately available
    status_penalty = 0.0
    if unit.status == "staging":
        status_penalty = 5.0
    elif unit.status not in ("available",):
        status_penalty = 50.0

    return proximity_score + capability_bonus + ics_bonus - status_penalty


def rank_units_for_incident(
    units: list[Unit],
    incident: Incident,
    limit: int = 10,
) -> list[tuple[Unit, float]]:
    """Return [(unit, score), ...] sorted best-first, up to `limit` entries."""
    scored = [
        (u, score_unit_for_incident(u, incident))
        for u in units
        if u.status != "out_of_service"
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]

# ---------------------------------------------------------------------------
# Full dispatch recommendation (used by /api/recommendations/{id}/units)
# ---------------------------------------------------------------------------

def get_dispatch_recommendation(db: Session, incident_id: str) -> dict:
    """
    Full dispatch recommendation for an incident.

    1. Loads the incident.
    2. Runs the recommendation engine to determine required unit types + quantities.
    3. Scores all available units and picks the best matches.
    4. Returns a ranked list with ETAs and a summary.
    """
    from app.models.incident import Incident
    from app.intelligence.recommendation_engine import generate_recommendation
    from app.models.route import Route

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise ValueError(f"Incident '{incident_id}' not found")

    # Build incident dict for recommendation engine
    counts = {
        "on_scene": db.query(Unit).filter(
            Unit.assigned_incident_id == incident.id, Unit.status == "on_scene"
        ).count(),
        "en_route": db.query(Unit).filter(
            Unit.assigned_incident_id == incident.id, Unit.status == "en_route"
        ).count(),
    }
    routes = db.query(Route).filter(Route.incident_id == incident.id).all()
    incident_dict = {
        "id": incident.id, "name": incident.name,
        "fire_type": incident.fire_type, "severity": incident.severity,
        "status": incident.status, "spread_risk": incident.spread_risk,
        "spread_direction": incident.spread_direction,
        "wind_speed_mph": incident.wind_speed_mph,
        "humidity_percent": incident.humidity_percent,
        "containment_percent": incident.containment_percent,
        "structures_threatened": incident.structures_threatened,
        "acres_burned": incident.acres_burned,
        "elevation_m": incident.elevation_m,
        "slope_percent": incident.slope_percent,
        "aspect_cardinal": incident.aspect_cardinal,
        "aqi": incident.aqi, "aqi_category": incident.aqi_category,
        "units_on_scene": counts["on_scene"],
        "units_en_route": counts["en_route"],
    }
    routes_list = [
        {"id": r.id, "label": r.label,
         "estimated_travel_minutes": r.estimated_travel_minutes,
         "terrain_accessibility": r.terrain_accessibility,
         "fire_exposure_risk": r.fire_exposure_risk,
         "safety_rating": r.safety_rating,
         "is_currently_passable": r.is_currently_passable,
         "notes": r.notes,
         "origin_lat": r.origin_lat, "origin_lon": r.origin_lon,
         "destination_lat": r.destination_lat, "destination_lon": r.destination_lon}
        for r in routes
    ]
    rec = generate_recommendation(incident_dict, routes_list)
    needed: list[dict] = rec.get("unit_recommendations", rec.get("recommended_units", []))

    # Get all non-OOS available units
    available_units = db.query(Unit).filter(
        Unit.status.in_(["available", "staging"]),
        Unit.assigned_incident_id.is_(None),
    ).all()

    selected = []
    shortage = []

    for req in needed:
        unit_type = req.get("unit_type", "")
        quantity  = req.get("quantity", 1)
        priority  = req.get("priority", "within_1hr")

        candidates = [
            u for u in available_units
            if normalize_unit_type(u.unit_type) == normalize_unit_type(unit_type)
        ]
        ranked = rank_units_for_incident(candidates, incident, limit=quantity)

        for unit, score in ranked:
            eta = estimate_eta_minutes(unit, incident)
            km  = haversine_distance(
                unit.latitude or incident.latitude,
                unit.longitude or incident.longitude,
                incident.latitude, incident.longitude,
            )
            selected.append({
                "unit_id":      unit.id,
                "unit_type":    unit.unit_type,
                "designation":  unit.designation,
                "status":       unit.status,
                "distance_km":  round(km, 1),
                "eta_minutes":  round(eta, 0),
                "score":        round(score, 1),
                "priority":     priority,
                "reason":       req.get("rationale", ""),
            })
            # Remove from pool so unit isn't double-allocated
            available_units = [u for u in available_units if u.id != unit.id]

        shortfall = quantity - len(ranked)
        if shortfall > 0:
            shortage.append({
                "unit_type": unit_type,
                "shortfall": shortfall,
                "missing":   shortfall,
                "priority":  priority,
            })

    selected.sort(key=lambda x: (x["priority"] != "immediate", x["eta_minutes"]))

    # Pull confidence from the recommendation engine result
    confidence_label = rec.get("confidence", "low")
    confidence_score = rec.get("confidence_score", 0.5)

    return {
        "incident_id":      incident_id,
        "incident_name":    incident.name,
        "recommended_units": selected,
        "summary": {
            "total_selected": len(selected),
            "shortage_count":  sum(s["shortfall"] for s in shortage),
            "shortages":       shortage,
            "tactical_notes":  rec.get("tactical_notes", ""),
            "overall_risk":    rec.get("overall_risk", "unknown"),
            "confidence":      confidence_label,
            "confidence_score": confidence_score,
        },
    }
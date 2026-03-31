"""
unit_selection.py — Unit scoring and selection helpers.

PATCH: Replaced local haversine_distance with shared app.utils.geo.haversine_km.
       incident_dict construction now uses shared incident_to_dict() utility.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.unit import Unit
from app.services.routing import normalize_unit_type, is_ground_unit, is_air_unit
from app.utils.geo import haversine_km

logger = logging.getLogger(__name__)

# Keep the old name as an alias so callers outside this module aren't broken
haversine_distance = haversine_km

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
    if unit.latitude is None or unit.longitude is None:
        return 9999.0
    km = haversine_km(unit.latitude, unit.longitude, incident.latitude, incident.longitude)
    miles = km * 0.621371
    speed = UNIT_SPEED_MPH.get(normalize_unit_type(unit.unit_type), 40)
    return (miles / speed) * 60


def score_unit_for_incident(unit: Unit, incident: Incident) -> float:
    if unit.status == "out_of_service":
        return -1.0

    eta = estimate_eta_minutes(unit, incident)
    proximity_score = max(0.0, 100.0 - eta)

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

    if incident.structures_threatened and incident.structures_threatened > 0:
        if unit.has_structure_protection:
            capability_bonus += 10.0

    ics_bonus = 0.0
    ics_type  = (unit.ics_type or "").strip()
    severity  = (incident.severity or "low").lower()
    spread    = (incident.spread_risk or "low").lower()
    if ics_type:
        type_num = None
        for part in ics_type.split():
            try:
                type_num = int(part)
                break
            except ValueError:
                continue
        if type_num is not None:
            if severity in ("critical", "high") or spread in ("extreme", "high"):
                ics_bonus = max(0.0, (4 - type_num) * 8.0)
            else:
                ics_bonus = max(0.0, (4 - type_num) * 3.0)

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
    scored = [
        (u, score_unit_for_incident(u, incident))
        for u in units
        if u.status != "out_of_service"
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def incident_to_dict(incident: Incident, counts: dict) -> dict:
    """
    Canonical incident → dict conversion used by recommendation engine calls.
    Single source of truth — previously copy-pasted in 3 places (unit_selection,
    recommendations, intelligence), which caused aqi_category to be missing
    in the unit_selection version.
    """
    return {
        "id":                    incident.id,
        "name":                  incident.name,
        "fire_type":             incident.fire_type,
        "severity":              incident.severity,
        "status":                incident.status,
        "spread_risk":           incident.spread_risk,
        "spread_direction":      incident.spread_direction,
        "wind_speed_mph":        incident.wind_speed_mph,
        "humidity_percent":      incident.humidity_percent,
        "containment_percent":   incident.containment_percent,
        "structures_threatened": incident.structures_threatened,
        "acres_burned":          incident.acres_burned,
        "elevation_m":           incident.elevation_m,
        "slope_percent":         incident.slope_percent,
        "aspect_cardinal":       incident.aspect_cardinal,
        "aqi":                   incident.aqi,
        "aqi_category":          incident.aqi_category,
        "units_on_scene":        counts.get("on_scene", 0),
        "units_en_route":        counts.get("en_route", 0),
    }


def get_dispatch_recommendation(db: Session, incident_id: str) -> dict:
    from app.models.route import Route
    from app.intelligence.recommendation_engine import generate_recommendation

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise ValueError(f"Incident '{incident_id}' not found")

    from sqlalchemy import func
    counts = {
        "on_scene": db.query(func.count(Unit.id))
            .filter(Unit.assigned_incident_id == incident.id, Unit.status == "on_scene")
            .scalar() or 0,
        "en_route": db.query(func.count(Unit.id))
            .filter(Unit.assigned_incident_id == incident.id, Unit.status == "en_route")
            .scalar() or 0,
    }

    routes = db.query(Route).filter(Route.incident_id == incident.id).all()
    incident_dict = incident_to_dict(incident, counts)
    routes_list = [
        {
            "id": r.id, "label": r.label,
            "estimated_travel_minutes": r.estimated_travel_minutes,
            "terrain_accessibility": r.terrain_accessibility,
            "fire_exposure_risk": r.fire_exposure_risk,
            "safety_rating": r.safety_rating,
            "is_currently_passable": r.is_currently_passable,
            "notes": r.notes,
            "origin_lat": r.origin_lat, "origin_lon": r.origin_lon,
            "destination_lat": r.destination_lat, "destination_lon": r.destination_lon,
        }
        for r in routes
    ]
    rec = generate_recommendation(incident_dict, routes_list)
    needed: list[dict] = rec.get("unit_recommendations", rec.get("recommended_units", []))

    # Count units already assigned to this incident by type
    # so we don't recommend units the incident already has
    already_assigned = db.query(Unit).filter(
        Unit.assigned_incident_id == incident.id,
        Unit.status.in_(["en_route", "on_scene", "staging"]),
    ).all()
    already_by_type: dict[str, int] = {}
    for u in already_assigned:
        ntype = normalize_unit_type(u.unit_type)
        already_by_type[ntype] = already_by_type.get(ntype, 0) + 1

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

        ntype = normalize_unit_type(unit_type)
        already_count = already_by_type.get(ntype, 0)
        remaining_needed = max(0, quantity - already_count)

        if remaining_needed == 0:
            continue  # This type is fully covered — skip entirely

        candidates = [
            u for u in available_units
            if normalize_unit_type(u.unit_type) == ntype
        ]
        ranked = rank_units_for_incident(candidates, incident, limit=remaining_needed)

        for unit, score in ranked:
            eta = estimate_eta_minutes(unit, incident)
            km  = haversine_km(
                unit.latitude or incident.latitude,
                unit.longitude or incident.longitude,
                incident.latitude, incident.longitude,
            )
            selected.append({
                "unit_id":     unit.id,
                "unit_type":   unit.unit_type,
                "designation": unit.designation,
                "status":      unit.status,
                "distance_km": round(km, 1),
                "eta_minutes": round(eta, 0),
                "score":       round(score, 1),
                "priority":    priority,
                "reason":      req.get("rationale", ""),
            })
            available_units = [u for u in available_units if u.id != unit.id]

        shortfall = remaining_needed - len(ranked)
        if shortfall > 0:
            shortage.append({"unit_type": unit_type, "shortfall": shortfall,
                             "missing": shortfall, "priority": priority})

    selected.sort(key=lambda x: (x["priority"] != "immediate", x["eta_minutes"]))

    return {
        "incident_id":       incident_id,
        "incident_name":     incident.name,
        "recommended_units": selected,
        "summary": {
            "total_selected":   len(selected),
            "shortage_count":   sum(s["shortfall"] for s in shortage),
            "shortages":        shortage,
            "tactical_notes":   rec.get("tactical_notes", ""),
            "overall_risk":     rec.get("overall_risk", "unknown"),
            "confidence":       rec.get("confidence", "low"),
            "confidence_score": rec.get("confidence_score", 0.5),
        },
    }
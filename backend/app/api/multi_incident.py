"""
multi_incident.py — GET /api/multi-incident/priority

PATCH: _priority_score no longer fires a COUNT query per incident.
Unit counts are now batch-loaded in a single query before the scoring loop,
collapsing N DB round-trips to 1.
haversine_km consolidated to app.utils.geo.
"""
from __future__ import annotations

import math
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.incident import Incident
from app.models.unit import Unit
from app.models.user import User
from app.utils.geo import haversine_km

router = APIRouter(prefix="/api/multi-incident", tags=["Multi-Incident"])

SEVERITY_SCORE  = {"critical": 40, "high": 30, "moderate": 20, "low": 10}
SPREAD_SCORE    = {"extreme":  30, "high": 20, "moderate": 10, "low":  5}
FIRE_TYPE_BONUS = {"wildland_urban_interface": 10, "structure": 5, "wildland": 0}


def _priority_score(incident: Incident, on_scene: int) -> dict:
    """Compute a 0-100 priority score. on_scene is pre-fetched by the caller."""
    score = 0.0
    factors: list[str] = []

    sev = SEVERITY_SCORE.get((incident.severity or "low").lower(), 10)
    score += sev
    factors.append(f"severity={incident.severity}")

    spread = SPREAD_SCORE.get((incident.spread_risk or "low").lower(), 5)
    score += spread
    factors.append(f"spread={incident.spread_risk}")

    score += FIRE_TYPE_BONUS.get((incident.fire_type or "wildland").lower(), 0)

    structs = incident.structures_threatened or 0
    if structs > 0:
        struct_pts = min(20.0, 20.0 * math.log10(structs + 1) / math.log10(1001))
        score += struct_pts
        factors.append(f"structures={structs}")

    containment = incident.containment_percent or 0
    score += -(containment / 100.0) * 15

    if on_scene == 0:
        score += 10
        factors.append("no_resources_assigned")
    elif on_scene < 3:
        score += 5
        factors.append("few_resources")

    age_hrs = 0.0
    if incident.started_at:
        now = datetime.now(UTC)
        started = incident.started_at
        if started.tzinfo is None:
            from datetime import timezone
            started = started.replace(tzinfo=timezone.utc)
        age_hrs = (now - started).total_seconds() / 3600

    if age_hrs > 24:
        score -= 10
        factors.append("incident_age>24h")
    elif age_hrs > 12:
        score -= 5

    wind = incident.wind_speed_mph or 0
    humidity = incident.humidity_percent or 50
    if wind > 25 and humidity < 20:
        score += 10
        factors.append("extreme_fire_weather")
    elif wind > 15 or humidity < 30:
        score += 5

    final = max(0.0, min(100.0, score))
    return {
        "incident_id":           incident.id,
        "incident_name":         incident.name,
        "priority_score":        round(final, 1),
        "severity":              incident.severity,
        "spread_risk":           incident.spread_risk,
        "fire_type":             incident.fire_type,
        "status":                incident.status,
        "containment_percent":   incident.containment_percent,
        "structures_threatened": incident.structures_threatened,
        "units_assigned":        on_scene,
        "wind_speed_mph":        wind,
        "humidity_percent":      humidity,
        "age_hours":             round(age_hrs, 1),
        "priority_factors":      factors,
        "latitude":              incident.latitude,
        "longitude":             incident.longitude,
    }


def _recommend_allocation(ranked: list[dict], available_units: list[Unit]) -> list[dict]:
    allocations: list[dict] = []
    pool = list(available_units)

    for inc in ranked:
        if inc["units_assigned"] >= 5:
            continue
        need = max(0, 3 - inc["units_assigned"])
        if need == 0:
            continue
        assigned_here = 0
        for unit in pool[:]:
            if assigned_here >= need:
                break
            if unit.latitude is None or unit.longitude is None:
                continue
            dist_km = haversine_km(
                unit.latitude, unit.longitude,
                inc["latitude"], inc["longitude"],
            )
            if dist_km > 150:
                continue
            allocations.append({
                "incident_id":    inc["incident_id"],
                "incident_name":  inc["incident_name"],
                "priority_score": inc["priority_score"],
                "unit_id":        unit.id,
                "unit_type":      unit.unit_type,
                "designation":    unit.designation,
                "distance_km":    round(dist_km, 1),
                "rationale": (
                    f"Priority {inc['priority_score']:.0f} incident with only "
                    f"{inc['units_assigned']} unit(s) on scene. "
                    f"{unit.designation} is {dist_km:.1f} km away."
                ),
            })
            pool.remove(unit)
            assigned_here += 1

    return allocations


@router.get("/priority", summary="Rank all active incidents by priority and recommend resource allocation")
def get_multi_incident_priority(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    incidents = db.query(Incident).filter(
        Incident.status.in_(["active", "contained"])
    ).all()

    if not incidents:
        return {
            "ranked_incidents": [],
            "allocation_recommendations": [],
            "summary": {"total_incidents": 0, "critical": 0, "high": 0},
        }

    # Batch unit counts — 1 query instead of 1 per incident
    incident_ids = [i.id for i in incidents]
    on_scene_map = dict(
        db.query(Unit.assigned_incident_id, func.count(Unit.id))
        .filter(
            Unit.assigned_incident_id.in_(incident_ids),
            Unit.status.in_(["on_scene", "en_route", "staging"]),
        )
        .group_by(Unit.assigned_incident_id)
        .all()
    )

    ranked = [_priority_score(inc, on_scene_map.get(inc.id, 0)) for inc in incidents]
    ranked.sort(key=lambda x: -x["priority_score"])

    available_units = db.query(Unit).filter(
        Unit.status.in_(["available", "staging"]),
        Unit.assigned_incident_id.is_(None),
    ).all()

    allocations = _recommend_allocation(ranked, available_units)

    return {
        "ranked_incidents": ranked,
        "allocation_recommendations": allocations,
        "summary": {
            "total_incidents":  len(ranked),
            "critical":         sum(1 for i in ranked if i["severity"] == "critical"),
            "high":             sum(1 for i in ranked if i["severity"] == "high"),
            "available_units":  len(available_units),
            "allocation_count": len(allocations),
            "top_priority":     ranked[0]["incident_name"] if ranked else None,
        },
    }
"""
Recommendations API — live engine replacing previous mock data.

GET /api/recommendations/                      — list live recommendations for all active incidents
GET /api/recommendations/{id}                  — get recommendation for a specific incident
GET /api/recommendations/{id}/units            — unit selection: which specific units to dispatch
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.incident import Incident
from app.models.route import Route
from app.models.unit import Unit
from app.models.user import User
from app.intelligence.recommendation_engine import generate_recommendation
from app.services.unit_selection import get_dispatch_recommendation

router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"])


def _build_recommendation(incident: Incident, db: Session) -> dict:
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
        "units_on_scene":        counts["on_scene"],
        "units_en_route":        counts["en_route"],
    }

    routes_list = [
        {
            "id":                       r.id,
            "label":                    r.label,
            "estimated_travel_minutes": r.estimated_travel_minutes,
            "terrain_accessibility":    r.terrain_accessibility,
            "fire_exposure_risk":       r.fire_exposure_risk,
            "safety_rating":            r.safety_rating,
            "is_currently_passable":    r.is_currently_passable,
            "notes":                    r.notes,
            "origin_lat":               r.origin_lat,
            "origin_lon":               r.origin_lon,
            "destination_lat":          r.destination_lat,
            "destination_lon":          r.destination_lon,
        }
        for r in routes
    ]

    return generate_recommendation(incident_dict, routes_list)


@router.get("/", summary="List live recommendations for all active incidents")
def list_recommendations(
    incident_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    query = db.query(Incident).filter(Incident.status.in_(["active", "contained"]))
    if incident_id:
        query = query.filter(Incident.id == incident_id)

    incidents = query.all()
    return [_build_recommendation(inc, db) for inc in incidents]


@router.get("/{incident_id}", summary="Get live recommendation for an incident")
def get_recommendation(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    return _build_recommendation(incident, db)

@router.get("/{incident_id}/units", summary="Select best available units for an incident")
def get_unit_selection(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    """
    Dispatch Intelligence Engine — unit selection.

    Runs the recommendation engine to determine *what* unit types are needed,
    then selects *which* specific available units to send, ranked by distance.

    Returns:
    - recommended_units: ranked list with unit_id, type, distance_km, score, reason
    - summary: total selected, shortage count, tactical notes
    """
    try:
        result = get_dispatch_recommendation(db, incident_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return result

# ── Recommendation feedback ────────────────────────────────────────────────────

from pydantic import BaseModel as _BaseModel
from app.models.recommendation_feedback import RecommendationFeedback
import uuid as _uuid


class FeedbackRequest(_BaseModel):
    outcome: str                     # accepted | rejected | overridden
    override_unit_ids: list[str] = []
    reason: str = ""
    recommendation_id: str = ""
    confidence_reported: str = ""


@router.post("/{incident_id}/feedback", summary="Record dispatcher feedback on a recommendation")
def submit_feedback(
    incident_id: str,
    body: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    """
    Logs whether the dispatcher accepted, rejected, or overrode the AI recommendation.
    Overrides also capture the actual unit IDs dispatched.
    """
    valid_outcomes = {"accepted", "rejected", "overridden"}
    if body.outcome not in valid_outcomes:
        raise HTTPException(
            status_code=422,
            detail=f"outcome must be one of {sorted(valid_outcomes)}",
        )

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    fb = RecommendationFeedback(
        id=str(_uuid.uuid4()),
        incident_id=incident_id,
        recommendation_id=body.recommendation_id or None,
        actor=current_user.username,
        actor_role=current_user.role,
        outcome=body.outcome,
        override_unit_ids=",".join(body.override_unit_ids) if body.override_unit_ids else None,
        reason=body.reason or None,
        confidence_reported=body.confidence_reported or None,
        recorded_at=datetime.now(),
    )
    db.add(fb)
    db.commit()

    return {
        "feedback_id": fb.id,
        "incident_id": incident_id,
        "outcome":     body.outcome,
        "recorded_at": fb.recorded_at.isoformat(),
        "message":     f"Feedback recorded: {body.outcome}",
    }


@router.get("/{incident_id}/feedback", summary="List recommendation feedback for an incident")
def list_feedback(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    entries = (
        db.query(RecommendationFeedback)
        .filter(RecommendationFeedback.incident_id == incident_id)
        .order_by(RecommendationFeedback.recorded_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "feedback_id":        e.id,
            "outcome":            e.outcome,
            "actor":              e.actor,
            "actor_role":         e.actor_role,
            "reason":             e.reason,
            "override_unit_ids":  e.override_unit_ids.split(",") if e.override_unit_ids else [],
            "confidence_reported": e.confidence_reported,
            "recorded_at":        e.recorded_at.isoformat(),
        }
        for e in entries
    ]

"""
recommendations.py — Live recommendation engine API.

PATCHES
-------
1. Added TTL cache on list_recommendations / get_recommendation — the engine
   is purely rule-based so results are deterministic given the same incident
   state. Previously every poll rebuilt every recommendation with N DB queries.
   Cache keyed on (incident_id, incident.updated_at) so stale entries are
   automatically bypassed when incident state changes.
2. incident_dict construction consolidated to unit_selection.incident_to_dict —
   single source of truth, no more copy-paste drift.
3. recorded_at in submit_feedback now uses datetime.now(UTC) (was naive datetime.now()).
"""

import threading
import time

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from datetime import datetime, UTC

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.incident import Incident
from app.models.route import Route
from app.models.unit import Unit
from app.models.user import User
from app.intelligence.recommendation_engine import generate_recommendation
from app.services.unit_selection import get_dispatch_recommendation, incident_to_dict

router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"])

# ---------------------------------------------------------------------------
# In-process TTL cache keyed on (incident_id, updated_at_isoformat)
# ---------------------------------------------------------------------------
_rec_cache: dict[str, tuple[float, dict]] = {}
_rec_cache_lock = threading.Lock()
_REC_CACHE_TTL = 30.0   # seconds — short enough to stay fresh, long enough to absorb poll bursts
_REC_CACHE_MAX = 128


def _cache_key(incident: Incident) -> str:
    ts = incident.updated_at.isoformat() if incident.updated_at else "none"
    return f"{incident.id}:{ts}"


def _cache_get(key: str) -> dict | None:
    with _rec_cache_lock:
        entry = _rec_cache.get(key)
        if not entry:
            return None
        ts, result = entry
        if time.monotonic() - ts > _REC_CACHE_TTL:
            del _rec_cache[key]
            return None
        return result


def _cache_set(key: str, result: dict) -> None:
    with _rec_cache_lock:
        if len(_rec_cache) >= _REC_CACHE_MAX:
            oldest = min(_rec_cache, key=lambda k: _rec_cache[k][0])
            del _rec_cache[oldest]
        _rec_cache[key] = (time.monotonic(), result)


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------

def _build_recommendation(incident: Incident, db: Session) -> dict:
    key = _cache_key(incident)
    cached = _cache_get(key)
    if cached:
        return cached

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
    result = generate_recommendation(incident_dict, routes_list)
    _cache_set(key, result)
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", summary="List live recommendations for all active incidents")
def list_recommendations(
    incident_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    query = db.query(Incident).filter(Incident.status.in_(["active", "contained"]))
    if incident_id:
        query = query.filter(Incident.id == incident_id)
    return [_build_recommendation(inc, db) for inc in query.all()]


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
    try:
        return get_dispatch_recommendation(db, incident_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel
from app.models.recommendation_feedback import RecommendationFeedback
import uuid as _uuid


class FeedbackRequest(_BaseModel):
    outcome: str
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
    valid_outcomes = {"accepted", "rejected", "overridden"}
    if body.outcome not in valid_outcomes:
        raise HTTPException(status_code=422,
                            detail=f"outcome must be one of {sorted(valid_outcomes)}")

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
        recorded_at=datetime.now(UTC),   # FIX: was naive datetime.now()
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
            "feedback_id":         e.id,
            "outcome":             e.outcome,
            "actor":               e.actor,
            "actor_role":          e.actor_role,
            "reason":              e.reason,
            "override_unit_ids":   e.override_unit_ids.split(",") if e.override_unit_ids else [],
            "confidence_reported": e.confidence_reported,
            "recorded_at":         e.recorded_at.isoformat(),
        }
        for e in entries
    ]
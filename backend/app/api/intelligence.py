"""
intelligence.py — Intelligence layer API.

Endpoints:
  GET /api/intelligence/spread-risk/{id}      — terrain-aware spread cone (GeoJSON)
  GET /api/intelligence/fire-behavior/{id}    — fire behavior prediction
  GET /api/intelligence/risk-score/{id}       — composite risk score (0-100 + breakdown)
  GET /api/intelligence/recommendation/{id}   — full tactical recommendation
  GET /api/intelligence/alert-recommendation/{id} — alert-level recommendation
  GET /api/intelligence/unit-capabilities     — all unit type profiles
  GET /api/intelligence/unit-capabilities/{type} — single unit type profile
  GET /api/intelligence/summary/{id}          — full intelligence summary (aggregated)
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.incident import Incident
from app.models.alert import Alert
from app.models.route import Route
from app.models.unit import Unit
from app.models.user import User
from app.intelligence.spread_risk import generate_spread_cone
from app.intelligence.recommendation_engine import generate_recommendation
from app.intelligence.alert_recommendation import generate_alert_recommendation

from app.ext.fire_behavior import predict_fire_behavior, fire_behavior_index
from app.ext.composite_risk import compute_risk_score
from app.ext.unit_capabilities import get_profile, format_capability_summary, UNIT_PROFILES

router = APIRouter(prefix="/api/intelligence", tags=["Intelligence"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit_counts(db: Session, incident_id: str) -> dict:
    on_scene = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id, Unit.status == "on_scene"
    ).count()
    en_route = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id, Unit.status == "en_route"
    ).count()
    return {"on_scene": on_scene, "en_route": en_route}


def _incident_to_dict(incident: Incident, units: dict | None = None) -> dict:
    d = {
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
    }
    if units:
        d["units_on_scene"] = units["on_scene"]
        d["units_en_route"] = units["en_route"]
    return d


def _compute_fbi_and_score(incident: Incident, counts: dict) -> tuple[float, dict]:
    """Compute fire behavior index and composite risk score. Returns (fbi, score_dict)."""
    fbi = fire_behavior_index(
        wind_speed_mph   = incident.wind_speed_mph,
        humidity_percent = incident.humidity_percent,
        spread_risk      = incident.spread_risk,
        slope_percent    = incident.slope_percent,
        aqi              = incident.aqi,
    )
    score = compute_risk_score(
        fire_behavior_index   = fbi,
        spread_risk           = incident.spread_risk,
        severity              = incident.severity,
        structures_threatened = incident.structures_threatened,
        containment_percent   = incident.containment_percent,
        acres_burned          = incident.acres_burned,
        slope_percent         = incident.slope_percent,
        aspect_cardinal       = incident.aspect_cardinal,
        spread_direction      = incident.spread_direction,
        units_on_scene        = counts["on_scene"],
        units_en_route        = counts["en_route"],
    )
    return fbi, score


# ---------------------------------------------------------------------------
# Spread Risk
# ---------------------------------------------------------------------------

@router.get("/spread-risk/{incident_id}", summary="Get terrain-adjusted spread risk cone (GeoJSON)")
def get_spread_risk(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    """
    Returns a GeoJSON Feature (Polygon) representing the fire spread cone.
    Properties include risk_score (0-100), terrain_adjusted_risk, radius_km.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    return generate_spread_cone(
        latitude         = incident.latitude,
        longitude        = incident.longitude,
        spread_risk      = incident.spread_risk,
        spread_direction = incident.spread_direction,
        wind_speed_mph   = incident.wind_speed_mph,
        humidity_percent = incident.humidity_percent,
        slope_percent    = incident.slope_percent,
        aspect_cardinal  = incident.aspect_cardinal,
    )


# ---------------------------------------------------------------------------
# Fire Behavior Prediction
# ---------------------------------------------------------------------------

@router.get("/fire-behavior/{incident_id}", summary="Get fire behavior prediction")
def get_fire_behavior(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    counts = _unit_counts(db, incident_id)

    prediction = predict_fire_behavior(
        fire_type           = incident.fire_type,
        spread_risk         = incident.spread_risk,
        wind_speed_mph      = incident.wind_speed_mph,
        humidity_percent    = incident.humidity_percent,
        containment_percent = incident.containment_percent,
        acres_burned        = incident.acres_burned,
        units_on_scene      = counts["on_scene"],
        slope_percent       = incident.slope_percent,
        aqi                 = incident.aqi,
    )

    return {
        "incident_id":   incident_id,
        "incident_name": incident.name,
        **prediction,
        "data_quality": {
            "has_terrain":    incident.slope_percent is not None,
            "has_weather":    incident.wind_speed_mph is not None,
            "has_aqi":        incident.aqi is not None,
            "units_on_scene": counts["on_scene"],
        },
    }


# ---------------------------------------------------------------------------
# Composite Risk Score (0-100)
# ---------------------------------------------------------------------------

@router.get("/risk-score/{incident_id}", summary="Get composite risk score (0-100 + breakdown)")
def get_risk_score(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    """
    Returns a composite risk score (0-100) combining fire behavior, spread risk,
    severity, structures threatened, terrain, containment, and resource factors.

    Also returns risk_level (low/moderate/high/extreme) and a factor breakdown
    for transparency.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    counts = _unit_counts(db, incident_id)
    fbi, score = _compute_fbi_and_score(incident, counts)

    # Normalize 0-1 score to 0-100 integer for frontend
    risk_score_100 = round(score["risk_score"] * 100)

    return {
        "incident_id":    incident_id,
        "incident_name":  incident.name,
        "risk_score":     risk_score_100,       # 0-100 integer
        "risk_score_raw": score["risk_score"],  # 0.0-1.0 float (for calculations)
        "risk_level":     score["risk_level"],
        "drivers":        score["drivers"],
        "fire_behavior_index": fbi,
        "data_completeness": {
            "has_weather":  incident.wind_speed_mph is not None,
            "has_terrain":  incident.slope_percent is not None,
            "has_aqi":      incident.aqi is not None,
        },
    }


# ---------------------------------------------------------------------------
# Recommendation Engine
# ---------------------------------------------------------------------------

@router.get("/recommendation/{incident_id}", summary="Get full tactical recommendation")
def get_recommendation(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    counts     = _unit_counts(db, incident_id)
    routes     = db.query(Route).filter(Route.incident_id == incident_id).all()
    inc_dict   = _incident_to_dict(incident, counts)

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

    return generate_recommendation(inc_dict, routes_list)


# ---------------------------------------------------------------------------
# Alert Recommendation
# ---------------------------------------------------------------------------

@router.get("/alert-recommendation/{alert_id}", summary="Get tactical recommendation for an alert")
def get_alert_recommendation(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found")

    incident_dict = None
    if alert.incident_id:
        incident = db.query(Incident).filter(Incident.id == alert.incident_id).first()
        if incident:
            counts = _unit_counts(db, alert.incident_id)
            incident_dict = {
                "wind_speed_mph":        incident.wind_speed_mph,
                "humidity_percent":      incident.humidity_percent,
                "containment_percent":   incident.containment_percent,
                "structures_threatened": incident.structures_threatened,
                "spread_risk":           incident.spread_risk,
                "slope_percent":         incident.slope_percent,
                "aqi":                   incident.aqi,
                "units_on_scene":        counts["on_scene"],
            }

    rec = generate_alert_recommendation(
        alert_type  = alert.alert_type,
        severity    = alert.severity,
        alert_title = alert.title,
        incident    = incident_dict,
    )

    return {
        "alert_id":   alert_id,
        "alert_type": alert.alert_type,
        "severity":   alert.severity,
        "title":      alert.title,
        **rec,
    }


# ---------------------------------------------------------------------------
# Unit Capabilities
# ---------------------------------------------------------------------------

@router.get("/unit-capabilities", summary="Get capability profiles for all unit types")
def get_all_capabilities(
    current_user: User = Depends(require_any_role),
):
    return {
        unit_type: {
            **profile,
            "capability_summary": format_capability_summary(unit_type),
        }
        for unit_type, profile in UNIT_PROFILES.items()
    }


@router.get("/unit-capabilities/{unit_type}", summary="Get capability profile for a unit type")
def get_unit_capability(
    unit_type: str,
    current_user: User = Depends(require_any_role),
):
    profile = get_profile(unit_type)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Unknown unit type: {unit_type}")
    return {
        **profile,
        "unit_type":          unit_type,
        "capability_summary": format_capability_summary(unit_type),
    }


# ---------------------------------------------------------------------------
# Full Intelligence Summary (aggregated — single call for frontend)
# ---------------------------------------------------------------------------

@router.get("/summary/{incident_id}", summary="Full intelligence summary for an incident")
def get_summary(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    """
    Aggregates all intelligence signals into a single response:
      - Composite risk score (0-100)
      - Spread risk cone (GeoJSON)
      - Fire behavior prediction
      - Tactical recommendation
      - Data completeness indicators

    Designed for the frontend dashboard — replaces 4 separate API calls.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    counts   = _unit_counts(db, incident_id)
    routes   = db.query(Route).filter(Route.incident_id == incident_id).all()
    inc_dict = _incident_to_dict(incident, counts)

    # Fire behavior
    prediction = predict_fire_behavior(
        fire_type           = incident.fire_type,
        spread_risk         = incident.spread_risk,
        wind_speed_mph      = incident.wind_speed_mph,
        humidity_percent    = incident.humidity_percent,
        containment_percent = incident.containment_percent,
        acres_burned        = incident.acres_burned,
        units_on_scene      = counts["on_scene"],
        slope_percent       = incident.slope_percent,
        aqi                 = incident.aqi,
    )

    # Composite risk
    fbi, score = _compute_fbi_and_score(incident, counts)
    risk_score_100 = round(score["risk_score"] * 100)

    # Spread cone
    spread_cone = generate_spread_cone(
        latitude         = incident.latitude,
        longitude        = incident.longitude,
        spread_risk      = incident.spread_risk,
        spread_direction = incident.spread_direction,
        wind_speed_mph   = incident.wind_speed_mph,
        humidity_percent = incident.humidity_percent,
        slope_percent    = incident.slope_percent,
        aspect_cardinal  = incident.aspect_cardinal,
    )

    # Tactical recommendation
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
    recommendation = generate_recommendation(inc_dict, routes_list)

    data_quality = {
        "has_weather":  incident.wind_speed_mph is not None,
        "has_humidity": incident.humidity_percent is not None,
        "has_terrain":  incident.slope_percent is not None,
        "has_aqi":      incident.aqi is not None,
        "units_on_scene": counts["on_scene"],
        "units_en_route": counts["en_route"],
    }

    return {
        "incident_id":   incident_id,
        "incident_name": incident.name,
        "generated_at":  recommendation["generated_at"],

        # Core intelligence signals
        "risk_score":         risk_score_100,
        "risk_level":         score["risk_level"],
        "risk_drivers":       score["drivers"],
        "fire_behavior_index": round(fbi, 3),

        # Fire behavior prediction
        "fire_behavior": prediction,

        # Spread risk cone (GeoJSON) — ready for map overlay
        "spread_cone": spread_cone,

        # Tactical recommendation
        "recommendation": {
            "loadout_profile":      recommendation["loadout_profile"],
            "confidence":           recommendation["confidence"],
            "confidence_score":     recommendation["confidence_score"],
            "summary":              recommendation["summary"],
            "unit_recommendations": recommendation["unit_recommendations"],
            "tactical_notes":       recommendation["tactical_notes"],
            "route_options":        recommendation["route_options"],
        },

        # Data completeness
        "data_quality": data_quality,
    }
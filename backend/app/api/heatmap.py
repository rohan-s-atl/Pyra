"""
heatmap.py — Risk heatmap using composite risk scoring.

PATCH: Replaced N unit COUNT queries per incident with two batch queries
(one for on_scene, one for en_route), collapsing N+1 to 2 regardless of
how many active incidents exist.
"""
import math
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.incident import Incident
from app.models.unit import Unit
from app.models.user import User

from app.ext.fire_behavior import fire_behavior_index
from app.ext.composite_risk import compute_risk_score

router = APIRouter(prefix="/api/heatmap", tags=["Heatmap"])

LAT_MIN, LAT_MAX = 32.5, 42.0
LON_MIN, LON_MAX = -124.5, -114.0
GRID_STEP = 0.35   # ~38 km cells


def _influence_at(grid_lat, grid_lon, inc_lat, inc_lon, score, radius_deg=1.8):
    dlat = grid_lat - inc_lat
    dlon = (grid_lon - inc_lon) * math.cos(math.radians(inc_lat))
    dist = math.sqrt(dlat**2 + dlon**2)
    if dist > radius_deg:
        return 0.0
    return score * math.exp(-(dist**2) / (2 * (radius_deg / 2)**2))


@router.get("/", summary="Get composite risk heatmap grid for California")
def get_heatmap(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    incidents = db.query(Incident).filter(
        Incident.status.in_(["active", "contained"])
    ).all()

    if not incidents:
        return {"points": [], "max_score": 0, "incident_count": 0}

    # Batch-load unit counts — 2 queries total regardless of incident count
    incident_ids = [i.id for i in incidents]

    on_scene_counts = dict(
        db.query(Unit.assigned_incident_id, func.count(Unit.id))
        .filter(Unit.assigned_incident_id.in_(incident_ids), Unit.status == "on_scene")
        .group_by(Unit.assigned_incident_id)
        .all()
    )
    en_route_counts = dict(
        db.query(Unit.assigned_incident_id, func.count(Unit.id))
        .filter(Unit.assigned_incident_id.in_(incident_ids), Unit.status == "en_route")
        .group_by(Unit.assigned_incident_id)
        .all()
    )

    scored = []
    for inc in incidents:
        on_scene = on_scene_counts.get(inc.id, 0)
        en_route = en_route_counts.get(inc.id, 0)

        fbi = fire_behavior_index(
            wind_speed_mph   = inc.wind_speed_mph,
            humidity_percent = inc.humidity_percent,
            spread_risk      = inc.spread_risk,
            slope_percent    = inc.slope_percent,
            aqi              = inc.aqi,
        )
        result = compute_risk_score(
            fire_behavior_index   = fbi,
            spread_risk           = inc.spread_risk,
            severity              = inc.severity,
            structures_threatened = inc.structures_threatened,
            containment_percent   = inc.containment_percent,
            acres_burned          = inc.acres_burned,
            slope_percent         = inc.slope_percent,
            aspect_cardinal       = inc.aspect_cardinal,
            spread_direction      = inc.spread_direction,
            units_on_scene        = on_scene,
            units_en_route        = en_route,
        )
        scored.append((inc.latitude, inc.longitude, result["risk_score"]))

    points = []
    lat = LAT_MIN
    while lat <= LAT_MAX:
        lon = LON_MIN
        while lon <= LON_MAX:
            total = sum(
                _influence_at(lat, lon, ilat, ilon, iscore)
                for ilat, ilon, iscore in scored
            )
            total = min(total, 1.0)
            if total > 0.05:
                points.append({"lat": round(lat, 3), "lon": round(lon, 3), "score": round(total, 3)})
            lon = round(lon + GRID_STEP, 6)
        lat = round(lat + GRID_STEP, 6)

    max_score = max((p["score"] for p in points), default=0)
    return {
        "points":         points,
        "max_score":      max_score,
        "incident_count": len(incidents),
        "scoring_model":  "composite_risk_v2",
    }
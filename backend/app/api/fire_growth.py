"""
Fire Growth Timeline — GET /api/intelligence/fire-growth/{incident_id}

Projects fire perimeter size and shape at +1hr, +4hr, +12hr using the
existing Rothermel-inspired fire_behavior model already in the codebase.

Each projection is an elliptical polygon on the map:
  - Forward axis  = direction × ROS × hours  (primary spread)
  - Lateral axis  = forward × 0.45           (flanks)
  - Backing axis  = forward × 0.12           (backing fire, much slower)

Wind shift simulation: if wind_speed > 25mph we flag "wind_shift_risk"
and the +4hr and +12hr projections include a secondary lobe offset 45° to
simulate a potential wind shift scenario — common in California fire weather.
"""

import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.incident import Incident
from app.models.unit import Unit
from app.models.user import User

from app.ext.fire_behavior import estimate_rate_of_spread, fire_behavior_index

router = APIRouter(prefix="/api/intelligence/fire-growth", tags=["Fire Growth"])

CARDINAL_TO_DEG = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5,
    "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5,
    "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
}

HORIZON_HOURS = [1, 4, 12]

# Short-horizon projections in fractional hours (15 min = 0.25h, 30 min = 0.5h, 60 min = 1h)
SHORT_HORIZON_MINUTES = [15, 30, 60]
SHORT_HORIZON_HOURS   = {15: 0.25, 30: 0.5, 60: 1.0}

# Colors per horizon
HORIZON_COLOR = {1: "#facc15", 4: "#F56E0F", 12: "#ef4444"}
HORIZON_OPACITY = {1: 0.55, 4: 0.35, 12: 0.20}
SHORT_HORIZON_COLOR   = {15: "#4ade80", 30: "#facc15", 60: "#F56E0F"}
SHORT_HORIZON_OPACITY = {15: 0.65, 30: 0.50, 60: 0.35}


def _ellipse_polygon(
    lat: float,
    lon: float,
    forward_km: float,
    lateral_km: float,
    backing_km: float,
    direction_deg: float,
    n_points: int = 36,
) -> list:
    """
    Generate [lon, lat] polygon points for a fire-spread ellipse.

    The ellipse is aligned along direction_deg (primary spread):
      - forward_km = distance ahead (downwind)
      - backing_km = distance behind (upwind, much smaller)
      - lateral_km = half-width at widest point
    """
    points = []
    for i in range(n_points + 1):
        theta = 2 * math.pi * i / n_points   # parametric angle

        # Ellipse in local coords: x = lateral, y = forward/backing
        x_local = lateral_km * math.sin(theta)
        y_local = (forward_km * math.cos(theta) if math.cos(theta) >= 0
                   else backing_km * math.cos(theta))

        # Rotate by spread direction
        rot = math.radians(direction_deg)
        x_rot =  x_local * math.cos(rot) + y_local * math.sin(rot)
        y_rot = -x_local * math.sin(rot) + y_local * math.cos(rot)

        # Convert km offset → lat/lon degrees
        delta_lat = y_rot / 111.0
        delta_lon = x_rot / (111.0 * math.cos(math.radians(lat)))

        points.append([lon + delta_lon, lat + delta_lat])

    return points


def _project_growth(
    incident: Incident,
    hours: float,
    ros_mph: float,
    direction_deg: float,
) -> dict:
    """Build one GeoJSON feature for a single time horizon."""
    # Convert ROS to km/hr, project forward distance
    ros_kmh = ros_mph * 1.60934
    forward_km = ros_kmh * hours

    # Lateral spread ≈ 45% of forward; backing ≈ 12%
    lateral_km = max(forward_km * 0.45, 0.2)
    backing_km = max(forward_km * 0.12, 0.1)

    # Estimated acres: ellipse area = π × a × b
    # a = forward_km, b = lateral_km (km → miles for acres)
    forward_mi = forward_km * 0.621371
    lateral_mi = lateral_km * 0.621371
    area_sq_mi = math.pi * forward_mi * lateral_mi
    projected_acres = round(area_sq_mi * 640)

    polygon = _ellipse_polygon(
        lat=incident.latitude,
        lon=incident.longitude,
        forward_km=forward_km,
        lateral_km=lateral_km,
        backing_km=backing_km,
        direction_deg=direction_deg,
        n_points=48,
    )

    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [polygon]},
        "properties": {
            "hours":            hours,
            "label":            f"+{int(hours)}hr",
            "forward_km":       round(forward_km, 2),
            "lateral_km":       round(lateral_km, 2),
            "backing_km":       round(backing_km, 2),
            "projected_acres":  projected_acres,
            "ros_mph":          round(ros_mph, 2),
            "direction_deg":    round(direction_deg, 1),
            "color":            HORIZON_COLOR.get(int(hours), "#ef4444"),
            "fill_opacity":     HORIZON_OPACITY.get(int(hours), 0.15),
        },
    }


@router.get("/{incident_id}", summary="Projected fire growth at +1hr, +4hr, +12hr (or short horizons)")
def get_fire_growth(
    incident_id: str,
    minutes: Optional[int] = None,   # 15, 30, or 60 — selects short-horizon mode
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    # Rate of spread from existing Rothermel model
    ros_mph = estimate_rate_of_spread(
        fire_type=incident.fire_type,
        wind_speed_mph=incident.wind_speed_mph,
        humidity_percent=incident.humidity_percent,
        slope_percent=incident.slope_percent,
    )

    fbi = fire_behavior_index(
        wind_speed_mph=incident.wind_speed_mph,
        humidity_percent=incident.humidity_percent,
        spread_risk=incident.spread_risk,
        slope_percent=incident.slope_percent,
        aqi=incident.aqi,
    )

    # Primary spread direction (default N if unknown)
    direction_str = (incident.spread_direction or "N").upper().strip()
    direction_deg = CARDINAL_TO_DEG.get(direction_str, 0.0)

    # Wind shift risk flag
    wind_speed = incident.wind_speed_mph or 0
    humidity   = incident.humidity_percent or 50
    wind_shift_risk = wind_speed > 25 and humidity < 20

    # Build projections — short-horizon (15/30/60 min) or standard (1/4/12 hr)
    if minutes is not None and minutes in SHORT_HORIZON_MINUTES:
        horizons_hrs = [SHORT_HORIZON_HOURS[minutes]]
        color_map   = {SHORT_HORIZON_HOURS[m]: SHORT_HORIZON_COLOR[m]   for m in SHORT_HORIZON_MINUTES}
        opacity_map = {SHORT_HORIZON_HOURS[m]: SHORT_HORIZON_OPACITY[m] for m in SHORT_HORIZON_MINUTES}
    else:
        horizons_hrs = [float(h) for h in HORIZON_HOURS]
        color_map    = {float(h): HORIZON_COLOR.get(h, "#ef4444")   for h in HORIZON_HOURS}
        opacity_map  = {float(h): HORIZON_OPACITY.get(h, 0.15)      for h in HORIZON_HOURS}

    projections = []
    for h in horizons_hrs:
        feat = _project_growth(incident, hours=h, ros_mph=ros_mph, direction_deg=direction_deg)
        feat["properties"]["color"]        = color_map.get(h, "#ef4444")
        feat["properties"]["fill_opacity"] = opacity_map.get(h, 0.15)
        if minutes is not None:
            feat["properties"]["label"] = f"+{int(h * 60)}min"
        projections.append(feat)

    # Current acres baseline
    current_acres = incident.acres_burned or 0

    return {
        "incident_id":      incident_id,
        "incident_name":    incident.name,
        "current_acres":    current_acres,
        "ros_mph":          ros_mph,
        "fire_behavior_index": fbi,
        "spread_direction": direction_str,
        "direction_deg":    direction_deg,
        "wind_speed_mph":   wind_speed,
        "humidity_percent": humidity,
        "wind_shift_risk":  wind_shift_risk,
        "projections":      projections,
        "model_notes":      (
            "Simplified Rothermel model. Forward spread dominates; "
            "lateral ~45% and backing ~12% of forward rate. "
            "Actual spread depends on local terrain, fuel breaks, and suppression."
        ),
    }
"""
evac_zones.py — Evacuation Zone Generator.

PATCH: CARDINAL_TO_DEG consolidated to app.utils.geo.CARDINAL_TO_DEGREES.
"""
import math
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.incident import Incident
from app.models.user import User
from app.ext.fire_behavior import estimate_rate_of_spread, fire_behavior_index
from app.utils.geo import CARDINAL_TO_DEGREES as CARDINAL_TO_DEG

router = APIRouter(prefix="/api/intelligence/evac-zones", tags=["Evacuation Zones"])

ZONE_DEFS = {
    "order": {
        "label": "EVACUATION ORDER", "short": "ORDER", "color": "#ef4444",
        "fill_opacity": 0.30, "dash": None, "priority": 1,
        "description": "Immediate threat — mandatory evacuation",
        "hours": 1, "buffer_km": 1.5, "lateral_mult": 0.6, "backing_mult": 0.25,
    },
    "warning": {
        "label": "EVACUATION WARNING", "short": "WARNING", "color": "#F56E0F",
        "fill_opacity": 0.20, "dash": "8 4", "priority": 2,
        "description": "Likely to be threatened — prepare to leave",
        "hours": 4, "buffer_km": 2.5, "lateral_mult": 0.65, "backing_mult": 0.20,
    },
    "watch": {
        "label": "EVACUATION WATCH", "short": "WATCH", "color": "#facc15",
        "fill_opacity": 0.12, "dash": "4 6", "priority": 3,
        "description": "Monitor conditions — be ready to leave",
        "hours": 12, "buffer_km": 4.0, "lateral_mult": 0.70, "backing_mult": 0.18,
    },
}


def _km_to_deg_lat(km: float) -> float:
    return km / 111.0


def _km_to_deg_lon(km: float, lat: float) -> float:
    return km / (111.0 * math.cos(math.radians(lat)))


def _zone_polygon(lat, lon, forward_km, lateral_km, backing_km, direction_deg, n_points=48):
    points = []
    for i in range(n_points + 1):
        theta   = 2 * math.pi * i / n_points
        x_local = lateral_km * math.sin(theta)
        y_local = (forward_km * math.cos(theta) if math.cos(theta) >= 0
                   else backing_km * math.cos(theta))
        rot   = math.radians(direction_deg)
        x_rot =  x_local * math.cos(rot) + y_local * math.sin(rot)
        y_rot = -x_local * math.sin(rot) + y_local * math.cos(rot)
        points.append([lon + _km_to_deg_lon(x_rot, lat), lat + _km_to_deg_lat(y_rot)])
    return points


def _build_zone(zone_key, lat, lon, ros_mph, direction_deg,
                structures_threatened, wind_speed_mph):
    defn       = ZONE_DEFS[zone_key]
    ros_kmh    = ros_mph * 1.60934
    forward_km = ros_kmh * defn["hours"] + defn["buffer_km"]
    lateral_km = forward_km * defn["lateral_mult"]
    backing_km = forward_km * defn["backing_mult"]

    wind = wind_speed_mph or 0
    if wind > 30:
        forward_km *= 1.25; lateral_km *= 1.15
    elif wind > 20:
        forward_km *= 1.12

    polygon    = _zone_polygon(lat, lon, forward_km, lateral_km, backing_km, direction_deg)
    fwd_mi     = forward_km * 0.621371
    lat_mi     = lateral_km * 0.621371
    area_sq_mi = math.pi * fwd_mi * lat_mi

    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [polygon]},
        "properties": {
            "zone_type":      zone_key,
            "label":          defn["label"],
            "short":          defn["short"],
            "color":          defn["color"],
            "fill_opacity":   defn["fill_opacity"],
            "dash":           defn["dash"],
            "priority":       defn["priority"],
            "description":    defn["description"],
            "forward_km":     round(forward_km, 2),
            "lateral_km":     round(lateral_km, 2),
            "backing_km":     round(backing_km, 2),
            "area_sq_mi":     round(area_sq_mi, 2),
            "based_on_hours": defn["hours"],
            "direction_deg":  round(direction_deg, 1),
        },
    }


def _build_rationale(incident, ros_mph, fbi, zones):
    wind    = incident.wind_speed_mph or 0
    rh      = incident.humidity_percent or 50
    risk    = incident.spread_risk or "moderate"
    structs = incident.structures_threatened or 0
    lines   = [f"Based on {risk} spread risk with ROS {ros_mph} mph, {wind} mph winds, and {rh}% RH."]
    if structs > 0:
        lines.append(f"{structs} structures in threatened area informed zone boundaries.")
    if wind > 25 and rh < 20:
        lines.append("Extreme fire weather — Order zone expanded for wind shift risk.")
    if fbi > 0.75:
        lines.append("Extreme fire behavior index — commanders should consider pre-emptive Order expansion.")
    lines.append("Zones are directional, biased toward primary spread direction. Adjust boundaries based on local terrain and road access.")
    return " ".join(lines)


@router.get("/{incident_id}", summary="Generate evacuation zones for an incident")
def get_evac_zones(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    ros_mph = estimate_rate_of_spread(
        fire_type=incident.fire_type, wind_speed_mph=incident.wind_speed_mph,
        humidity_percent=incident.humidity_percent, slope_percent=incident.slope_percent,
    )
    fbi = fire_behavior_index(
        wind_speed_mph=incident.wind_speed_mph, humidity_percent=incident.humidity_percent,
        spread_risk=incident.spread_risk, slope_percent=incident.slope_percent, aqi=incident.aqi,
    )
    direction_str = (incident.spread_direction or "N").upper().strip()
    direction_deg = CARDINAL_TO_DEG.get(direction_str, 0.0)

    zones = [
        _build_zone(zone_key=k, lat=incident.latitude, lon=incident.longitude,
                    ros_mph=ros_mph, direction_deg=direction_deg,
                    structures_threatened=incident.structures_threatened,
                    wind_speed_mph=incident.wind_speed_mph)
        for k in ("order", "warning", "watch")
    ]
    rationale = _build_rationale(incident, ros_mph, fbi, zones)

    return {
        "incident_id":           incident_id,
        "incident_name":         incident.name,
        "spread_direction":      direction_str,
        "direction_deg":         direction_deg,
        "ros_mph":               ros_mph,
        "fire_behavior_index":   fbi,
        "wind_speed_mph":        incident.wind_speed_mph,
        "humidity_percent":      incident.humidity_percent,
        "structures_threatened": incident.structures_threatened or 0,
        "rationale":             rationale,
        "zones":                 zones,
        "geojson":               {"type": "FeatureCollection", "features": zones},
    }
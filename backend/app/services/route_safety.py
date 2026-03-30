"""
route_safety.py — Route safety scoring service.

PATCH: Replaced local _haversine_km with shared app.utils.geo.haversine_km.
       Replaced local CARDINAL_TO_DEGREES with shared version.
"""
from __future__ import annotations

import math
from typing import Optional

from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.route import Route
from app.utils.geo import haversine_km, CARDINAL_TO_DEGREES

SPREAD_RADIUS_KM = {
    "extreme": 25.0,
    "high":    15.0,
    "moderate": 8.0,
    "low":      3.0,
}

CONE_HALF_ANGLE = {
    "extreme": 60, "high": 50, "moderate": 40, "low": 30,
}

EXPOSURE_DEDUCTIONS = {"low": 0, "moderate": -20, "high": -40, "extreme": -60}
ACCESS_DEDUCTIONS   = {"good": 0, "limited": -15, "poor": -30}


def _point_in_spread_cone(
    pt_lat: float, pt_lon: float,
    fire_lat: float, fire_lon: float,
    spread_risk: str,
    spread_direction: Optional[str],
    wind_speed_mph: Optional[float] = None,
) -> bool:
    risk     = (spread_risk or "moderate").lower()
    radius   = SPREAD_RADIUS_KM.get(risk, 8.0)
    half_ang = CONE_HALF_ANGLE.get(risk, 40)

    if wind_speed_mph and wind_speed_mph > 0:
        radius *= min(2.0, 1.0 + wind_speed_mph / 30.0)

    dist_km = haversine_km(fire_lat, fire_lon, pt_lat, pt_lon)
    if dist_km > radius:
        return False

    dir_deg = CARDINAL_TO_DEGREES.get((spread_direction or "N").upper(), 0)
    d_lat = pt_lat - fire_lat
    d_lon = (pt_lon - fire_lon) * math.cos(math.radians(fire_lat))
    bearing = math.degrees(math.atan2(d_lon, d_lat)) % 360
    diff = abs(bearing - dir_deg) % 360
    if diff > 180:
        diff = 360 - diff
    return diff <= half_ang


def score_route(
    route: Route,
    active_incidents: list[Incident],
    hotspots: Optional[list[dict]] = None,
) -> dict:
    score = 100.0
    risk_factors: list[str] = []

    exposure = (route.fire_exposure_risk or "low").lower()
    access   = (route.terrain_accessibility or "good").lower()

    score += EXPOSURE_DEDUCTIONS.get(exposure, 0)
    score += ACCESS_DEDUCTIONS.get(access, 0)

    if exposure in ("high", "extreme"):
        risk_factors.append(f"High fire exposure risk ({exposure})")
    if access == "poor":
        risk_factors.append("Poor terrain accessibility")
    if not route.is_currently_passable:
        score -= 60
        risk_factors.append("Route currently impassable")

    for incident in active_incidents:
        if incident.spread_risk is None:
            continue
        for pt_lat, pt_lon, label in [
            (route.origin_lat,      route.origin_lon,      "origin"),
            (route.destination_lat, route.destination_lon, "destination"),
        ]:
            if pt_lat is None or pt_lon is None:
                continue
            in_cone = _point_in_spread_cone(
                pt_lat, pt_lon,
                incident.latitude, incident.longitude,
                incident.spread_risk,
                incident.spread_direction,
                incident.wind_speed_mph,
            )
            if in_cone:
                risk    = (incident.spread_risk or "moderate").lower()
                deduct  = {"extreme": 50, "high": 35, "moderate": 20, "low": 10}.get(risk, 20)
                score  -= deduct
                risk_factors.append(f"Route {label} in {risk} fire spread zone ({incident.name})")

        if route.origin_lat and route.destination_lat:
            mid_lat = (route.origin_lat + route.destination_lat) / 2
            mid_lon = (route.origin_lon + route.destination_lon) / 2
            dist_to_fire = haversine_km(mid_lat, mid_lon, incident.latitude, incident.longitude)
            if dist_to_fire < 1.5:
                score -= 30
                risk_factors.append(f"Route midpoint within 1.5 km of fire origin ({incident.name})")
            elif dist_to_fire < 3.0:
                score -= 15
                risk_factors.append(f"Route midpoint within 3 km of fire origin ({incident.name})")

    if hotspots:
        for hs in hotspots:
            hs_lat = hs.get("latitude") or hs.get("lat")
            hs_lon = hs.get("longitude") or hs.get("lon")
            if hs_lat is None or hs_lon is None or route.origin_lat is None:
                continue
            min_dist = min(
                haversine_km(route.origin_lat, route.origin_lon, hs_lat, hs_lon),
                haversine_km(route.destination_lat, route.destination_lon, hs_lat, hs_lon),
            )
            if min_dist < 1.0:
                score -= 25
                risk_factors.append("Active hotspot within 1 km of route")
                break
            elif min_dist < 2.0:
                score -= 12
                risk_factors.append("Active hotspot within 2 km of route")
                break

    score = max(0.0, min(100.0, score))
    if score >= 70:
        status = "safe"
    elif score >= 40:
        status = "risky"
    else:
        status = "blocked"

    if not risk_factors:
        explanation = "No significant hazards detected on this route."
    else:
        explanation = "; ".join(risk_factors[:3])
        if len(risk_factors) > 3:
            explanation += f" (+{len(risk_factors) - 3} more)"

    return {
        "route_id":     route.id,
        "label":        route.label,
        "safety_score": round(score, 1),
        "status":       status,
        "risk_factors": risk_factors,
        "explanation":  explanation,
        "is_passable":  route.is_currently_passable,
    }


def score_all_routes(
    db: Session,
    incident_id: str,
    hotspots: Optional[list[dict]] = None,
) -> list[dict]:
    routes = db.query(Route).filter(Route.incident_id == incident_id).all()
    active_incidents = db.query(Incident).filter(
        Incident.status.in_(["active", "contained"])
    ).all()
    scored = [score_route(r, active_incidents, hotspots) for r in routes]
    scored.sort(key=lambda x: -x["safety_score"])
    return scored
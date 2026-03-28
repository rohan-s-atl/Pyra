"""
spread_risk.py — Wildfire spread risk modelling.

Produces a directional GeoJSON spread cone combining:
  - FRP-derived base risk
  - Wind speed/direction scaling
  - Terrain (slope + aspect) using Rothermel model approximation
  - Humidity modifier (low humidity = faster spread)
  - Risk score (0-100) for frontend display

All geometry is GeoJSON-compliant [lon, lat] coordinate order.
"""

import math
from typing import Optional


CARDINAL_TO_DEGREES = {
    "N": 0,   "NE": 45,  "E": 90,  "SE": 135,
    "S": 180, "SW": 225, "W": 270, "NW": 315,
}

SPREAD_RADIUS_KM = {
    "extreme":  25.0,
    "high":     15.0,
    "moderate":  8.0,
    "low":       3.0,
}

CONE_HALF_ANGLE = {
    "extreme":  60,
    "high":     50,
    "moderate": 40,
    "low":      30,
}

RISK_SCORE_BASE = {
    "extreme": 85,
    "high":    65,
    "moderate": 40,
    "low":     15,
}

RISK_LADDER = ["low", "moderate", "high", "extreme"]


def compute_terrain_adjusted_risk(
    base_spread_risk: str,
    slope_percent: Optional[float],
    aspect_cardinal: Optional[str],
    wind_direction: Optional[str],
) -> str:
    """
    Upgrade spread risk level based on terrain slope and wind alignment.
    Rothermel model approximation:
      - Slope >= 40% + aligned aspect -> escalate 2 levels
      - Slope >= 20%                  -> escalate 1 level
    """
    if slope_percent is None:
        return base_spread_risk

    try:
        current_idx = RISK_LADDER.index(base_spread_risk.lower())
    except ValueError:
        return base_spread_risk

    if slope_percent >= 40:
        steps = 2
    elif slope_percent >= 20:
        steps = 1
    elif slope_percent >= 10:
        steps = 0
    else:
        return base_spread_risk

    if aspect_cardinal and wind_direction:
        aspect_deg = CARDINAL_TO_DEGREES.get(aspect_cardinal.upper())
        wind_deg   = CARDINAL_TO_DEGREES.get(wind_direction.upper())
        if aspect_deg is not None and wind_deg is not None:
            diff = abs(aspect_deg - wind_deg)
            if diff > 180:
                diff = 360 - diff
            if diff <= 45:
                steps = min(steps + 1, 2)

    new_idx = min(current_idx + steps, len(RISK_LADDER) - 1)
    return RISK_LADDER[new_idx]


def compute_risk_score(
    spread_risk: str,
    wind_speed_mph: Optional[float],
    humidity_percent: Optional[float],
    slope_percent: Optional[float],
    terrain_adjusted_risk: Optional[str] = None,
) -> int:
    """Compute a 0-100 numeric risk score incorporating all environmental factors."""
    effective_risk = (terrain_adjusted_risk or spread_risk or "moderate").lower()
    base = RISK_SCORE_BASE.get(effective_risk, 40)

    wind_bonus = 0
    if wind_speed_mph and wind_speed_mph > 0:
        wind_bonus = min(10, int(wind_speed_mph / 5))

    humidity_bonus = 0
    if humidity_percent is not None:
        if humidity_percent < 10:
            humidity_bonus = 8
        elif humidity_percent < 20:
            humidity_bonus = 5
        elif humidity_percent < 30:
            humidity_bonus = 2

    slope_bonus = 0
    if slope_percent:
        if slope_percent >= 40:
            slope_bonus = 7
        elif slope_percent >= 20:
            slope_bonus = 4
        elif slope_percent >= 10:
            slope_bonus = 2

    return min(100, max(0, base + wind_bonus + humidity_bonus + slope_bonus))


def generate_spread_cone(
    latitude: float,
    longitude: float,
    spread_risk: str,
    spread_direction: Optional[str],
    wind_speed_mph: Optional[float] = None,
    humidity_percent: Optional[float] = None,
    slope_percent: Optional[float] = None,
    aspect_cardinal: Optional[str] = None,
) -> dict:
    """
    Generate a directional spread risk cone as a GeoJSON Feature.

    Factors in: wind speed/direction, humidity, terrain slope+aspect.
    Returns GeoJSON Feature with risk_score (0-100) and metadata.
    """
    spread_risk = (spread_risk or "moderate").lower()

    terrain_risk = compute_terrain_adjusted_risk(
        spread_risk, slope_percent, aspect_cardinal, spread_direction
    )

    radius_km  = SPREAD_RADIUS_KM.get(terrain_risk, 8.0)
    half_angle = CONE_HALF_ANGLE.get(terrain_risk, 40)

    if wind_speed_mph and wind_speed_mph > 0:
        wind_factor = min(2.0, 1.0 + (wind_speed_mph / 30.0))
        radius_km  *= wind_factor

    if humidity_percent is not None:
        if humidity_percent < 10:
            radius_km  *= 1.25
            half_angle  = min(half_angle + 10, 70)
        elif humidity_percent < 20:
            radius_km  *= 1.12

    if slope_percent and slope_percent >= 10:
        if slope_percent >= 40:
            slope_boost = 1.4
        elif slope_percent >= 20:
            slope_boost = 1.2
        else:
            slope_boost = 1.1
        radius_km *= slope_boost

    direction_deg = CARDINAL_TO_DEGREES.get(
        spread_direction.upper() if spread_direction else "N", 0
    )

    points = _generate_cone_points(
        lat=latitude,
        lon=longitude,
        direction_deg=direction_deg,
        radius_km=radius_km,
        half_angle_deg=half_angle,
        num_arc_points=20,
    )

    risk_score = compute_risk_score(
        spread_risk=spread_risk,
        wind_speed_mph=wind_speed_mph,
        humidity_percent=humidity_percent,
        slope_percent=slope_percent,
        terrain_adjusted_risk=terrain_risk,
    )

    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [points],
        },
        "properties": {
            "spread_risk":           spread_risk,
            "terrain_adjusted_risk": terrain_risk,
            "risk_score":            risk_score,
            "spread_direction":      spread_direction,
            "radius_km":             round(radius_km, 2),
            "wind_speed_mph":        wind_speed_mph,
            "humidity_percent":      humidity_percent,
            "direction_degrees":     direction_deg,
            "slope_percent":         slope_percent,
            "aspect_cardinal":       aspect_cardinal,
            "terrain_adjusted":      terrain_risk != spread_risk,
        },
    }


def _generate_cone_points(
    lat: float,
    lon: float,
    direction_deg: float,
    radius_km: float,
    half_angle_deg: float,
    num_arc_points: int = 20,
) -> list:
    """Generate [lon, lat] polygon points for a directional cone."""
    points = [[lon, lat]]

    start_angle = direction_deg - half_angle_deg
    end_angle   = direction_deg + half_angle_deg

    for i in range(num_arc_points + 1):
        angle_deg = start_angle + (end_angle - start_angle) * (i / num_arc_points)
        angle_rad = math.radians(angle_deg)

        delta_lat = (radius_km / 111.0) * math.cos(angle_rad)
        delta_lon = (radius_km / (111.0 * math.cos(math.radians(lat)))) * math.sin(angle_rad)

        points.append([lon + delta_lon, lat + delta_lat])

    points.append([lon, lat])
    return points
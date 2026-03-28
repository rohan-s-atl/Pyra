from __future__ import annotations

from typing import Any

_RISK_MULT = {"low": 0.85, "moderate": 1.0, "high": 1.2, "extreme": 1.45}
_SEVERITY_MULT = {"low": 0.85, "moderate": 1.0, "high": 1.18, "critical": 1.35, "extreme": 1.45}

def _safe_num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def estimate_rate_of_spread(
    fire_type: str | None,
    wind_speed_mph: float | None,
    humidity_percent: float | None,
    slope_percent: float | None = None,
) -> float:
    fire_type = (fire_type or 'wildland').lower()
    wind = max(_safe_num(wind_speed_mph), 0.0)
    humidity = min(max(_safe_num(humidity_percent, 35.0), 0.0), 100.0)
    slope = max(_safe_num(slope_percent), 0.0)

    base = {
        'wildland': 0.7,
        'brush': 0.9,
        'grass': 1.1,
        'timber': 0.6,
        'wildland_urban_interface': 0.55,
        'structure': 0.25,
        'vehicle': 0.2,
    }.get(fire_type, 0.7)

    ros = base
    ros *= 1.0 + min(wind / 45.0, 1.75)
    ros *= 1.0 + min(slope / 100.0, 0.8)
    ros *= 1.0 + max((35.0 - humidity) / 100.0, -0.15)
    return round(max(0.05, min(ros, 15.0)), 2)


def estimate_spotting(
    fire_behavior_index_val: float,
    wind_speed_mph: float | None,
) -> dict:
    fbi = max(0.0, min(_safe_num(fire_behavior_index_val), 1.0))
    wind = max(_safe_num(wind_speed_mph), 0.0)

    if fbi >= 0.75:
        potential = 'extreme'
    elif fbi >= 0.5:
        potential = 'high'
    elif fbi >= 0.25:
        potential = 'moderate'
    else:
        potential = 'low'

    distance = round(min(fbi * wind * 0.08, 8.0), 1) if wind > 0 else 0.0

    return {
        'spotting_potential': potential,
        'spotting_distance_miles': distance,
    }


def estimate_containment_probability(
    fire_behavior_index_val: float,
    units_on_scene: int | None,
    containment_percent: float | None,
    acres_burned: float | None,
) -> float:
    fbi = max(0.0, min(_safe_num(fire_behavior_index_val), 1.0))
    units = max(int(units_on_scene or 0), 0)
    containment = min(max(_safe_num(containment_percent, 0.0), 0.0), 100.0) / 100.0
    acres = max(_safe_num(acres_burned, 100.0), 1.0)

    base = 0.5
    base -= fbi * 0.35
    base += units * 0.04
    base += containment * 0.25
    base -= min(acres / 10000.0, 0.15)
    return round(max(0.0, min(base, 1.0)), 3)


def fire_behavior_index(
    wind_speed_mph: float | None,
    humidity_percent: float | None,
    spread_risk: str | None,
    slope_percent: float | None,
    aqi: float | None = None,
) -> float:
    wind = max(_safe_num(wind_speed_mph), 0.0)
    humidity = min(max(_safe_num(humidity_percent, 35.0), 0.0), 100.0)
    slope = max(_safe_num(slope_percent), 0.0)
    aqi_val = max(_safe_num(aqi), 0.0)
    risk_mult = _RISK_MULT.get((spread_risk or 'moderate').lower(), 1.0)

    score = 0.0
    score += min(wind / 45.0, 1.0) * 0.38
    score += min(max((40.0 - humidity) / 40.0, 0.0), 1.0) * 0.24
    score += min(slope / 60.0, 1.0) * 0.18
    score += min(aqi_val / 300.0, 1.0) * 0.08
    score *= risk_mult
    return round(max(0.0, min(score, 1.0)), 3)


def predict_fire_behavior(
    fire_type: str | None,
    spread_risk: str | None,
    wind_speed_mph: float | None,
    humidity_percent: float | None,
    containment_percent: float | None,
    acres_burned: float | None,
    units_on_scene: int | None = None,
    slope_percent: float | None = None,
    aqi: float | None = None,
) -> dict:
    ros = estimate_rate_of_spread(fire_type, wind_speed_mph, humidity_percent, slope_percent)
    fbi = fire_behavior_index(wind_speed_mph, humidity_percent, spread_risk, slope_percent, aqi)
    spotting = estimate_spotting(fbi, wind_speed_mph)
    containment_prob = estimate_containment_probability(fbi, units_on_scene, containment_percent, acres_burned)

    containment = min(max(_safe_num(containment_percent), 0.0), 100.0)
    acres = max(_safe_num(acres_burned), 0.0)
    units = max(int(units_on_scene or 0), 0)

    projected_growth_pct = max(0.0, (ros * 18.0) - (containment * 0.22) - (units * 1.5))
    projected_growth_pct = round(min(projected_growth_pct, 250.0), 1)
    projected_acres_12h = round(acres * (1 + projected_growth_pct / 100.0), 1) if acres else None

    if fbi >= 0.8:
        label = 'extreme'
    elif fbi >= 0.6:
        label = 'high'
    elif fbi >= 0.35:
        label = 'moderate'
    else:
        label = 'low'

    descriptions = {
        'extreme': 'Extreme fire behavior expected. Rapid spread, spotting, and erratic winds likely.',
        'high': 'High fire behavior. Active spread with potential for rapid growth.',
        'moderate': 'Moderate fire behavior. Steady spread, manageable with adequate resources.',
        'low': 'Low fire behavior. Slow spread, favorable for suppression.',
    }

    return {
        'fire_behavior_index': fbi,
        'rate_of_spread_mph': ros,
        'spotting_potential': spotting['spotting_potential'],
        'spotting_distance_miles': spotting['spotting_distance_miles'],
        'containment_probability': containment_prob,
        'containment_probability_pct': int(round(containment_prob * 100)),
        'behavior_description': descriptions[label],
        'predicted_behavior': label,
        'projected_growth_percent_12h': projected_growth_pct,
        'projected_acres_12h': projected_acres_12h,
        'suppression_effectiveness': round(max(0.0, min((containment / 100.0) + (units * 0.04), 1.0)), 3),
    }
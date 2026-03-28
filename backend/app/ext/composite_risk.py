from __future__ import annotations

from typing import Any

_SEV = {'low': 0.2, 'moderate': 0.4, 'high': 0.7, 'critical': 0.9, 'extreme': 1.0}
_SPR = {'low': 0.2, 'moderate': 0.45, 'high': 0.7, 'extreme': 0.95}

def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def compute_risk_score(
    fire_behavior_index: float,
    spread_risk: str | None,
    severity: str | None,
    structures_threatened: int | None,
    containment_percent: float | None,
    acres_burned: float | None,
    slope_percent: float | None,
    aspect_cardinal: str | None,
    spread_direction: str | None,
    units_on_scene: int | None,
    units_en_route: int | None,
) -> dict:
    fbi = max(0.0, min(_num(fire_behavior_index), 1.0))
    spread = _SPR.get((spread_risk or 'moderate').lower(), 0.45)
    sev = _SEV.get((severity or 'moderate').lower(), 0.4)
    structures = min(_num(structures_threatened) / 100.0, 1.0)
    containment = min(max(_num(containment_percent), 0.0), 100.0) / 100.0
    acres = min(_num(acres_burned) / 5000.0, 1.0)
    slope = min(_num(slope_percent) / 60.0, 1.0)
    resources = min((int(units_on_scene or 0) + 0.6 * int(units_en_route or 0)) / 12.0, 1.0)

    raw = (
        fbi * 0.30 +
        spread * 0.18 +
        sev * 0.15 +
        structures * 0.14 +
        acres * 0.08 +
        slope * 0.08 +
        (1.0 - containment) * 0.11 -
        resources * 0.10
    )
    score = max(0.0, min(raw, 1.0))

    if score >= 0.8:
        label = 'extreme'
    elif score >= 0.6:
        label = 'high'
    elif score >= 0.35:
        label = 'moderate'
    else:
        label = 'low'

    components = {
        'fire_behavior':    round(fbi * 0.30, 4),
        'spread_risk':      round(spread * 0.18, 4),
        'structure_threat': round(structures * 0.14, 4),
        'containment_gap':  round((1.0 - containment) * 0.11, 4),
        'terrain':          round(slope * 0.08, 4),
        'resource_deficit': round(max(0.0, (1.0 - resources) * 0.10 - resources * 0.10 + 0.10), 4),
    }

    return {
        'risk_score': round(score, 3),
        'risk_level': label,
        'components': components,
        'raw_scores': {
            'fire_behavior_index': round(fbi, 3),
            'spread_score':        round(spread, 3),
            'severity_score':      round(sev, 3),
            'structure_score':     round(structures, 3),
            'containment_score':   round(1.0 - containment, 3),
            'terrain_score':       round(slope if slope > 0 else 0.15, 3),
            'resource_score':      round(resources, 3),
        },
        # kept for backwards compat
        'drivers': {
            'fire_behavior_index': round(fbi, 3),
            'spread_risk_factor':  round(spread, 3),
            'severity_factor':     round(sev, 3),
            'structures_factor':   round(structures, 3),
            'containment_factor':  round(1.0 - containment, 3),
            'resource_relief_factor': round(resources, 3),
        },
    }


def score_incidents_for_heatmap(incidents: list[dict]) -> list[dict]:
    """Batch-score a list of incident dicts, adding risk_score and risk_level."""
    results = []
    for inc in incidents:
        scored = compute_risk_score(
            fire_behavior_index=inc.get('fire_behavior_index', 0.0),
            spread_risk=inc.get('spread_risk'),
            severity=inc.get('severity'),
            structures_threatened=inc.get('structures_threatened'),
            containment_percent=inc.get('containment_percent'),
            acres_burned=inc.get('acres_burned'),
            slope_percent=inc.get('slope_percent'),
            aspect_cardinal=inc.get('aspect_cardinal'),
            spread_direction=inc.get('spread_direction'),
            units_on_scene=inc.get('units_on_scene', 0),
            units_en_route=inc.get('units_en_route', 0),
        )
        results.append({**inc, 'risk_score': scored['risk_score'], 'risk_level': scored['risk_level']})
    return results
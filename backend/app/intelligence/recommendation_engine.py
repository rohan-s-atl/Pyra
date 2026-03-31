from typing import List, Optional
from datetime import datetime, UTC


# Loadout profiles mapped to fire conditions
LOADOUT_RULES = [
    {
        "condition": lambda inc: inc.get("severity") == "critical" and inc.get("fire_type") == "wildland_urban_interface",
        "profile":   "structure_protection",
    },
    {
        "condition": lambda inc: inc.get("severity") in ("critical", "high") and inc.get("spread_risk") in ("extreme", "high"),
        "profile":   "extended_suppression",
    },
    {
        "condition": lambda inc: inc.get("fire_type") == "wildland" and inc.get("structures_threatened", 0) == 0,
        "profile":   "aerial_suppression",
    },
    {
        "condition": lambda inc: inc.get("containment_percent", 0) >= 50,
        "profile":   "containment_support",
    },
    {
        "condition": lambda inc: True,  # Default
        "profile":   "initial_attack",
    },
]

UNIT_RULES = {
    "structure_protection": [
        {"unit_type": "engine",       "quantity": 4, "priority": "immediate",  "rationale": "Structure protection along residential interface."},
        {"unit_type": "air_tanker",   "quantity": 2, "priority": "immediate",  "rationale": "Retardant drop to slow forward spread."},
        {"unit_type": "hand_crew",    "quantity": 2, "priority": "within_1hr", "rationale": "Containment line construction on flanks."},
        {"unit_type": "water_tender", "quantity": 2, "priority": "within_1hr", "rationale": "Resupply support for engines on perimeter."},
        {"unit_type": "command_unit", "quantity": 1, "priority": "immediate",  "rationale": "Establish unified command post."},
    ],
    "extended_suppression": [
        {"unit_type": "hand_crew",    "quantity": 3, "priority": "immediate",  "rationale": "Direct attack and line construction."},
        {"unit_type": "engine",       "quantity": 3, "priority": "immediate",  "rationale": "Perimeter defense and spot fire suppression."},
        {"unit_type": "dozer",        "quantity": 2, "priority": "within_1hr", "rationale": "Construct containment lines on accessible terrain."},
        {"unit_type": "water_tender", "quantity": 2, "priority": "within_1hr", "rationale": "Water resupply for extended operations."},
        {"unit_type": "helicopter",   "quantity": 1, "priority": "within_1hr", "rationale": "Aerial reconnaissance and water drops."},
    ],
    "aerial_suppression": [
        {"unit_type": "air_tanker",   "quantity": 2, "priority": "immediate",  "rationale": "Primary suppression — remote terrain limits ground access."},
        {"unit_type": "helicopter",   "quantity": 2, "priority": "immediate",  "rationale": "Water drops and crew transport."},
        {"unit_type": "hand_crew",    "quantity": 1, "priority": "within_1hr", "rationale": "Accessible flank line construction via trail access."},
    ],
    "containment_support": [
        {"unit_type": "hand_crew",    "quantity": 2, "priority": "immediate",  "rationale": "Mop-up and hotspot patrol."},
        {"unit_type": "engine",       "quantity": 2, "priority": "immediate",  "rationale": "Perimeter patrol and spot fire response."},
        {"unit_type": "water_tender", "quantity": 1, "priority": "within_1hr", "rationale": "Support mop-up operations."},
    ],
    "initial_attack": [
        {"unit_type": "engine",       "quantity": 2, "priority": "immediate",  "rationale": "Initial ground attack."},
        {"unit_type": "hand_crew",    "quantity": 1, "priority": "immediate",  "rationale": "Direct attack support."},
        {"unit_type": "helicopter",   "quantity": 1, "priority": "within_1hr", "rationale": "Aerial reconnaissance and initial water drops."},
    ],
}

TACTICAL_NOTES = {
    "structure_protection": (
        "Priority is life safety and structure protection. "
        "Establish defensible space perimeters before committing engines. "
        "Monitor wind shifts — reassess southern flank exposure if direction changes. "
        "Coordinate evacuation corridors with ground units before aerial drops."
    ),
    "extended_suppression": (
        "Focus on containing the most active flank. "
        "Do not commit resources to direct attack without safe anchor points. "
        "Establish escape routes and safety zones before line construction. "
        "Monitor for spotting ahead of the main fire front."
    ),
    "aerial_suppression": (
        "Ground access is limited — aerial assets are primary suppression tool. "
        "Coordinate air-to-ground communications before drops. "
        "Identify helispots for crew insertion on accessible flanks. "
        "Monitor for terrain-driven wind shifts in canyon areas."
    ),
    "containment_support": (
        "Fire is approaching containment — focus on mop-up and hotspot patrol. "
        "Maintain perimeter integrity and watch for spot fires outside the line. "
        "Begin planning demobilization of non-essential resources."
    ),
    "initial_attack": (
        "Establish command post and size up the fire before committing resources. "
        "Identify escape routes and safety zones immediately. "
        "Request additional resources early if fire behavior is aggressive."
    ),
}


def select_loadout_profile(incident: dict) -> str:
    for rule in LOADOUT_RULES:
        if rule["condition"](incident):
            return rule["profile"]
    return "initial_attack"


def assess_confidence(incident: dict) -> tuple[str, float]:
    """
    Return (label, numeric_score) for the recommendation confidence.

    Numeric score (0.0–1.0) is computed from data completeness and
    incident conditions. Missing data and extreme/novel conditions
    reduce confidence.

    Returns:
        label:  "high" | "moderate" | "low"
        score:  float 0.0–1.0
    """
    checks = {
        "wind_speed_mph":       incident.get("wind_speed_mph") is not None,
        "spread_direction":     incident.get("spread_direction") is not None,
        "acres_burned":         incident.get("acres_burned") is not None,
        "humidity_percent":     incident.get("humidity_percent") is not None,
        "slope_percent":        incident.get("slope_percent") is not None,
        "elevation_m":          incident.get("elevation_m") is not None,
        "aqi":                  incident.get("aqi") is not None,
    }

    data_score = sum(checks.values()) / len(checks)   # 0.0–1.0

    # Severity/spread penalties — novel extreme conditions are harder to predict
    severity   = (incident.get("severity") or "low").lower()
    spread     = (incident.get("spread_risk") or "low").lower()
    novel_penalty = 0.0
    if severity == "critical" and spread == "extreme":
        novel_penalty = 0.15   # uncommon; confidence reduced
    elif severity == "critical" or spread == "extreme":
        novel_penalty = 0.08

    # Units on scene boost confidence (more real-world data)
    units_on_scene = incident.get("units_on_scene", 0)
    unit_boost = min(0.10, units_on_scene * 0.02)

    raw = data_score - novel_penalty + unit_boost
    numeric = round(max(0.0, min(1.0, raw)), 3)

    if numeric >= 0.70:
        label = "high"
    elif numeric >= 0.45:
        label = "moderate"
    else:
        label = "low"

    return label, numeric


def build_summary(incident: dict, loadout: str) -> str:
    name        = incident.get("name", "Unknown Fire")
    severity    = incident.get("severity", "unknown").upper()
    spread_risk = incident.get("spread_risk", "unknown").upper()
    direction   = incident.get("spread_direction") or "unknown direction"
    wind        = incident.get("wind_speed_mph")
    humidity    = incident.get("humidity_percent")
    containment = incident.get("containment_percent", 0)
    structures  = incident.get("structures_threatened", 0)

    lines = [
        f"{name} is a {severity} severity incident with {spread_risk} spread risk",
        f"moving {direction}",
    ]

    if wind:
        lines.append(f"at {wind} mph winds")
    if humidity:
        lines.append(f"and {humidity}% humidity")

    lines.append(f"with {containment}% containment.")

    if structures and structures > 0:
        lines.append(f"{structures} structures are threatened.")

    profile_label = loadout.replace("_", " ").title()
    lines.append(f"Recommended posture: {profile_label}.")

    return " ".join(lines)


def _compute_overall_risk(incident: dict) -> str:
    severity = (incident.get("severity") or "low").lower()
    spread   = (incident.get("spread_risk") or "low").lower()

    if severity == "critical" or spread == "extreme":
        return "extreme"
    if severity == "high" or spread == "high":
        return "high"
    if severity == "moderate" or spread == "moderate":
        return "moderate"
    return "low"


def generate_recommendation(incident: dict, routes: list) -> dict:
    """
    Generate a structured recommendation for an incident.
    Uses rule-based logic on fire conditions, weather, and terrain.
    """
    loadout                    = select_loadout_profile(incident)
    confidence_label, confidence_score = assess_confidence(incident)
    summary                    = build_summary(incident, loadout)

    unit_recs = UNIT_RULES.get(loadout, UNIT_RULES["initial_attack"])

    # Rank routes by safety then travel time
    ranked_routes = sorted(
        routes,
        key=lambda r: (
            0 if r.get("safety_rating") == "safe" else
            1 if r.get("safety_rating") == "caution" else 2,
            r.get("estimated_travel_minutes", 999),
        )
    )

    route_options = [
        {
            "route_id":                r.get("id"),
            "label":                   r.get("label"),
            "estimated_travel_minutes":r.get("estimated_travel_minutes"),
            "terrain_accessibility":   r.get("terrain_accessibility"),
            "fire_exposure_risk":      r.get("fire_exposure_risk"),
            "safety_rating":           r.get("safety_rating"),
            "is_currently_passable":   r.get("is_currently_passable", True),
            "notes":                   r.get("notes"),
            "origin_lat":              r.get("origin_lat"),
            "origin_lon":              r.get("origin_lon"),
            "destination_lat":         r.get("destination_lat"),
            "destination_lon":         r.get("destination_lon"),
        }
        for r in ranked_routes
    ]

    return {
        "id":                   f"REC-{incident['id']}-{datetime.now(UTC).strftime('%Y%m%d%H%M')}",
        "incident_id":          incident["id"],
        "generated_at":         datetime.now(UTC).isoformat(),
        "confidence":           confidence_label,
        "confidence_score":     confidence_score,
        "loadout_profile":      loadout,
        "summary":              summary,
        "unit_recommendations": unit_recs,
        "route_options":        route_options,
        "tactical_notes":       TACTICAL_NOTES.get(loadout, ""),
        "overall_risk":         _compute_overall_risk(incident),
    }
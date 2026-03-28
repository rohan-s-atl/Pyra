# backend/app/intelligence/alert_recommendation.py

ALERT_RECOMMENDATIONS = {
    "spread_warning": {
        "critical": {
            "actions": [
                "Immediately reassess all crew positions relative to fire perimeter",
                "Activate escape routes and confirm safety zones with all divisions",
                "Request additional air tanker support for forward spread suppression",
                "Notify evacuation coordinators — prepare for structure threat escalation",
                "Increase weather monitoring frequency to every 15 minutes",
            ],
            "units": [
                {"unit_type": "air_tanker",   "quantity": 2, "priority": "immediate",  "rationale": "Retardant drops on advancing head to slow forward spread."},
                {"unit_type": "helicopter",   "quantity": 1, "priority": "immediate",  "rationale": "Aerial reconnaissance and hotspot identification."},
                {"unit_type": "engine",       "quantity": 3, "priority": "within_1hr", "rationale": "Structure protection on threatened residential interface."},
            ],
        },
        "warning": {
            "actions": [
                "Monitor spread direction closely and brief all crews on current fire behavior",
                "Pre-position engines along threatened flank",
                "Confirm escape routes with division supervisors",
                "Request weather update from FBAN",
            ],
            "units": [
                {"unit_type": "engine",     "quantity": 2, "priority": "immediate",  "rationale": "Pre-position on advancing flank for suppression."},
                {"unit_type": "helicopter", "quantity": 1, "priority": "within_1hr", "rationale": "Aerial monitoring of spread direction."},
            ],
        },
    },
    "weather_shift": {
        "critical": {
            "actions": [
                "Issue immediate Red Flag advisory to all crews on scene",
                "Reassess all anchor points — wind shift may expose previously safe flanks",
                "Withdraw crews from direct attack until new fire behavior is assessed",
                "Reposition air resources to account for new wind direction",
                "Update evacuation routes in coordination with law enforcement",
            ],
            "units": [
                {"unit_type": "helicopter", "quantity": 2, "priority": "immediate",  "rationale": "Rapid recon of new fire behavior and spread under changed conditions."},
                {"unit_type": "engine",     "quantity": 2, "priority": "within_1hr", "rationale": "Reposition to newly exposed flanks after wind assessment."},
            ],
        },
        "warning": {
            "actions": [
                "Brief all division supervisors on forecast wind shift",
                "Review and update escape routes for new wind direction",
                "Monitor relative humidity — if below 12% escalate to Red Flag protocol",
                "Prepare to reposition aerial assets",
            ],
            "units": [
                {"unit_type": "helicopter", "quantity": 1, "priority": "within_1hr", "rationale": "Monitor developing fire behavior under new weather conditions."},
            ],
        },
    },
    "route_blocked": {
        "critical": {
            "actions": [
                "Immediately notify all inbound units of blocked route",
                "Activate alternate route — coordinate with law enforcement for access",
                "Assess whether units already committed can safely withdraw",
                "Request dozer to cut emergency access if terrain permits",
                "Update ICS-204 with new access routes",
            ],
            "units": [
                {"unit_type": "dozer",      "quantity": 1, "priority": "immediate",  "rationale": "Emergency access construction if terrain permits."},
                {"unit_type": "helicopter", "quantity": 1, "priority": "immediate",  "rationale": "Aerial resupply and personnel extraction if ground access fails."},
            ],
        },
        "warning": {
            "actions": [
                "Monitor route condition and reassess passability every 30 minutes",
                "Identify and brief crews on alternate access routes",
                "Stage water tenders at last safe access point",
            ],
            "units": [
                {"unit_type": "engine", "quantity": 1, "priority": "within_1hr", "rationale": "Scout alternate route for passability before committing resources."},
            ],
        },
    },
    "asset_at_risk": {
        "critical": {
            "actions": [
                "Deploy structure protection engines immediately to threatened structures",
                "Establish defensible space — clear 30 ft minimum around structures",
                "Coordinate with law enforcement for immediate evacuation order",
                "Pre-treat structures with fire retardant foam if available",
                "Establish triage: identify which structures are defensible vs. non-defensible",
            ],
            "units": [
                {"unit_type": "engine",       "quantity": 4, "priority": "immediate",  "rationale": "Structure protection — one engine per structure cluster."},
                {"unit_type": "water_tender", "quantity": 2, "priority": "immediate",  "rationale": "Sustained water supply for structure protection engines."},
                {"unit_type": "hand_crew",    "quantity": 1, "priority": "within_1hr", "rationale": "Clear defensible space around priority structures."},
            ],
        },
        "warning": {
            "actions": [
                "Pre-position engines near threatened structures",
                "Issue voluntary evacuation notice to residents",
                "Assess structure defensibility and triage priority",
                "Ensure water supply for sustained structure protection",
            ],
            "units": [
                {"unit_type": "engine",       "quantity": 2, "priority": "immediate",  "rationale": "Pre-position for structure protection."},
                {"unit_type": "water_tender", "quantity": 1, "priority": "within_1hr", "rationale": "Water supply support for engines."},
            ],
        },
    },
    "water_source_constraint": {
        "critical": {
            "actions": [
                "Immediately dispatch additional water tenders to scene",
                "Identify nearest hydrant or water source within 1 mile",
                "Reduce water usage to critical operations only until resupply arrives",
                "Contact dispatch for mutual aid water tender request",
                "Establish water shuttle operation with available tenders",
            ],
            "units": [
                {"unit_type": "water_tender", "quantity": 3, "priority": "immediate",  "rationale": "Emergency water resupply — establish shuttle operation."},
                {"unit_type": "helicopter",   "quantity": 1, "priority": "within_1hr", "rationale": "Aerial water drops to supplement ground operations."},
            ],
        },
        "warning": {
            "actions": [
                "Confirm water source location and access with on-scene tenders",
                "Request additional tender from dispatch as precaution",
                "Monitor tender capacity — initiate resupply before dropping below 25%",
            ],
            "units": [
                {"unit_type": "water_tender", "quantity": 1, "priority": "within_1hr", "rationale": "Precautionary water resupply to maintain operational capacity."},
            ],
        },
    },
    "evacuation_recommended": {
        "critical": {
            "actions": [
                "Coordinate mandatory evacuation order with county OES immediately",
                "Request law enforcement for evacuation route control",
                "Establish evacuation assembly point away from fire threat",
                "Deploy engines to escort and protect evacuation corridor",
                "Notify hospitals and shelters of incoming evacuees",
            ],
            "units": [
                {"unit_type": "engine",       "quantity": 2, "priority": "immediate",  "rationale": "Escort and protect evacuation corridors from fire encroachment."},
                {"unit_type": "command_unit", "quantity": 1, "priority": "immediate",  "rationale": "Coordinate evacuation with law enforcement and OES."},
            ],
        },
        "warning": {
            "actions": [
                "Issue voluntary evacuation advisory to affected zones",
                "Brief law enforcement on potential mandatory order trigger conditions",
                "Pre-stage resources at evacuation corridor entry points",
            ],
            "units": [
                {"unit_type": "command_unit", "quantity": 1, "priority": "within_1hr", "rationale": "Coordinate with OES for evacuation planning."},
            ],
        },
    },
    "resource_shortage": {
        "critical": {
            "actions": [
                "Submit immediate mutual aid request through dispatch",
                "Prioritize remaining resources on highest-threat division",
                "Request OES activation for additional engine strike teams",
                "Consider aerial resources as force multiplier until ground units arrive",
                "Brief IC on resource status — reassess tactical objectives",
            ],
            "units": [
                {"unit_type": "air_tanker", "quantity": 2, "priority": "immediate",  "rationale": "Aerial suppression as force multiplier during resource deficit."},
                {"unit_type": "helicopter", "quantity": 1, "priority": "immediate",  "rationale": "Aerial recon and water drops to hold perimeter."},
            ],
        },
        "warning": {
            "actions": [
                "Request additional resources through dispatch as precaution",
                "Review current resource assignments — release non-critical units to staging",
                "Monitor returning units ETA for redeployment planning",
            ],
            "units": [
                {"unit_type": "engine",    "quantity": 2, "priority": "within_1hr", "rationale": "Mutual aid engines to address resource gap."},
                {"unit_type": "hand_crew", "quantity": 1, "priority": "within_1hr", "rationale": "Hand crew for line construction on understaffed divisions."},
            ],
        },
    },
}


def generate_alert_recommendation(alert_type: str, severity: str, alert_title: str, incident: dict = None) -> dict:
    """Generate rule-based tactical recommendation for an alert."""
    type_recs = ALERT_RECOMMENDATIONS.get(alert_type, {})

    # Try exact severity match, fall back to warning, then critical
    rec = type_recs.get(severity) or type_recs.get("warning") or type_recs.get("critical")

    if not rec:
        return {
            "actions":          ["Monitor situation and follow standard ICS protocols."],
            "units":            [],
            "summary":          f"Alert: {alert_title}. No specific protocol available — consult IC.",
            "confidence":       "low",
            "confidence_score": 0.30,
        }

    # Build context-aware summary
    lines = [f"Alert: {alert_title}."]
    data_points = 0
    if incident:
        containment = incident.get("containment_percent", 0)
        wind        = incident.get("wind_speed_mph")
        humidity    = incident.get("humidity_percent")
        structures  = incident.get("structures_threatened", 0)

        if wind and wind > 20:
            lines.append(f"Wind at {wind} mph increases urgency.")
            data_points += 1
        if humidity and humidity < 12:
            lines.append(f"Critical humidity at {humidity}% — extreme fire behavior possible.")
            data_points += 1
        if structures and structures > 0:
            lines.append(f"{structures} structures threatened.")
            data_points += 1
        if containment < 15:
            lines.append(f"Low containment ({containment}%) — aggressive action required.")
            data_points += 1

    # Confidence: higher when we have more incident data
    raw_score = 0.50 + (data_points * 0.10)
    confidence_score = round(min(0.95, raw_score), 3)
    confidence_label = "high" if confidence_score >= 0.70 else ("moderate" if confidence_score >= 0.45 else "low")

    return {
        "actions":          rec["actions"],
        "units":            rec["units"],
        "summary":          " ".join(lines),
        "confidence":       confidence_label,
        "confidence_score": confidence_score,
    }

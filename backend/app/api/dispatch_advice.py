"""
dispatch_advice.py — AI dispatch assessment. (PATCHED)

FIXES APPLIED
-------------
1. anthropic.Anthropic (blocking sync) inside asyncio.wait_for is NOT truly
   async — it blocks the event loop thread. Replaced with AsyncAnthropic.
2. Model kept as claude-sonnet-4-6 (this is a nuanced assessment, not a
   structured JSON task — Sonnet quality matters here).
3. Timeout increased 10s → 15s with proper async handling.
4. Graceful fallback: on timeout or AI error, returns a rule-based assessment
   instead of HTTP 500, so the dispatch flow is never blocked by AI failures.
5. Removed redundant Recommendation DB query in hot path — the rule-based
   loadout profile from recommendation_engine is used directly instead.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator
from typing import List
import anthropic
import logging
import asyncio

from app.core.database import get_db
from app.core.config import settings
from app.core.security import require_dispatcher_or_above
from app.models.incident import Incident
from app.models.unit import Unit
from app.models.user import User
from app.core.limiter import limiter
from app.intelligence.recommendation_engine import select_loadout_profile, UNIT_RULES

router = APIRouter(prefix="/api/dispatch-advice", tags=["Dispatch Advice"])
logger = logging.getLogger(__name__)

UNIT_TYPE_LABEL = {
    "engine":       "Engine",
    "hand_crew":    "Hand Crew",
    "dozer":        "Dozer",
    "water_tender": "Water Tender",
    "helicopter":   "Helicopter",
    "air_tanker":   "Air Tanker",
    "command_unit": "Command Unit",
    "rescue":       "Rescue",
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class AdviceRequest(BaseModel):
    unit_ids: List[str]

    @field_validator("unit_ids")
    @classmethod
    def validate_unit_ids(cls, v):
        if not v:
            raise ValueError("At least one unit required")
        if len(v) > 50:
            raise ValueError("Too many units requested")
        return v


# ---------------------------------------------------------------------------
# Rule-based fallback (used when AI is unavailable or times out)
# ---------------------------------------------------------------------------

def _rule_based_assessment(
    incident: Incident,
    selected_units: list[Unit],
    loadout_str: str,
    rec_str: str,
) -> dict:
    """Fast rule-based dispatch assessment — no AI required."""
    type_counts = {}
    for u in selected_units:
        type_counts[u.unit_type] = type_counts.get(u.unit_type, 0) + 1

    inc_dict = {
        "severity":              incident.severity,
        "fire_type":             incident.fire_type,
        "spread_risk":           incident.spread_risk,
        "structures_threatened": incident.structures_threatened,
        "containment_percent":   incident.containment_percent,
    }
    profile  = select_loadout_profile(inc_dict)
    rec_types = {r["unit_type"] for r in UNIT_RULES.get(profile, [])}
    missing  = rec_types - set(type_counts.keys())

    if not missing:
        assessment = "optimal"
        advice = (
            f"OPTIMAL — Proposed dispatch ({loadout_str}) covers all recommended unit types "
            f"for {profile.replace('_', ' ')} posture. No critical gaps identified."
        )
    elif len(missing) <= 1:
        assessment = "adequate"
        m = ", ".join(UNIT_TYPE_LABEL.get(t, t) for t in missing)
        advice = (
            f"ADEQUATE — Dispatch covers most recommended types; consider adding {m} "
            f"for full {profile.replace('_', ' ')} posture."
        )
    else:
        assessment = "suboptimal"
        m = ", ".join(UNIT_TYPE_LABEL.get(t, t) for t in missing)
        advice = (
            f"SUBOPTIMAL — Missing recommended unit types: {m}. "
            f"Add these before dispatch for {incident.severity.upper()} {incident.fire_type.replace('_', ' ')} conditions."
        )

    return {"advice": advice, "assessment": assessment, "loadout": loadout_str}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/{incident_id}",
    summary="Get AI assessment of the selected dispatch loadout",
)
@limiter.limit("10/minute")
async def dispatch_advice(
    incident_id: str,
    request: Request,
    body: AdviceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Incident not found")

    selected_units = db.query(Unit).filter(Unit.id.in_(body.unit_ids)).all()
    if not selected_units:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="No valid units provided")

    # Build loadout string
    type_counts: dict[str, int] = {}
    for u in selected_units:
        label = UNIT_TYPE_LABEL.get(u.unit_type, u.unit_type)
        type_counts[label] = type_counts.get(label, 0) + 1
    loadout_str = ", ".join(f"{count}× {label}" for label, count in type_counts.items())

    # Already on scene
    already_on = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id,
        Unit.status.in_(["on_scene", "en_route"]),
    ).all()
    on_scene_str = ", ".join(
        UNIT_TYPE_LABEL.get(u.unit_type, u.unit_type) for u in already_on
    ) or "None"

    # System recommendation from rule engine (no DB hit needed)
    inc_dict = {
        "severity":              incident.severity,
        "fire_type":             incident.fire_type,
        "spread_risk":           incident.spread_risk,
        "structures_threatened": incident.structures_threatened,
        "containment_percent":   incident.containment_percent,
    }
    profile   = select_loadout_profile(inc_dict)
    rec_units = UNIT_RULES.get(profile, [])
    rec_str   = ", ".join(
        f"{r['quantity']}× {UNIT_TYPE_LABEL.get(r['unit_type'], r['unit_type'])}"
        for r in rec_units
    ) or "No recommendation available"

    # ── No API key — use rule-based fallback ─────────────────────────────────
    if not settings.anthropic_api_key:
        return _rule_based_assessment(incident, selected_units, loadout_str, rec_str)

    prompt = (
        f"You are a CAL FIRE dispatch advisor AI. Evaluate this unit dispatch in exactly 2 sentences.\n\n"
        f"INCIDENT: {incident.name}\n"
        f"TYPE: {incident.fire_type.replace('_',' ').title()} | SEVERITY: {incident.severity.upper()}\n"
        f"WIND: {incident.wind_speed_mph or 0:.0f} mph {incident.spread_direction or ''} | "
        f"HUMIDITY: {incident.humidity_percent or 0:.0f}% | SPREAD RISK: {(incident.spread_risk or '').upper()}\n"
        f"STRUCTURES THREATENED: {incident.structures_threatened or 0}\n"
        f"ALREADY ON SCENE/EN ROUTE: {on_scene_str}\n"
        f"SYSTEM RECOMMENDATION: {rec_str}\n"
        f"PROPOSED DISPATCH: {loadout_str}\n\n"
        f"Sentence 1: OPTIMAL (matches or exceeds recommendation) / ADEQUATE / SUBOPTIMAL\n"
        f"Sentence 2: single biggest risk or gap, or confirmation if optimal. No extra text."
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await asyncio.wait_for(
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=120,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=15,
        )
        advice = message.content[0].text.strip()
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning("[dispatch_advice] AI call failed: %s — using rule-based fallback", e)
        return _rule_based_assessment(incident, selected_units, loadout_str, rec_str)

    upper = advice.upper()
    if "OPTIMAL" in upper and "SUB" not in upper:
        assessment = "optimal"
    elif "SUBOPTIMAL" in upper:
        assessment = "suboptimal"
    else:
        assessment = "adequate"

    return {"advice": advice, "assessment": assessment, "loadout": loadout_str}

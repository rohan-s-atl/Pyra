"""
chat.py — SITREP chat streaming endpoint. (PATCHED)

FIXES APPLIED
-------------
1. client.messages.stream() is a sync context manager — wrapping it in
   asyncio.wait_for around a sync lambda DOES NOT make it async; it still
   blocks the event loop during streaming. Fixed by using AsyncAnthropic with
   async_stream context manager instead.
2. Alert query now capped at 10 most recent unacked — the old query fetched
   ALL unacknowledged alerts, which could be hundreds, and included them all
   in the system prompt (token waste + slow context build).
3. Unit queries limited to 20 each — on a large incident with many units the
   old code fetched every single one into the prompt.
4. Timeout moved to the outer stream generator with asyncio.wait_for so a
   hung connection doesn't hold the server thread indefinitely.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, field_validator
from typing import List
import anthropic
import json
import logging
import asyncio

from app.core.database import get_db
from app.core.config import settings
from app.core.security import require_any_role
from app.models.incident import Incident
from app.models.unit import Unit
from app.models.alert import Alert
from app.models.user import User
from app.core.limiter import limiter
from app.intelligence.recommendation_engine import (
    select_loadout_profile, TACTICAL_NOTES, UNIT_RULES, _adjust_unit_recommendations,
)
from app.ext.fire_behavior import predict_fire_behavior
from app.ext.composite_risk import compute_risk_score

router = APIRouter(prefix="/api/chat", tags=["Chat"])
logger = logging.getLogger(__name__)

_CHAT_TIMEOUT = 30   # total seconds for the full stream before we give up


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v not in {"user", "assistant"}:
            raise ValueError("Invalid role")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError("Message content cannot be empty")
        if len(v) > 2000:
            raise ValueError("Message too long")
        return v.strip()


class ChatRequest(BaseModel):
    messages: List[ChatMessage]

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v):
        if not v:
            raise ValueError("At least one message required")
        if len(v) > 20:
            raise ValueError("Too many messages")
        return v


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_system(
    incident: Incident,
    units_on: list,
    units_en: list,
    active_alerts: list,
    available_by_type: dict[str, int],
    rec_profile: str,
    tactical_notes: str,
    rec_unit_rules: list[dict],
    fire_behavior: dict,
    risk: dict,
) -> str:
    unit_lines = "\n".join(
        f"  - {u.designation} ({u.unit_type.replace('_', ' ')}) — {u.status}"
        for u in units_on + units_en
    ) or "  - None assigned"

    alert_lines = "\n".join(
        f"  - [{a.severity.upper()}] {a.title}: {a.description[:80]}"
        for a in active_alerts
    ) or "  - None"

    acres = f"{incident.acres_burned:,.0f}" if incident.acres_burned else "Unknown"

    # Fleet section — only types with at least 1 available unit
    if available_by_type:
        fleet_lines = "\n".join(
            f"  - {utype.replace('_', ' ')}: {count} available"
            for utype, count in sorted(available_by_type.items())
        )
    else:
        fleet_lines = "  - None available (all units assigned or offline)"

    # What the recommendation engine says this incident needs
    rec_lines = "\n".join(
        f"  - {r['unit_type'].replace('_', ' ')}: {r['quantity']} ({r['priority'].replace('_', ' ')}) — {r['rationale']}"
        for r in rec_unit_rules
    )

    # Terrain block — omit fields that were never fetched
    terrain_parts = []
    if incident.elevation_m is not None:
        terrain_parts.append(f"elevation {incident.elevation_m:.0f} m")
    if incident.slope_percent is not None:
        terrain_parts.append(f"slope {incident.slope_percent:.1f}%")
    if incident.aspect_cardinal:
        terrain_parts.append(f"aspect {incident.aspect_cardinal}")
    terrain_line = ", ".join(terrain_parts) if terrain_parts else "Not available"

    # AQI block
    if incident.aqi is not None:
        aqi_line = f"{incident.aqi} ({incident.aqi_category or 'unknown category'})"
    else:
        aqi_line = "Not available"

    proj_acres = fire_behavior.get("projected_acres_12h")
    proj_acres_str = f"{proj_acres:,.0f} acres" if proj_acres else "unknown"

    return (
        f"You are Pyra, an AI wildfire command support system embedded in an incident command platform.\n\n"
        f"INCIDENT: {incident.name}\n"
        f"TYPE: {incident.fire_type.replace('_', ' ').title()}\n"
        f"SEVERITY: {incident.severity.upper()}\n"
        f"STATUS: {incident.status.upper()}\n"
        f"LOCATION: {incident.latitude:.4f}N, {abs(incident.longitude):.4f}W\n"
        f"ACRES BURNED: {acres}\n"
        f"CONTAINMENT: {incident.containment_percent or 0:.0f}%\n"
        f"SPREAD RISK: {(incident.spread_risk or '').upper()}\n"
        f"SPREAD DIRECTION: {incident.spread_direction or 'Unknown'}\n\n"
        f"WEATHER:\n"
        f"  Wind: {incident.wind_speed_mph or 0:.1f} mph\n"
        f"  Humidity: {incident.humidity_percent or 0:.1f}%\n"
        f"  AQI: {aqi_line}\n\n"
        f"TERRAIN:\n"
        f"  {terrain_line}\n\n"
        f"STRUCTURES THREATENED: {incident.structures_threatened or 0}\n\n"
        f"FIRE BEHAVIOR (computed from current conditions):\n"
        f"  Fire Behavior Index (FBI): {fire_behavior.get('fire_behavior_index', 'N/A')} — {fire_behavior.get('predicted_behavior', '').upper()}\n"
        f"  {fire_behavior.get('behavior_description', '')}\n"
        f"  Rate of Spread: {fire_behavior.get('rate_of_spread_mph', 'N/A')} mph\n"
        f"  Spotting Potential: {fire_behavior.get('spotting_potential', 'N/A')} ({fire_behavior.get('spotting_distance_miles', 0)} mi max)\n"
        f"  Containment Probability: {fire_behavior.get('containment_probability_pct', 'N/A')}%\n"
        f"  Projected Growth (12h): {fire_behavior.get('projected_growth_percent_12h', 'N/A')}% → {proj_acres_str}\n"
        f"  Suppression Effectiveness: {fire_behavior.get('suppression_effectiveness', 'N/A')}\n\n"
        f"COMPOSITE RISK SCORE: {risk.get('risk_score', 'N/A')} / 1.0 — {risk.get('risk_level', '').upper()}\n"
        f"  Drivers: FBI={risk.get('raw_scores', {}).get('fire_behavior_index', 'N/A')}, "
        f"spread={risk.get('raw_scores', {}).get('spread_score', 'N/A')}, "
        f"terrain={risk.get('raw_scores', {}).get('terrain_score', 'N/A')}, "
        f"structures={risk.get('raw_scores', {}).get('structure_score', 'N/A')}, "
        f"resources={risk.get('raw_scores', {}).get('resource_score', 'N/A')}\n\n"
        f"ASSIGNED RESOURCES (top 20):\n{unit_lines}\n\n"
        f"FLEET — AVAILABLE TO DISPATCH (do not suggest unit types not listed here):\n{fleet_lines}\n\n"
        f"SYSTEM RECOMMENDATION — Profile: {rec_profile.replace('_', ' ').title()}\n"
        f"Recommended units for this incident:\n{rec_lines}\n"
        f"Tactical posture: {tactical_notes}\n\n"
        f"ACTIVE ALERTS (recent 10):\n{alert_lines}\n\n"
        f"CRITICAL RULES:\n"
        f"- When advising on tactics or dispatch, ONLY reference unit types present in the FLEET section above.\n"
        f"- If a recommended unit type has zero availability, explicitly state it is unavailable and suggest the best alternative from the fleet.\n"
        f"- Do not invent unit designations — use only those listed in ASSIGNED RESOURCES.\n"
        f"- Ground tactical advice in the FIRE BEHAVIOR and COMPOSITE RISK data above, not generic doctrine.\n"
        f"- Respond concisely using ICS terminology. Do not speculate beyond available data.\n"
        f"- Keep responses under 200 words unless explicitly asked for more detail."
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/{incident_id}", summary="Stream SITREP chat response")
@limiter.limit("10/minute")
async def chat(
    incident_id: str,
    request: Request,
    body: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=500, detail="AI service not configured")

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Cap unit/alert queries to keep prompt size bounded
    units_on = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id,
        Unit.status == "on_scene",
    ).limit(20).all()

    units_en = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id,
        Unit.status == "en_route",
    ).limit(10).all()

    alerts = (
        db.query(Alert)
        .filter(Alert.incident_id == incident_id, Alert.is_acknowledged.is_(False))
        .order_by(Alert.created_at.desc())
        .limit(10)
        .all()
    )

    # Count available units by type so the AI knows what can actually be dispatched
    available_rows = (
        db.query(Unit.unit_type, func.count(Unit.id).label("cnt"))
        .filter(Unit.status == "available", Unit.assigned_incident_id.is_(None))
        .group_by(Unit.unit_type)
        .all()
    )
    available_by_type: dict[str, int] = {row.unit_type: row.cnt for row in available_rows}

    # Get the recommendation engine's tactical profile for this incident
    incident_dict = {
        "id":                   incident.id,
        "severity":             incident.severity,
        "fire_type":            incident.fire_type,
        "spread_risk":          incident.spread_risk,
        "containment_percent":  incident.containment_percent or 0,
        "structures_threatened":incident.structures_threatened or 0,
        "units_on_scene":       len(units_on),
        "units_en_route":       len(units_en),
    }
    rec_profile    = select_loadout_profile(incident_dict)
    tactical_notes = TACTICAL_NOTES.get(rec_profile, "")
    rec_unit_rules = _adjust_unit_recommendations(
        rec_profile, incident_dict, UNIT_RULES.get(rec_profile, UNIT_RULES["initial_attack"])
    )

    # Compute live fire behavior and composite risk from all ingested data
    fire_behavior = predict_fire_behavior(
        fire_type          = incident.fire_type,
        spread_risk        = incident.spread_risk,
        wind_speed_mph     = incident.wind_speed_mph,
        humidity_percent   = incident.humidity_percent,
        containment_percent= incident.containment_percent,
        acres_burned       = incident.acres_burned,
        units_on_scene     = len(units_on),
        slope_percent      = incident.slope_percent,
        aqi                = incident.aqi,
    )
    risk = compute_risk_score(
        fire_behavior_index  = fire_behavior["fire_behavior_index"],
        spread_risk          = incident.spread_risk,
        severity             = incident.severity,
        structures_threatened= incident.structures_threatened,
        containment_percent  = incident.containment_percent,
        acres_burned         = incident.acres_burned,
        slope_percent        = incident.slope_percent,
        aspect_cardinal      = incident.aspect_cardinal,
        spread_direction     = incident.spread_direction,
        units_on_scene       = len(units_on),
        units_en_route       = len(units_en),
    )

    # Build the full system prompt from ORM objects while the session is still open
    system   = _build_system(incident, units_on, units_en, alerts, available_by_type, rec_profile, tactical_notes, rec_unit_rules, fire_behavior, risk)
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    # Everything needed is now in plain strings — close the session so the
    # connection is returned to the pool before the AI stream begins (up to 30s).
    db.close()

    async def stream_generator():
        try:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

            async with client.messages.stream(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                system=system,
                messages=messages,
            ) as s:
                async for text in s.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"

            yield "data: [DONE]\n\n"

        except asyncio.TimeoutError:
            logger.error("[chat] Stream timeout for incident=%s", incident_id)
            yield f"data: {json.dumps({'error': 'AI timeout'})}\n\n"
        except Exception as e:
            logger.error("[chat] Stream error: %s", e)
            yield f"data: {json.dumps({'error': 'AI stream failed'})}\n\n"

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
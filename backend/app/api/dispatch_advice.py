from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator
from typing import List
import anthropic
import logging
import asyncio
import json

from app.core.database import get_db
from app.core.config import settings
from app.core.security import require_dispatcher_or_above
from app.models.incident import Incident
from app.models.unit import Unit
from app.models.recommendation import Recommendation
from app.models.user import User

from app.core.limiter import limiter

router = APIRouter(prefix="/api/dispatch-advice", tags=["Dispatch Advice"])

logger = logging.getLogger(__name__)

UNIT_TYPE_LABEL = {
    "engine": "Engine",
    "hand_crew": "Hand Crew",
    "dozer": "Dozer",
    "water_tender": "Water Tender",
    "helicopter": "Helicopter",
    "air_tanker": "Air Tanker",
    "command_unit": "Command Unit",
    "rescue": "Rescue",
}


# -------------------------
# Schema + Validation
# -------------------------

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


# -------------------------
# Route
# -------------------------

@router.post(
    "/{incident_id}",
    summary="Get Claude's assessment of the selected dispatch loadout",
)
@limiter.limit("10/minute")
async def dispatch_advice(
    incident_id: str,
    request: Request,  # Required for slowapi limiter
    body: AdviceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),
):
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=500, detail="AI service not configured")

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    selected_units = db.query(Unit).filter(Unit.id.in_(body.unit_ids)).all()
    if not selected_units:
        raise HTTPException(status_code=400, detail="No valid units provided")

    # -------------------------
    # Build loadout
    # -------------------------

    type_counts = {}
    for u in selected_units:
        label = UNIT_TYPE_LABEL.get(u.unit_type, u.unit_type)
        type_counts[label] = type_counts.get(label, 0) + 1

    loadout_str = ", ".join(f"{count}× {label}" for label, count in type_counts.items())

    already_on = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id,
        Unit.status.in_(["on_scene", "en_route"]),
    ).all()

    on_scene_str = ", ".join(
        UNIT_TYPE_LABEL.get(u.unit_type, u.unit_type) for u in already_on
    ) or "None"

    # -------------------------
    # Fetch system recommendation (if any) so the AI can compare against it
    # -------------------------

    rec_str = "No system recommendation on file"
    try:
        rec = db.query(Recommendation).filter(
            Recommendation.incident_id == incident_id,
        ).order_by(Recommendation.generated_at.desc()).first()

        if rec and rec.unit_recommendations_json:
            recs = json.loads(rec.unit_recommendations_json)
            rec_str = ", ".join(
                f"{r['quantity']}× {UNIT_TYPE_LABEL.get(r['unit_type'], r['unit_type'])}"
                for r in recs
                if isinstance(r, dict) and "unit_type" in r and "quantity" in r
            ) or rec_str
    except Exception:
        pass  # non-fatal — advice will still work without it

    # -------------------------
    # Prompt
    # -------------------------

    prompt = f"""You are a CAL FIRE dispatch advisor AI. Evaluate this unit dispatch in exactly 2 sentences.

INCIDENT: {incident.name}
TYPE: {incident.fire_type.replace('_',' ').title()} | SEVERITY: {incident.severity.upper()}
WIND: {incident.wind_speed_mph or 0:.0f} mph {incident.spread_direction or ''} | HUMIDITY: {incident.humidity_percent or 0:.0f}% | SPREAD RISK: {(incident.spread_risk or '').upper()}
STRUCTURES THREATENED: {incident.structures_threatened or 0}
ALREADY ON SCENE/EN ROUTE: {on_scene_str}
SYSTEM RECOMMENDATION: {rec_str}
PROPOSED DISPATCH: {loadout_str}

Evaluate against the system recommendation AND fire conditions.
Sentence 1: OPTIMAL (matches or exceeds recommendation) / ADEQUATE / SUBOPTIMAL (missing key recommended units)
Sentence 2: single biggest risk or gap, or confirmation if optimal
No extra text."""

    # -------------------------
    # AI Call (with timeout)
    # -------------------------

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        async def ai_call():
            return client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=120,
                messages=[{"role": "user", "content": prompt}],
            )

        message = await asyncio.wait_for(ai_call(), timeout=10)

        advice = message.content[0].text.strip()

    except asyncio.TimeoutError:
        logger.error("Dispatch advice timeout")
        raise HTTPException(status_code=500, detail="AI timeout")

    except Exception as e:
        logger.error(f"Dispatch advice error: {e}")
        raise HTTPException(status_code=500, detail="AI request failed")

    # -------------------------
    # Parse response
    # -------------------------

    assessment = "adequate"
    upper = advice.upper()

    if "OPTIMAL" in upper and "SUB" not in upper:
        assessment = "optimal"
    elif "SUBOPTIMAL" in upper:
        assessment = "suboptimal"

    return {
        "advice": advice,
        "assessment": assessment,
        "loadout": loadout_str,
    }
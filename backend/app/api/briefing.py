from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime, UTC, timedelta
import uuid
import anthropic
import json
import logging
import asyncio

from app.core.database import get_db
from app.core.config import settings
from app.core.security import require_any_role
from app.core.limiter import limiter
from app.models.incident import Incident
from app.models.unit import Unit
from app.models.alert import Alert
from app.models.user import User
from app.models.shift_briefing import ShiftBriefing

router = APIRouter(prefix="/api/briefing", tags=["Briefing"])

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


def _build_prompt(incident, units_on_scene, units_en_route, active_alerts):
    now = datetime.now(UTC).strftime("%Y-%m-%d %H%MZ")

    # Units summary
    def unit_line(u):
        parts = [f"{UNIT_TYPE_LABEL.get(u.unit_type, u.unit_type)} {u.designation}"]
        if u.personnel_count:
            parts.append(f"{u.personnel_count} personnel")
        return ", ".join(parts)

    on_scene_str = "\n".join(f"  - {unit_line(u)}" for u in units_on_scene) or "  - None currently on scene"
    en_route_str = "\n".join(f"  - {unit_line(u)}" for u in units_en_route) or "  - None en route"
    alerts_str   = "\n".join(f"  - [{a.severity.upper()}] {a.title}" for a in active_alerts) or "  - No active alerts"

    return f"""Generate an ICS-style operational briefing for the following wildfire incident. Write in plain English using standard ICS terminology. Use ALLCAPS section headers followed by a colon. Be authoritative, concise, and direct — this document will be handed to a deputy incident commander or read aloud at a briefing.

INCIDENT DATA:
  Name: {incident.name}
  Type: {incident.fire_type.replace('_', ' ').title()}
  Severity: {incident.severity.upper()}
  Status: {incident.status.upper()}
  Location: {incident.latitude:.4f}N, {abs(incident.longitude):.4f}W
  Acres Burned: {incident.acres_burned:,.0f} acres
  Containment: {incident.containment_percent or 0:.0f}%
  Structures Threatened: {incident.structures_threatened or 0}
  Spread Risk: {(incident.spread_risk or 'Unknown').upper()}
  Spread Direction: {incident.spread_direction or 'Unknown'}
  Wind Speed: {incident.wind_speed_mph or 'Unknown'} mph
  Relative Humidity: {incident.humidity_percent or 'Unknown'}%
  Generated: {now}

UNITS ON SCENE:
{on_scene_str}

UNITS EN ROUTE:
{en_route_str}

ACTIVE ALERTS:
{alerts_str}

Generate a complete ICS operational briefing with these sections:
SITUATION, WEATHER, RESOURCES, TACTICS, COMMUNICATIONS, SAFETY

Keep the total briefing under 400 words. Each section should be 2-4 sentences. Do not use bullet points or markdown — write in prose."""


@router.post("/{incident_id}", summary="Generate AI operational briefing for an incident")
@limiter.limit("5/minute")
async def generate_briefing(
    incident_id: str,
    request: Request,  # Required for slowapi limiter
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    api_key = settings.anthropic_api_key
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set in .env")

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    units_on_scene = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id,
        Unit.status == "on_scene",
    ).all()

    units_en_route = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id,
        Unit.status == "en_route",
    ).all()

    active_alerts = db.query(Alert).filter(
        Alert.incident_id == incident_id,
        Alert.is_acknowledged.is_(False),  # Fixed: use .is_(False) for proper SQLAlchemy comparison
    ).all()

    prompt = _build_prompt(incident, units_on_scene, units_en_route, active_alerts)

    try:
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        logger.error(f"Anthropic init failed: {e}")
        raise HTTPException(status_code=500, detail="AI initialization failed")

    # Stream the response back
    async def stream_briefing():
        try:
            async def ai_call():
                return client.messages.stream(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1024,
                    system="You are a CAL FIRE incident commander generating ICS-style operational briefings. Write in plain English using standard ICS terminology. Be authoritative, concise, and direct.",
                    messages=[{"role": "user", "content": prompt}],
                )

            stream_obj = await asyncio.wait_for(ai_call(), timeout=15)

            with stream_obj as stream:
                for text in stream.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"

            yield "data: [DONE]\n\n"

        except asyncio.TimeoutError:
            logger.error("Briefing AI timeout")
            yield f"data: {json.dumps({'error': 'AI timeout'})}\n\n"

        except Exception as e:
            logger.error(f"Briefing stream error: {e}")
            yield f"data: {json.dumps({'error': 'AI stream failed'})}\n\n"

    return StreamingResponse(
        stream_briefing(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

# ── Shift handoff briefing ────────────────────────────────────────────────────

def _build_handoff_prompt(incident: Incident, recent_alerts: list, units: list, period_hours: int) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H%MZ")
    since = (datetime.now(UTC) - timedelta(hours=period_hours)).strftime("%Y-%m-%d %H%MZ")

    alert_lines = "\n".join(
        f"  - [{a.alert_type.upper()}] {a.title} (sev: {a.severity})" for a in recent_alerts
    ) or "  - No alerts in window"

    unit_lines = "\n".join(
        f"  - {u.unit_type} {u.designation} | status: {u.status}"
        for u in units
    ) or "  - None"

    return f"""Generate a shift handoff briefing for an outgoing incident commander.
Cover the last {period_hours} hours ({since} to {now}).

INCIDENT: {incident.name}
Status: {incident.status.upper()} | Severity: {incident.severity.upper()}
Containment: {incident.containment_percent or 0:.0f}% | Acres: {incident.acres_burned or 0:,.0f}
Spread Risk: {(incident.spread_risk or 'unknown').upper()} | Direction: {incident.spread_direction or 'N/A'}
Wind: {incident.wind_speed_mph or 'N/A'} mph | Humidity: {incident.humidity_percent or 'N/A'}%
Structures Threatened: {incident.structures_threatened or 0}

CURRENT RESOURCES:
{unit_lines}

ALERTS IN LAST {period_hours}h:
{alert_lines}

Write a professional ICS shift handoff using ALLCAPS section headers (SITUATION, PERIOD SUMMARY, RESOURCES STATUS, OUTSTANDING ACTIONS, WEATHER OUTLOOK, SAFETY CONCERNS). \
Prose only — no bullets. Max 350 words. Tone: authoritative, direct, factual."""


async def _generate_handoff_text(prompt: str, api_key: str) -> str:
    """Generate full briefing text (non-streaming) for DB storage."""
    client = anthropic.Anthropic(api_key=api_key)

    async def call():
        return client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system="You are a CAL FIRE incident commander generating ICS shift handoff briefings.",
            messages=[{"role": "user", "content": prompt}],
        )

    msg = await asyncio.wait_for(call(), timeout=30)
    return msg.content[0].text.strip()


@router.post("/handoff/{incident_id}", summary="Generate and store a shift handoff briefing")
@limiter.limit("5/minute")
async def generate_handoff_briefing(
    incident_id: str,
    request: Request,
    period_hours: int = 12,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    """
    Generates an AI shift handoff briefing covering the last `period_hours` of
    incident data, stores it in the database, and returns it.
    Can also be triggered automatically on incident close-out.
    """
    api_key = settings.anthropic_api_key
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    since = datetime.now(UTC) - timedelta(hours=period_hours)

    recent_alerts = db.query(Alert).filter(
        Alert.incident_id == incident_id,
    ).all()

    units = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id,
    ).all()

    prompt = _build_handoff_prompt(incident, recent_alerts, units, period_hours)

    try:
        content = await _generate_handoff_text(prompt, api_key)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail="AI timeout generating handoff briefing")
    except Exception as exc:
        logger.error("Handoff briefing error: %s", exc)
        raise HTTPException(status_code=500, detail="AI request failed")

    briefing = ShiftBriefing(
        id=str(uuid.uuid4()),
        incident_id=incident_id,
        generated_at=datetime.now(UTC),
        generated_by=current_user.username,
        trigger="manual",
        period_hours=str(period_hours),
        content=content,
    )
    db.add(briefing)
    db.commit()

    return {
        "briefing_id":   briefing.id,
        "incident_id":   incident_id,
        "incident_name": incident.name,
        "generated_at":  briefing.generated_at.isoformat(),
        "period_hours":  period_hours,
        "trigger":       "manual",
        "content":       content,
    }


@router.get("/handoff/{incident_id}", summary="List stored handoff briefings for an incident")
def list_handoff_briefings(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    briefings = (
        db.query(ShiftBriefing)
        .filter(ShiftBriefing.incident_id == incident_id)
        .order_by(ShiftBriefing.generated_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "briefing_id":  b.id,
            "generated_at": b.generated_at.isoformat(),
            "generated_by": b.generated_by,
            "trigger":      b.trigger,
            "period_hours": b.period_hours,
            "preview":      b.content[:200] + "..." if len(b.content) > 200 else b.content,
        }
        for b in briefings
    ]


@router.get("/handoff/{incident_id}/{briefing_id}", summary="Get a specific stored briefing")
def get_handoff_briefing(
    incident_id: str,
    briefing_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    b = db.query(ShiftBriefing).filter(
        ShiftBriefing.id == briefing_id,
        ShiftBriefing.incident_id == incident_id,
    ).first()
    if not b:
        raise HTTPException(status_code=404, detail="Briefing not found")
    return {
        "briefing_id":  b.id,
        "incident_id":  b.incident_id,
        "generated_at": b.generated_at.isoformat(),
        "generated_by": b.generated_by,
        "trigger":      b.trigger,
        "period_hours": b.period_hours,
        "content":      b.content,
    }

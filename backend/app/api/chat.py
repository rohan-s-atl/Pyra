from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
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

router = APIRouter(prefix="/api/chat", tags=["Chat"])

logger = logging.getLogger(__name__)


# -------------------------
# Schemas
# -------------------------

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


# -------------------------
# Prompt Builder
# -------------------------

def _build_system(incident, units_on, units_en, active_alerts):
    unit_lines = "\n".join(
        f"  - {u.designation} ({u.unit_type.replace('_',' ')}) — {u.status}"
        for u in units_on + units_en
    ) or "  - None assigned"

    alert_lines = "\n".join(
        f"  - [{a.severity.upper()}] {a.title}: {a.description[:100]}"
        for a in active_alerts
    ) or "  - None"

    return f"""You are Pyra, an AI wildfire command support system embedded in an incident command platform.

INCIDENT: {incident.name}
TYPE: {incident.fire_type.replace('_',' ').title()}
SEVERITY: {incident.severity.upper()}
STATUS: {incident.status.upper()}
LOCATION: {incident.latitude:.4f}N, {abs(incident.longitude):.4f}W
ACRES BURNED: {incident.acres_burned:,.0f}
CONTAINMENT: {incident.containment_percent or 0:.0f}%
SPREAD RISK: {(incident.spread_risk or '').upper()}
SPREAD DIRECTION: {incident.spread_direction or 'Unknown'}
WIND: {incident.wind_speed_mph or 0:.1f} mph
HUMIDITY: {incident.humidity_percent or 0:.1f}%
STRUCTURES THREATENED: {incident.structures_threatened or 0}

RESOURCES:
{unit_lines}

ACTIVE ALERTS:
{alert_lines}

Respond concisely using ICS terminology. Do not speculate beyond available data. Keep responses under 200 words unless explicitly asked for more detail."""


# -------------------------
# Route
# -------------------------

@router.post("/{incident_id}", summary="Stream SITREP chat response")
@limiter.limit("10/minute")
async def chat(
    incident_id: str,
    request: Request,  # Required for slowapi limiter
    body: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=500, detail="AI service not configured")

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    units_on = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id,
        Unit.status == "on_scene"
    ).all()

    units_en = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id,
        Unit.status == "en_route"
    ).all()

    alerts = db.query(Alert).filter(
        Alert.incident_id == incident_id,
        Alert.is_acknowledged.is_(False)
    ).all()

    system = _build_system(incident, units_on, units_en, alerts)

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    except Exception as e:
        logger.error(f"Anthropic init failed: {e}")
        raise HTTPException(status_code=500, detail="AI initialization failed")

    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    async def stream():
        try:
            async def ai_call():
                return client.messages.stream(
                    model="claude-sonnet-4-20250514",
                    max_tokens=512,
                    system=system,
                    messages=messages,
                )

            stream_obj = await asyncio.wait_for(ai_call(), timeout=10)

            with stream_obj as s:
                for text in s.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"

            yield "data: [DONE]\n\n"

        except asyncio.TimeoutError:
            logger.error("Chat AI timeout")
            yield f"data: {json.dumps({'error': 'AI timeout'})}\n\n"

        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield f"data: {json.dumps({'error': 'AI stream failed'})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
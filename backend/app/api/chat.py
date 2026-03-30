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

def _build_system(incident: Incident, units_on: list, units_en: list, active_alerts: list) -> str:
    unit_lines = "\n".join(
        f"  - {u.designation} ({u.unit_type.replace('_', ' ')}) — {u.status}"
        for u in units_on + units_en
    ) or "  - None assigned"

    alert_lines = "\n".join(
        f"  - [{a.severity.upper()}] {a.title}: {a.description[:80]}"
        for a in active_alerts
    ) or "  - None"

    acres = f"{incident.acres_burned:,.0f}" if incident.acres_burned else "Unknown"

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
        f"SPREAD DIRECTION: {incident.spread_direction or 'Unknown'}\n"
        f"WIND: {incident.wind_speed_mph or 0:.1f} mph\n"
        f"HUMIDITY: {incident.humidity_percent or 0:.1f}%\n"
        f"STRUCTURES THREATENED: {incident.structures_threatened or 0}\n\n"
        f"RESOURCES (top 20):\n{unit_lines}\n\n"
        f"ACTIVE ALERTS (recent 10):\n{alert_lines}\n\n"
        f"Respond concisely using ICS terminology. Do not speculate beyond available data. "
        f"Keep responses under 200 words unless explicitly asked for more detail."
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

    system   = _build_system(incident, units_on, units_en, alerts)
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    async def stream_generator():
        try:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

            async def do_stream():
                async with client.messages.stream(
                    model="claude-sonnet-4-6",
                    max_tokens=512,
                    system=system,
                    messages=messages,
                ) as s:
                    async for text in s.text_stream:
                        yield f"data: {json.dumps({'text': text})}\n\n"
                yield "data: [DONE]\n\n"

            async for chunk in asyncio.wait_for(
                _collect_stream(do_stream()),
                timeout=_CHAT_TIMEOUT,
            ):
                yield chunk

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


async def _collect_stream(agen):
    """Adapter: yield from an async generator so asyncio.wait_for can wrap it."""
    async for item in agen:
        yield item

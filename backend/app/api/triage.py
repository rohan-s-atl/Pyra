from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import anthropic
import logging
import asyncio

from app.core.database import get_db
from app.core.config import settings
from app.core.security import require_any_role
from app.models.alert import Alert
from app.models.incident import Incident
from app.models.user import User

from app.core.limiter import limiter

router = APIRouter(prefix="/api/triage", tags=["Triage"])

logger = logging.getLogger(__name__)

# Simple in-memory cache
_triage_cache: dict = {}
MAX_CACHE_SIZE = 1000


@router.get("/{alert_id}", summary="Get Claude triage score for an alert")
@limiter.limit("15/minute")
async def triage_alert(
    alert_id: str,
    request: Request,  # Required for slowapi limiter
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    # -------------------------
    # Cache hit
    # -------------------------
    if alert_id in _triage_cache:
        return _triage_cache[alert_id]

    if not settings.anthropic_api_key:
        raise HTTPException(status_code=500, detail="AI service not configured")

    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    incident = None
    if alert.incident_id:
        incident = db.query(Incident).filter(Incident.id == alert.incident_id).first()

    inc_context = ""
    if incident:
        inc_context = (
            f"Incident: {incident.name} | Severity: {incident.severity} | "
            f"Wind: {incident.wind_speed_mph or 0:.0f}mph | "
            f"Humidity: {incident.humidity_percent or 0:.0f}% | "
            f"Containment: {incident.containment_percent or 0:.0f}%"
        )

    prompt = f"""You are a CAL FIRE incident support AI. Triage this alert in exactly ONE sentence (max 15 words).

Alert Type: {alert.alert_type}
Severity: {alert.severity}
Title: {alert.title}
Description: {alert.description}
{inc_context}

Respond with: urgency (IMMEDIATE/MONITOR/LOW) + action. No extra text."""

    # -------------------------
    # AI Call (with timeout)
    # -------------------------

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        async def ai_call():
            return client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=60,
                messages=[{"role": "user", "content": prompt}],
            )

        message = await asyncio.wait_for(ai_call(), timeout=10)

        triage_text = message.content[0].text.strip()

    except asyncio.TimeoutError:
        logger.error("Triage AI timeout")
        raise HTTPException(status_code=500, detail="AI timeout")

    except Exception as e:
        logger.error(f"Triage AI error: {e}")
        raise HTTPException(status_code=500, detail="AI request failed")

    # -------------------------
    # Parse urgency
    # -------------------------

    urgency = "monitor"
    text_upper = triage_text.upper()

    if "IMMEDIATE" in text_upper:
        urgency = "immediate"
    elif "LOW" in text_upper:
        urgency = "low"

    result = {
        "alert_id": alert_id,
        "triage": triage_text,
        "urgency": urgency,
    }

    # -------------------------
    # Cache (bounded)
    # -------------------------

    if len(_triage_cache) >= MAX_CACHE_SIZE:
        _triage_cache.pop(next(iter(_triage_cache)))

    _triage_cache[alert_id] = result

    return result
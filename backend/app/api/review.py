from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import anthropic
import json
import logging
import asyncio
from datetime import datetime, UTC

from app.core.database import get_db
from app.core.config import settings
from app.core.security import require_commander
from app.models.incident import Incident
from app.models.audit_log import AuditLog
from app.models.unit import Unit
from app.models.alert import Alert
from app.models.user import User

from app.core.limiter import limiter

router = APIRouter(prefix="/api/review", tags=["Review"])

logger = logging.getLogger(__name__)


# -------------------------
# Timeline Builder
# -------------------------

def _build_timeline(incident_id: str, db: Session) -> str:
    entries = (
        db.query(AuditLog)
        .filter(AuditLog.incident_id == incident_id)
        .order_by(AuditLog.timestamp.asc())
        .all()
    )

    if not entries:
        return "No dispatch actions recorded for this incident."

    lines = []
    for e in entries:
        t = e.timestamp.strftime("%H%MZ")
        units = f" — Units: {e.unit_ids}" if e.unit_ids else ""
        lines.append(
            f"  {t} [{e.action}] by {e.actor} ({e.actor_role}): {e.details or ''}{units}"
        )

    return "\n".join(lines)


# -------------------------
# Route (Commander Only)
# -------------------------

@router.post(
    "/{incident_id}",
    summary="Generate post-incident lessons-learned review (Commander only)",
)
@limiter.limit("5/minute")
async def post_incident_review(
    incident_id: str,
    request: Request,  # Required for slowapi limiter
    db: Session = Depends(get_db),
    current_user: User = Depends(require_commander),
):
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=500, detail="AI service not configured")

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # -------------------------
    # Gather data
    # -------------------------

    total_units = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id
    ).count()

    total_alerts = db.query(Alert).filter(
        Alert.incident_id == incident_id
    ).count()

    acked_alerts = db.query(Alert).filter(
        Alert.incident_id == incident_id,
        Alert.is_acknowledged.is_(True)
    ).count()

    timeline = _build_timeline(incident_id, db)

    duration_hrs = None
    if incident.started_at:
        try:
            started = incident.started_at
            # Handle naive datetimes stored without timezone info
            if started.tzinfo is None:
                from datetime import timezone
                started = started.replace(tzinfo=timezone.utc)
            duration_hrs = round(
                (datetime.now(UTC) - started).total_seconds() / 3600, 1
            )
        except Exception:
            duration_hrs = None

    # -------------------------
    # Prompt
    # -------------------------

    prompt = f"""You are a CAL FIRE after-action review specialist. Generate a structured post-incident lessons-learned document.

INCIDENT DATA:
  Name: {incident.name}
  Type: {incident.fire_type.replace('_', ' ').title()}
  Final Severity: {incident.severity.upper()}
  Final Status: {incident.status.upper()}
  Acres Burned: {incident.acres_burned:,.0f}
  Peak Spread Risk: {(incident.spread_risk or 'Unknown').upper()}
  Final Containment: {incident.containment_percent or 0:.0f}%
  Structures Threatened: {incident.structures_threatened or 0}
  Duration: {duration_hrs or 'Unknown'} hours
  Total Units Deployed: {total_units}
  Total Alerts Generated: {total_alerts} ({acked_alerts} resolved)

DISPATCH TIMELINE:
{timeline}

Generate sections:
INCIDENT SUMMARY, TIMELINE ANALYSIS, RESOURCE DEPLOYMENT ASSESSMENT, ALERT RESPONSE EFFECTIVENESS, LESSONS LEARNED, RECOMMENDATIONS FOR FUTURE INCIDENTS

Keep total length under 600 words. No bullet points."""

    # -------------------------
    # AI Client
    # -------------------------

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    except Exception as e:
        logger.error(f"Anthropic init failed: {e}")
        raise HTTPException(status_code=500, detail="AI initialization failed")

    # -------------------------
    # Stream response (with timeout)
    # -------------------------

    async def stream():
        try:
            async def ai_call():
                return client.messages.stream(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1200,
                    system="You are a CAL FIRE after-action review specialist. Be analytical and concise.",
                    messages=[{"role": "user", "content": prompt}],
                )

            stream_obj = await asyncio.wait_for(ai_call(), timeout=15)

            with stream_obj as s:
                for text in s.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"

            yield "data: [DONE]\n\n"

        except asyncio.TimeoutError:
            logger.error("Review AI timeout")
            yield f"data: {json.dumps({'error': 'AI timeout'})}\n\n"

        except Exception as e:
            logger.error(f"Review stream error: {e}")
            yield f"data: {json.dumps({'error': 'AI stream failed'})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
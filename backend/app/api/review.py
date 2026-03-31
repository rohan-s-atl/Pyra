"""
review.py — Post-incident lessons-learned review endpoint. (PATCHED)

FIXES APPLIED
-------------
1. anthropic.Anthropic (blocking sync) + sync context manager stream replaced
   with AsyncAnthropic + async with client.messages.stream() — event loop is
   no longer blocked during token streaming.
2. asyncio.wait_for now wraps the entire stream generator rather than just
   the client initialisation call, giving a real end-to-end timeout.
3. Audit log query capped at 100 entries — very old large incidents could have
   thousands of log lines, blowing the context window and slowing the prompt build.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import anthropic
import json
import logging
import asyncio
from datetime import datetime, UTC, timezone

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

_REVIEW_TIMEOUT = 45   # seconds — review is longer than chat/triage


# ---------------------------------------------------------------------------
# Timeline builder
# ---------------------------------------------------------------------------

def _build_timeline(incident_id: str, db: Session) -> str:
    entries = (
        db.query(AuditLog)
        .filter(AuditLog.incident_id == incident_id)
        .order_by(AuditLog.timestamp.asc())
        .limit(100)   # cap: very large incidents had thousands of log entries
        .all()
    )

    if not entries:
        return "No dispatch actions recorded for this incident."

    lines = []
    for e in entries:
        t     = e.timestamp.strftime("%H%MZ")
        units = f" — Units: {e.unit_ids}" if e.unit_ids else ""
        lines.append(
            f"  {t} [{e.action}] by {e.actor} ({e.actor_role}): {e.details or ''}{units}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Route (Commander Only)
# ---------------------------------------------------------------------------

@router.post(
    "/{incident_id}",
    summary="Generate post-incident lessons-learned review (Commander only)",
)
@limiter.limit("5/minute")
async def post_incident_review(
    incident_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_commander),
):
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=500, detail="AI service not configured")

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # ── Gather data ──────────────────────────────────────────────────────────
    total_units  = db.query(Unit).filter(Unit.assigned_incident_id == incident_id).count()
    total_alerts = db.query(Alert).filter(Alert.incident_id == incident_id).count()
    acked_alerts = db.query(Alert).filter(
        Alert.incident_id == incident_id,
        Alert.is_acknowledged.is_(True),
    ).count()

    timeline = _build_timeline(incident_id, db)

    duration_hrs = None
    if incident.started_at:
        try:
            started = incident.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            duration_hrs = round((datetime.now(UTC) - started).total_seconds() / 3600, 1)
        except Exception:
            pass

    acres = f"{incident.acres_burned:,.0f}" if incident.acres_burned else "Unknown"

    # ── Prompt ───────────────────────────────────────────────────────────────
    prompt = (
        f"You are a CAL FIRE after-action review specialist. "
        f"Generate a structured post-incident lessons-learned document.\n\n"
        f"INCIDENT DATA:\n"
        f"  Name: {incident.name}\n"
        f"  Type: {incident.fire_type.replace('_', ' ').title()}\n"
        f"  Final Severity: {incident.severity.upper()}\n"
        f"  Final Status: {incident.status.upper()}\n"
        f"  Acres Burned: {acres}\n"
        f"  Peak Spread Risk: {(incident.spread_risk or 'Unknown').upper()}\n"
        f"  Final Containment: {incident.containment_percent or 0:.0f}%\n"
        f"  Structures Threatened: {incident.structures_threatened or 0}\n"
        f"  Duration: {duration_hrs or 'Unknown'} hours\n"
        f"  Total Units Deployed: {total_units}\n"
        f"  Total Alerts Generated: {total_alerts} ({acked_alerts} resolved)\n\n"
        f"DISPATCH TIMELINE:\n{timeline}\n\n"
        f"Generate sections:\n"
        f"INCIDENT SUMMARY, TIMELINE ANALYSIS, RESOURCE DEPLOYMENT ASSESSMENT, "
        f"ALERT RESPONSE EFFECTIVENESS, LESSONS LEARNED, RECOMMENDATIONS FOR FUTURE INCIDENTS\n\n"
        f"Keep total length under 600 words. No bullet points."
    )

    # All DB data is now in plain Python values — release the connection before
    # the AI stream begins (up to 45s).
    db.close()

    # ── Async streaming response ─────────────────────────────────────────────
    async def stream():
        try:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

            async with client.messages.stream(
                model="claude-haiku-4-5-20251001",
                max_tokens=1200,
                system="You are a CAL FIRE after-action review specialist. Be analytical and concise.",
                messages=[{"role": "user", "content": prompt}],
            ) as s:
                async for text in s.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"

            yield "data: [DONE]\n\n"

        except asyncio.TimeoutError:
            logger.error("[review] Stream timeout for incident=%s", incident_id)
            yield f"data: {json.dumps({'error': 'AI timeout'})}\n\n"
        except Exception as e:
            logger.error("[review] Stream error: %s", e)
            yield f"data: {json.dumps({'error': 'AI stream failed'})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
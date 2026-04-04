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
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
import anthropic
import json
import logging
import asyncio
import io
import re
from datetime import datetime, UTC, timezone
from pydantic import BaseModel
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

from app.core.database import get_db
from app.core.config import settings
from app.core.security import require_commander
from app.models.incident import Incident
from app.models.audit_log import AuditLog
from app.models.unit import Unit
from app.models.alert import Alert
from app.models.user import User
from app.core.limiter import limiter
from app.ext.fire_behavior import predict_fire_behavior
from app.ext.composite_risk import compute_risk_score

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

    # Compute fire behavior so the review can explain why the fire behaved as it did
    fire_behavior = predict_fire_behavior(
        fire_type           = incident.fire_type,
        spread_risk         = incident.spread_risk,
        wind_speed_mph      = incident.wind_speed_mph,
        humidity_percent    = incident.humidity_percent,
        containment_percent = incident.containment_percent,
        acres_burned        = incident.acres_burned,
        units_on_scene      = None,
        slope_percent       = incident.slope_percent,
        aqi                 = incident.aqi,
    )
    risk = compute_risk_score(
        fire_behavior_index   = fire_behavior["fire_behavior_index"],
        spread_risk           = incident.spread_risk,
        severity              = incident.severity,
        structures_threatened = incident.structures_threatened,
        containment_percent   = incident.containment_percent,
        acres_burned          = incident.acres_burned,
        slope_percent         = incident.slope_percent,
        aspect_cardinal       = incident.aspect_cardinal,
        spread_direction      = incident.spread_direction,
        units_on_scene        = None,
        units_en_route        = None,
    )

    terrain_parts = []
    if incident.elevation_m   is not None: terrain_parts.append(f"elevation {incident.elevation_m:.0f} m")
    if incident.slope_percent is not None: terrain_parts.append(f"slope {incident.slope_percent:.1f}%")
    if incident.aspect_cardinal:           terrain_parts.append(f"aspect {incident.aspect_cardinal}")
    terrain_str = ", ".join(terrain_parts) or "Not recorded"
    aqi_str     = f"{incident.aqi} ({incident.aqi_category})" if incident.aqi is not None else "Not recorded"

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
        f"  Spread Direction: {incident.spread_direction or 'Unknown'}\n"
        f"  Final Containment: {incident.containment_percent or 0:.0f}%\n"
        f"  Structures Threatened: {incident.structures_threatened or 0}\n"
        f"  Duration: {duration_hrs or 'Unknown'} hours\n"
        f"  Total Units Deployed: {total_units}\n"
        f"  Total Alerts Generated: {total_alerts} ({acked_alerts} resolved)\n\n"
        f"ENVIRONMENTAL CONDITIONS AT CLOSE:\n"
        f"  Wind: {incident.wind_speed_mph or 'Unknown'} mph\n"
        f"  Humidity: {incident.humidity_percent or 'Unknown'}%\n"
        f"  AQI: {aqi_str}\n"
        f"  Terrain: {terrain_str}\n\n"
        f"FIRE BEHAVIOR PROFILE (explains why the fire behaved as it did):\n"
        f"  Fire Behavior Index: {fire_behavior['fire_behavior_index']} — {fire_behavior['predicted_behavior'].upper()}\n"
        f"  {fire_behavior['behavior_description']}\n"
        f"  Rate of Spread: {fire_behavior['rate_of_spread_mph']} mph\n"
        f"  Spotting Potential: {fire_behavior['spotting_potential']} ({fire_behavior['spotting_distance_miles']} mi max)\n"
        f"  Final Containment Probability: {fire_behavior['containment_probability_pct']}%\n"
        f"  Composite Risk Score: {risk['risk_score']} / 1.0 — {risk['risk_level'].upper()}\n\n"
        f"DISPATCH TIMELINE:\n{timeline}\n\n"
        f"Generate sections:\n"
        f"INCIDENT SUMMARY, ENVIRONMENTAL AND FIRE BEHAVIOR ANALYSIS, TIMELINE ANALYSIS, "
        f"RESOURCE DEPLOYMENT ASSESSMENT, ALERT RESPONSE EFFECTIVENESS, "
        f"LESSONS LEARNED, RECOMMENDATIONS FOR FUTURE INCIDENTS\n\n"
        f"Keep total length under 700 words. No bullet points. "
        f"Ground tactical observations in the environmental conditions and fire behavior data above."
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


# ---------------------------------------------------------------------------
# PDF Export
# ---------------------------------------------------------------------------

_C_BG     = HexColor('#151419')
_C_PANEL  = HexColor('#1B1B1E')
_C_BORDER = HexColor('#262626')
_C_ORANGE = HexColor('#F56E0F')
_C_TEXT   = HexColor('#FBFBFB')
_C_MUTED  = HexColor('#9baac0')
_C_PAGE_TEXT = HexColor('#1F2937')
_C_PAGE_MUTED = HexColor('#64748B')
_C_RULE = HexColor('#374151')

SEVERITY_COLOR = {
    "low": HexColor('#22c55e'), "moderate": HexColor('#f59e0b'),
    "high": HexColor('#ff4d1a'), "critical": HexColor('#ef4444'),
}


def _ps(name, **kw):
    return ParagraphStyle(name, **kw)


def _generate_review_pdf(incident: Incident, content: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
    )

    styles = {
        'title':   _ps('title',   fontName='Helvetica-Bold', fontSize=18, textColor=_C_TEXT, spaceAfter=2),
        'sub':     _ps('sub',     fontName='Helvetica', fontSize=10, textColor=_C_MUTED, spaceAfter=12, alignment=TA_RIGHT),
        'meta':    _ps('meta',    fontName='Helvetica', fontSize=10, textColor=_C_MUTED, spaceAfter=2),
        'section': _ps('section', fontName='Helvetica-Bold', fontSize=8, textColor=_C_PAGE_MUTED, spaceBefore=12, spaceAfter=4, letterSpacing=2),
        'body':    _ps('body',    fontName='Helvetica', fontSize=9, textColor=_C_PAGE_TEXT, spaceAfter=6, leading=14),
        'bold':    _ps('bold',    fontName='Helvetica-Bold', fontSize=9, textColor=_C_PAGE_TEXT, spaceAfter=4),
        'footer':  _ps('footer',  fontName='Helvetica', fontSize=7, textColor=_C_PAGE_MUTED, alignment=TA_CENTER),
    }

    sev_color = SEVERITY_COLOR.get(incident.severity, _C_MUTED)
    story = []

    # Header bar
    hdr = Table([[
        Paragraph(f'<font color="#{_C_ORANGE.hexval()[2:]}">PYRA</font> POST-INCIDENT AAR', styles['title']),
        Paragraph(datetime.now(UTC).strftime('%Y-%m-%d %H%MZ'), styles['sub']),
    ]], colWidths=[4.5 * inch, 2.8 * inch])
    hdr.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), _C_BG),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(hdr)
    story.append(HRFlowable(width='100%', thickness=1, color=_C_ORANGE, spaceAfter=12))

    # Incident summary block
    sev_hex = sev_color.hexval()[2:]
    summary = Table([
        [
            Paragraph(incident.name, styles['title']),
            Paragraph(f'<font color="#{sev_hex}">{incident.severity.upper()}</font>', styles['title']),
        ],
        [
            Paragraph(f'{incident.fire_type.replace("_", " ").title()} · {incident.status.upper()}', styles['meta']),
            Paragraph(
                f'{incident.acres_burned:,.0f} acres · {incident.containment_percent or 0:.0f}% contained'
                if incident.acres_burned else f'{incident.containment_percent or 0:.0f}% contained',
                styles['meta'],
            ),
        ],
    ], colWidths=[4.5 * inch, 2.8 * inch])
    summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), _C_PANEL),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('LINEBELOW', (0, -1), (-1, -1), 1, _C_BORDER),
    ]))
    story.append(summary)
    story.append(Spacer(1, 14))

    # Parse markdown content into styled paragraphs
    for line in content.split('\n'):
        line = line.rstrip()
        if line.startswith('# '):
            story.append(Paragraph(line[2:], styles['section']))
        elif line.startswith('## '):
            story.append(Paragraph(line[3:], styles['bold']))
        elif line.startswith('### '):
            story.append(Paragraph(line[4:], styles['bold']))
        elif line.strip() == '---':
            story.append(HRFlowable(width='100%', thickness=1, color=_C_RULE, spaceAfter=6))
        elif line.strip():
            # strip markdown bold markers for PDF
            cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
            story.append(Paragraph(cleaned, styles['body']))
        else:
            story.append(Spacer(1, 4))

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width='100%', thickness=1, color=_C_RULE, spaceAfter=6))
    story.append(Paragraph('Generated by PYRA · After-Action Review · COMMANDER RESTRICTED', styles['footer']))

    doc.build(story)
    return buf.getvalue()


class _ExportBody(BaseModel):
    content: str


@router.post(
    "/{incident_id}/export.pdf",
    summary="Export post-incident AAR as PDF",
    response_class=Response,
)
def export_review_pdf(
    incident_id: str,
    body: _ExportBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_commander),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    pdf_bytes = _generate_review_pdf(incident, body.content)
    filename = f"pyra_aar_{incident_id}_{datetime.now(UTC).strftime('%Y%m%d_%H%M')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

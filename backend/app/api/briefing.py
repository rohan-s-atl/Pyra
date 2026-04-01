"""
briefing.py — AI operational briefing endpoints.

PATCH: generate_handoff_briefing now applies the `since` time filter to
the alert query. Previously `since` was computed but never used — the
handoff briefing fetched ALL alerts ever created instead of only those
in the last `period_hours` window.
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime, UTC, timedelta
import uuid
import anthropic
import json
import logging
import asyncio
import io
from pydantic import BaseModel
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

from app.core.database import get_db, SessionLocal
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

C_BG       = HexColor('#151419')
C_PANEL    = HexColor('#1B1B1E')
C_BORDER   = HexColor('#262626')
C_ORANGE   = HexColor('#F56E0F')
C_RED      = HexColor('#ef4444')
C_YELLOW   = HexColor('#facc15')
C_GREEN    = HexColor('#4ade80')
C_TEXT     = HexColor('#FBFBFB')
C_MUTED    = HexColor('#878787')

SEVERITY_COLOR = {
    'critical': C_RED, 'high': C_ORANGE, 'moderate': C_YELLOW, 'low': C_GREEN,
}

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


class BriefingExportBody(BaseModel):
    content: str


def _fmt_time(dt):
    if not dt:
        return '—'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.strftime('%Y-%m-%d %H%MZ')


def _fmt_num(v, decimals=1, suffix=''):
    if v is None:
        return '—'
    return f"{v:,.{decimals}f}{suffix}"


def _parse_briefing_sections(content: str) -> list[tuple[str, str]]:
    sections = []
    current_title = None
    current_lines = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.endswith(':') and line[:-1].replace(' ', '').replace('-', '').isupper():
            if current_title:
                sections.append((current_title, ' '.join(current_lines).strip()))
            current_title = line[:-1]
            current_lines = []
        else:
            current_lines.append(line)
    if current_title:
        sections.append((current_title, ' '.join(current_lines).strip()))
    return sections


def generate_briefing_pdf(incident: Incident, content: str, generated_by: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
    )

    def style(name, **kw):
        return ParagraphStyle(name, **kw)

    styles = {
        'title':    style('title',   fontName='Helvetica-Bold', fontSize=18, textColor=C_TEXT, spaceAfter=2),
        'subtitle': style('subtitle', fontName='Helvetica', fontSize=10, textColor=C_MUTED, spaceAfter=12, alignment=TA_RIGHT),
        'meta':     style('meta', fontName='Helvetica', fontSize=10, textColor=C_MUTED, spaceAfter=2),
        'section':  style('section', fontName='Helvetica-Bold', fontSize=8, textColor=C_MUTED, spaceBefore=12, spaceAfter=4, letterSpacing=2),
        'body':     style('body', fontName='Helvetica', fontSize=9, textColor=C_TEXT, spaceAfter=8, leading=14),
        'label':    style('label', fontName='Helvetica-Bold', fontSize=8, textColor=C_MUTED),
        'value':    style('value', fontName='Helvetica', fontSize=9, textColor=C_TEXT),
        'footer':   style('footer', fontName='Helvetica', fontSize=7, textColor=C_MUTED, alignment=TA_CENTER),
    }

    sev_color = SEVERITY_COLOR.get(incident.severity, C_MUTED)
    story = []

    header = Table([[
        Paragraph(f'<font color="#{C_ORANGE.hexval()[2:]}">PYRA</font> ICS OPERATIONAL BRIEFING', styles['title']),
        Paragraph(f'ICS-202 | {_fmt_time(datetime.now(UTC))}', styles['subtitle']),
    ]], colWidths=[4.5 * inch, 2.8 * inch])
    header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), C_BG),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(header)
    story.append(HRFlowable(width='100%', thickness=1, color=C_ORANGE, spaceAfter=12))

    summary = Table([
        [
            Paragraph(incident.name, styles['title']),
            Paragraph(f'<font color="#{sev_color.hexval()[2:]}">{incident.severity.upper()}</font>', styles['title']),
        ],
        [
            Paragraph(f'{incident.fire_type.replace("_", " ").title()} · {incident.status.upper()}', styles['meta']),
            Paragraph(f'{_fmt_num(incident.acres_burned, 0)} acres · {_fmt_num(incident.containment_percent, 0, "% contained")}', styles['meta']),
        ],
    ], colWidths=[4.5 * inch, 2.8 * inch])
    summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), C_PANEL),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('LINEBELOW', (0, -1), (-1, -1), 1, C_BORDER),
    ]))
    story.append(summary)
    story.append(Spacer(1, 10))

    situation_rows = [[
        Paragraph('LOCATION', styles['label']), Paragraph(f'{incident.latitude:.4f}N, {abs(incident.longitude):.4f}W', styles['value']),
        Paragraph('SPREAD RISK', styles['label']), Paragraph((incident.spread_risk or '—').upper(), styles['value']),
    ], [
        Paragraph('ACRES BURNED', styles['label']), Paragraph(_fmt_num(incident.acres_burned, 1, ' ac'), styles['value']),
        Paragraph('SPREAD DIRECTION', styles['label']), Paragraph((incident.spread_direction or '—').upper(), styles['value']),
    ], [
        Paragraph('CONTAINMENT', styles['label']), Paragraph(_fmt_num(incident.containment_percent, 0, '%'), styles['value']),
        Paragraph('WIND SPEED', styles['label']), Paragraph(_fmt_num(incident.wind_speed_mph, 1, ' mph'), styles['value']),
    ], [
        Paragraph('STRUCTURES AT RISK', styles['label']), Paragraph(str(incident.structures_threatened or '—'), styles['value']),
        Paragraph('HUMIDITY', styles['label']), Paragraph(_fmt_num(incident.humidity_percent, 1, '%'), styles['value']),
    ]]
    story.append(Paragraph('SITUATION SNAPSHOT', styles['section']))
    situation = Table(situation_rows, colWidths=[1.5 * inch, 2.0 * inch, 1.5 * inch, 2.3 * inch])
    situation.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), C_PANEL),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [C_PANEL, HexColor('#1e1e22')]),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('LINEBELOW', (0, -1), (-1, -1), 1, C_BORDER),
    ]))
    story.append(situation)
    story.append(Spacer(1, 10))

    for title, body in _parse_briefing_sections(content):
        story.append(Paragraph(title, styles['section']))
        story.append(Paragraph(body, styles['body']))

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width='100%', thickness=1, color=C_BORDER, spaceBefore=12, spaceAfter=8))
    story.append(Paragraph(
        f'Generated by Pyra Wildfire Command · {_fmt_time(datetime.now(UTC))} · Operator: {generated_by} · CONFIDENTIAL — OFFICIAL USE ONLY',
        styles['footer']
    ))

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C_BG)
        canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    buf.seek(0)
    return buf.read()


def _build_prompt(incident, units_on_scene, units_en_route, active_alerts):
    now = datetime.now(UTC).strftime("%Y-%m-%d %H%MZ")

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
    request: Request,
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
        Unit.assigned_incident_id == incident_id, Unit.status == "on_scene"
    ).all()
    units_en_route = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id, Unit.status == "en_route"
    ).all()
    active_alerts = db.query(Alert).filter(
        Alert.incident_id == incident_id,
        Alert.is_acknowledged.is_(False),
    ).order_by(Alert.created_at.desc()).limit(10).all()

    # Build prompt while session is open, then close before streaming (up to 30s AI call)
    prompt = _build_prompt(incident, units_on_scene, units_en_route, active_alerts)
    db.close()

    async def stream_briefing():
        try:
            client = anthropic.AsyncAnthropic(api_key=api_key)
            async with client.messages.stream(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=(
                    "You are a CAL FIRE incident commander generating ICS-style operational briefings. "
                    "Write in plain English using standard ICS terminology. Be authoritative, concise, and direct."
                ),
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"
            yield "data: [DONE]\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'error': 'AI timeout'})}\n\n"
        except Exception as e:
            logger.error("Briefing stream error: %s", e)
            yield f"data: {json.dumps({'error': 'AI stream failed'})}\n\n"

    return StreamingResponse(
        stream_briefing(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{incident_id}/export.pdf", summary="Export operational briefing as PDF")
def export_briefing_pdf(
    incident_id: str,
    body: BriefingExportBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Briefing content is required")

    pdf_bytes = generate_briefing_pdf(incident, body.content, current_user.username)
    filename = (
        f"pyra_ics_briefing_{incident.name.replace(' ', '_').lower()}"
        f"_{datetime.now(UTC).strftime('%Y%m%d_%H%M')}.pdf"
    )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _build_handoff_prompt(incident: Incident, recent_alerts: list, units: list, period_hours: int) -> str:
    now   = datetime.now(UTC).strftime("%Y-%m-%d %H%MZ")
    since = (datetime.now(UTC) - timedelta(hours=period_hours)).strftime("%Y-%m-%d %H%MZ")

    alert_lines = "\n".join(
        f"  - [{a.alert_type.upper()}] {a.title} (sev: {a.severity})" for a in recent_alerts
    ) or "  - No alerts in window"
    unit_lines = "\n".join(
        f"  - {u.unit_type} {u.designation} | status: {u.status}" for u in units
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
    client = anthropic.AsyncAnthropic(api_key=api_key)
    msg = await asyncio.wait_for(
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system="You are a CAL FIRE incident commander generating ICS shift handoff briefings.",
            messages=[{"role": "user", "content": prompt}],
        ),
        timeout=30,
    )
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
    api_key = settings.anthropic_api_key
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    since = datetime.now(UTC) - timedelta(hours=period_hours)

    recent_alerts = db.query(Alert).filter(
        Alert.incident_id == incident_id,
        Alert.created_at >= since,
    ).all()

    units = db.query(Unit).filter(Unit.assigned_incident_id == incident_id).all()

    # Build prompt and snapshot incident name before closing the session
    prompt        = _build_handoff_prompt(incident, recent_alerts, units, period_hours)
    incident_name = incident.name
    username      = current_user.username
    db.close()  # Release connection before the AI call (up to 30s)

    try:
        content = await _generate_handoff_text(prompt, api_key)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail="AI timeout generating handoff briefing")
    except Exception as exc:
        logger.error("Handoff briefing error: %s", exc)
        raise HTTPException(status_code=500, detail="AI request failed")

    # Re-open session only to persist the result
    db2 = SessionLocal()
    try:
        briefing = ShiftBriefing(
            id=str(uuid.uuid4()),
            incident_id=incident_id,
            generated_at=datetime.now(UTC),
            generated_by=username,
            trigger="manual",
            period_hours=str(period_hours),
            content=content,
        )
        db2.add(briefing)
        db2.commit()
        briefing_id  = briefing.id
        generated_at = briefing.generated_at.isoformat()
    finally:
        db2.close()

    return {
        "briefing_id":   briefing_id,
        "incident_id":   incident_id,
        "incident_name": incident_name,
        "generated_at":  generated_at,
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

"""
report.py — PDF incident report generator.

PATCH: Replaced db.query(Unit).all() with a filtered query scoped to
the incident. Previously every report fetched the entire fleet into memory
then filtered in Python.
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime, UTC
import io

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.incident import Incident
from app.models.unit import Unit
from app.models.alert import Alert
from app.models.user import User

router = APIRouter(prefix="/api/report", tags=["Report"])

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
    'engine': 'Engine', 'hand_crew': 'Hand Crew', 'dozer': 'Dozer',
    'water_tender': 'Water Tender', 'helicopter': 'Helicopter',
    'air_tanker': 'Air Tanker', 'command_unit': 'Command Unit', 'rescue': 'Rescue',
}


def _fmt_time(dt):
    if not dt: return '—'
    return dt.strftime('%Y-%m-%d %H%MZ')


def _fmt_num(v, decimals=1, suffix=''):
    if v is None: return '—'
    return f"{v:,.{decimals}f}{suffix}"


def generate_report_pdf(incident: Incident, units: list, alerts: list, generated_by: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.6*inch, rightMargin=0.6*inch,
        topMargin=0.6*inch, bottomMargin=0.6*inch,
    )

    def style(name, **kw):
        return ParagraphStyle(name, **kw)

    S = {
        'title':    style('title',   fontName='Helvetica-Bold',   fontSize=18, textColor=C_TEXT,   spaceAfter=2),
        'subtitle': style('sub',     fontName='Helvetica',        fontSize=10, textColor=C_MUTED,  spaceAfter=12),
        'section':  style('section', fontName='Helvetica-Bold',   fontSize=8,  textColor=C_MUTED,  spaceBefore=12, spaceAfter=4, letterSpacing=2),
        'body':     style('body',    fontName='Helvetica',        fontSize=9,  textColor=C_TEXT,   spaceAfter=4, leading=14),
        'label':    style('label',   fontName='Helvetica-Bold',   fontSize=8,  textColor=C_MUTED),
        'value':    style('value',   fontName='Helvetica',        fontSize=9,  textColor=C_TEXT),
        'footer':   style('footer',  fontName='Helvetica',        fontSize=7,  textColor=C_MUTED,  alignment=TA_CENTER),
    }

    story = []
    sev_color = SEVERITY_COLOR.get(incident.severity, C_MUTED)

    header_data = [[
        Paragraph(f'<font color="#{C_ORANGE.hexval()[2:]}">PYRA</font> INCIDENT REPORT', S['title']),
        Paragraph(f'ICS-209 | {_fmt_time(datetime.now(UTC))}', S['subtitle']),
    ]]
    header_table = Table(header_data, colWidths=[4.5*inch, 2.8*inch])
    header_table.setStyle(TableStyle([
        ('BACKGROUND',  (0,0), (-1,-1), C_BG),
        ('BOTTOMPADDING',(0,0),(-1,-1), 8),
        ('TOPPADDING',  (0,0),(-1,-1), 8),
        ('LEFTPADDING', (0,0),(-1,-1), 10),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width='100%', thickness=1, color=C_ORANGE, spaceAfter=12))

    sev_label    = incident.severity.upper()
    status_label = incident.status.upper()
    summary_data = [
        [
            Paragraph(incident.name, S['title']),
            Paragraph(f'<font color="#{sev_color.hexval()[2:]}">{sev_label}</font>', S['title']),
        ],
        [
            Paragraph(f'{incident.fire_type.replace("_"," ").title()} · {status_label}', S['subtitle']),
            Paragraph(f'{_fmt_num(incident.acres_burned, 0)} acres · {_fmt_num(incident.containment_percent, 0, "% contained")}', S['subtitle']),
        ],
    ]
    summary_table = Table(summary_data, colWidths=[4.5*inch, 2.8*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND',   (0,0),(-1,-1), C_PANEL),
        ('TOPPADDING',   (0,0),(-1,-1), 6),
        ('BOTTOMPADDING',(0,0),(-1,-1), 6),
        ('LEFTPADDING',  (0,0),(-1,-1), 10),
        ('RIGHTPADDING', (0,0),(-1,-1), 10),
        ('LINEBELOW',    (0,-1),(-1,-1), 1, C_BORDER),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph('SITUATION', S['section']))
    sit_data = [
        ['LOCATION',          f'{incident.latitude:.4f}N, {abs(incident.longitude):.4f}W',
         'SPREAD RISK',        (incident.spread_risk or '—').upper()],
        ['ACRES BURNED',      _fmt_num(incident.acres_burned, 1, ' ac'),
         'SPREAD DIRECTION',   (incident.spread_direction or '—').upper()],
        ['CONTAINMENT',       _fmt_num(incident.containment_percent, 0, '%'),
         'WIND SPEED',         _fmt_num(incident.wind_speed_mph, 1, ' mph')],
        ['STRUCTURES AT RISK', str(incident.structures_threatened or '—'),
         'HUMIDITY',           _fmt_num(incident.humidity_percent, 1, '%')],
        ['STARTED',           _fmt_time(incident.started_at),
         'LAST UPDATED',       _fmt_time(incident.updated_at)],
    ]
    sit_rows = [[
        Paragraph(row[0], S['label']), Paragraph(str(row[1]), S['value']),
        Paragraph(row[2], S['label']), Paragraph(str(row[3]), S['value']),
    ] for row in sit_data]
    sit_table = Table(sit_rows, colWidths=[1.5*inch, 2.0*inch, 1.5*inch, 2.3*inch])
    sit_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), C_PANEL),
        ('ROWBACKGROUNDS',(0,0),(-1,-1), [C_PANEL, HexColor('#1e1e22')]),
        ('TOPPADDING',    (0,0),(-1,-1), 5),
        ('BOTTOMPADDING', (0,0),(-1,-1), 5),
        ('LEFTPADDING',   (0,0),(-1,-1), 8),
        ('RIGHTPADDING',  (0,0),(-1,-1), 8),
        ('LINEBELOW',     (0,-1),(-1,-1), 1, C_BORDER),
    ]))
    story.append(sit_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph('RESOURCES ON INCIDENT', S['section']))
    # units is already filtered to this incident by the endpoint
    if not units:
        story.append(Paragraph('No resources currently assigned.', S['body']))
    else:
        res_header = [Paragraph(h, S['label']) for h in ('UNIT', 'TYPE', 'STATUS', 'PERSONNEL')]
        res_rows = [res_header]
        for u in sorted(units, key=lambda x: x.unit_type):
            status_color = {
                'en_route': '#60a5fa', 'on_scene': '#F56E0F',
                'staging': '#facc15', 'returning': '#a78bfa',
            }.get(u.status, '#878787')
            res_rows.append([
                Paragraph(u.designation, S['value']),
                Paragraph(UNIT_TYPE_LABEL.get(u.unit_type, u.unit_type), S['value']),
                Paragraph(f'<font color="{status_color}">{u.status.replace("_"," ").upper()}</font>', S['value']),
                Paragraph(str(u.personnel_count or '—'), S['value']),
            ])
        res_table = Table(res_rows, colWidths=[1.8*inch, 1.8*inch, 1.6*inch, 1.6*inch])
        res_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0),(-1,0),  C_ORANGE),
            ('TEXTCOLOR',     (0,0),(-1,0),  white),
            ('ROWBACKGROUNDS',(0,1),(-1,-1), [C_PANEL, HexColor('#1e1e22')]),
            ('TOPPADDING',    (0,0),(-1,-1), 5),
            ('BOTTOMPADDING', (0,0),(-1,-1), 5),
            ('LEFTPADDING',   (0,0),(-1,-1), 8),
            ('RIGHTPADDING',  (0,0),(-1,-1), 8),
            ('LINEBELOW',     (0,-1),(-1,-1), 1, C_BORDER),
        ]))
        story.append(res_table)

    story.append(Spacer(1, 10))

    active_alerts = [a for a in alerts if not a.is_acknowledged]
    story.append(Paragraph(f'ACTIVE ALERTS ({len(active_alerts)})', S['section']))
    if not active_alerts:
        story.append(Paragraph('No active alerts.', S['body']))
    else:
        for a in active_alerts[:8]:
            alert_color = {'critical': '#ef4444', 'high': '#F56E0F', 'moderate': '#facc15'}.get(a.severity, '#878787')
            story.append(Paragraph(
                f'<font color="{alert_color}">[{a.severity.upper()}]</font> {a.title}', S['body']
            ))
            story.append(Paragraph(a.description[:200], S['body']))
            story.append(Spacer(1, 4))

    story.append(Spacer(1, 10))
    if incident.notes:
        story.append(Paragraph('INCIDENT NOTES', S['section']))
        story.append(Paragraph(incident.notes, S['body']))
        story.append(Spacer(1, 10))

    story.append(HRFlowable(width='100%', thickness=1, color=C_BORDER, spaceBefore=12, spaceAfter=8))
    story.append(Paragraph(
        f'Generated by Pyra Wildfire Command · {_fmt_time(datetime.now(UTC))} · Operator: {generated_by} · CONFIDENTIAL — OFFICIAL USE ONLY',
        S['footer']
    ))

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C_BG)
        canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    buf.seek(0)
    return buf.read()


@router.get("/{incident_id}", summary="Generate PDF incident report")
def get_incident_report(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    # FIX: was db.query(Unit).all() — loaded entire fleet, filtered in Python
    units  = db.query(Unit).filter(Unit.assigned_incident_id == incident_id).all()
    alerts = db.query(Alert).filter(Alert.incident_id == incident_id).all()

    pdf_bytes = generate_report_pdf(incident, units, alerts, current_user.username)
    filename = (
        f"pyra_report_{incident.name.replace(' ', '_').lower()}"
        f"_{datetime.now(UTC).strftime('%Y%m%d_%H%M')}.pdf"
    )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
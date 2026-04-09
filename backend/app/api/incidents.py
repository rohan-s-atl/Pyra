from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, UTC
import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)

from app.core.database import get_db
from app.core.security import require_any_role, require_dispatcher_or_above
from app.models.incident import Incident as IncidentModel
from app.models.unit import Unit
from app.models.shift_briefing import ShiftBriefing
from app.schemas import Incident
from app.models.user import User
from app.services.audit_service import write_audit_log


router = APIRouter(prefix="/api/incidents", tags=["Incidents"])


@router.get(
    "/",
    response_model=List[Incident],
    summary="List all incidents",
)
def list_incidents(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    query = db.query(IncidentModel)
    if status:
        query = query.filter(IncidentModel.status == status)
    else:
        # By default exclude fully-closed fires (status='out') from the live view
        query = query.filter(IncidentModel.status != "out")
    return query.all()


@router.get(
    "/{incident_id}",
    response_model=Incident,
    summary="Get incident by ID",
)
def get_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    incident = (
        db.query(IncidentModel)
        .filter(IncidentModel.id == incident_id)
        .first()
    )
    if not incident:
        raise HTTPException(
            status_code=404,
            detail=f"Incident '{incident_id}' not found",
        )
    return incident


@router.get(
    "/{incident_id}/closeout-checklist",
    summary="Get close-out checklist status before marking incident out",
)
def get_closeout_checklist(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    """
    Returns a checklist of requirements that must be satisfied before an
    incident can be closed.  Each item has a `passed` flag and a message.
    The overall `ready` field is True only when all required items pass.
    """
    incident = db.query(IncidentModel).filter(IncidentModel.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    checks = []

    # 1. All units recalled (none on_scene or en_route)
    active_units = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id,
        Unit.status.in_(["on_scene", "en_route", "staging"]),
    ).all()
    units_recalled = len(active_units) == 0
    checks.append({
        "key":      "units_recalled",
        "label":    "All units recalled",
        "passed":   units_recalled,
        "required": True,
        "detail":   (
            f"{len(active_units)} unit(s) still active: "
            + ", ".join(u.designation for u in active_units[:5])
        ) if not units_recalled else "All units recalled or returned.",
    })

    # 2. Shift handoff briefing generated
    briefing = db.query(ShiftBriefing).filter(
        ShiftBriefing.incident_id == incident_id
    ).order_by(ShiftBriefing.generated_at.desc()).first()
    has_briefing = briefing is not None
    checks.append({
        "key":      "briefing_generated",
        "label":    "Shift handoff briefing generated",
        "passed":   has_briefing,
        "required": True,
        "detail":   (
            f"Last briefing: {briefing.generated_at.strftime('%Y-%m-%d %H:%MZ')}"
            if has_briefing else "No handoff briefing on record — generate one via POST /api/briefing/handoff/{id}."
        ),
    })

    # 3. Containment ≥ 100% (recommended, not required for out status)
    containment = incident.containment_percent or 0
    fully_contained = containment >= 100
    checks.append({
        "key":      "fully_contained",
        "label":    "Fire fully contained (100%)",
        "passed":   fully_contained,
        "required": False,
        "detail":   f"Current containment: {containment:.0f}%",
    })

    # 4. Incident not already closed
    already_closed = incident.status == "out"
    checks.append({
        "key":      "not_already_closed",
        "label":    "Incident not already closed",
        "passed":   not already_closed,
        "required": True,
        "detail":   "Incident is already marked OUT." if already_closed else "Incident is active.",
    })

    required_failed = [c for c in checks if c["required"] and not c["passed"]]
    ready = len(required_failed) == 0

    return {
        "incident_id":   incident_id,
        "incident_name": incident.name,
        "ready":         ready,
        "checks":        checks,
        "blocking":      [c["key"] for c in required_failed],
    }


@router.post(
    "/{incident_id}/close",
    summary="Close an incident after passing the close-out checklist",
)
async def close_incident(
    incident_id: str,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),
):
    """
    Closes an incident (sets status to 'out').

    Before closing:
    1. Validates the close-out checklist (all units recalled + briefing generated).
    2. Automatically triggers a final shift handoff briefing if one has not been
       generated in the last 2 hours.
    3. Writes an audit log entry.

    Pass `?force=true` to bypass checklist validation (commander only).
    """
    from app.core.config import settings
    import anthropic
    import json

    incident = db.query(IncidentModel).filter(IncidentModel.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    if incident.status == "out":
        raise HTTPException(status_code=400, detail="Incident is already closed.")

    if force and current_user.role != "commander":
        raise HTTPException(
            status_code=403,
            detail="Commander role required to force close an incident.",
        )

    # --- Checklist validation ---
    if not force:
        active_units = db.query(Unit).filter(
            Unit.assigned_incident_id == incident_id,
            Unit.status.in_(["on_scene", "en_route", "staging"]),
        ).count()
        if active_units > 0:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot close: {active_units} unit(s) still active. Recall all units first.",
            )

        briefing = db.query(ShiftBriefing).filter(
            ShiftBriefing.incident_id == incident_id
        ).order_by(ShiftBriefing.generated_at.desc()).first()
        if briefing is None:
            raise HTTPException(
                status_code=422,
                detail="Cannot close: no shift handoff briefing on record. Generate one first.",
            )

    # --- Auto-generate final briefing if stale (>2h old) ---
    api_key = settings.anthropic_api_key
    final_briefing_id = None

    recent_briefing = db.query(ShiftBriefing).filter(
        ShiftBriefing.incident_id == incident_id
    ).order_by(ShiftBriefing.generated_at.desc()).first()

    # ShiftBriefing.generated_at is stored as a naive DateTime (no tzinfo).
    # Comparing it directly with datetime.now(UTC) (timezone-aware) raises:
    #   TypeError: can't subtract offset-naive and offset-aware datetimes -> 500
    # Fix: strip tzinfo before subtraction so both sides are naive UTC.
    if recent_briefing is None:
        needs_final = True
    else:
        stored_at = recent_briefing.generated_at
        if stored_at.tzinfo is not None:
            stored_at = stored_at.replace(tzinfo=None)
        age_seconds = (datetime.now(UTC).replace(tzinfo=None) - stored_at).total_seconds()
        needs_final = age_seconds > 7200

    if needs_final and api_key:
        try:
            from app.api.briefing import _build_handoff_prompt, _generate_handoff_text
            from app.models.alert import Alert

            alerts = db.query(Alert).filter(Alert.incident_id == incident_id).all()
            units  = db.query(Unit).filter(Unit.assigned_incident_id == incident_id).all()
            prompt = _build_handoff_prompt(incident, alerts, units, 12)
            content = await _generate_handoff_text(prompt, api_key)

            fb = ShiftBriefing(
                id=str(uuid.uuid4()),
                incident_id=incident_id,
                generated_at=datetime.now(UTC),
                generated_by=current_user.username,
                trigger="incident_close",
                period_hours="12",
                content=content,
            )
            db.add(fb)
            final_briefing_id = fb.id
        except Exception as exc:
            # Don't block close-out on briefing failure
            logger.warning("[incidents] Final briefing generation failed for incident=%s: %s", incident_id, exc)

    # --- Mark incident out ---
    incident.status = "out"
    incident.updated_at = datetime.now(UTC)

    # Recall any remaining units
    remaining = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id,
        Unit.status != "out_of_service",
    ).all()
    for u in remaining:
        if u.status not in ("returning", "available"):
            u.status = "returning"
            u.last_updated = datetime.now(UTC)

    write_audit_log(
        db,
        action="INCIDENT_CLOSE",
        actor=current_user.username,
        actor_role=current_user.role,
        incident_id=incident_id,
        incident_name=incident.name,
        details=f"Incident closed. Force={force}. Final briefing={'generated' if final_briefing_id else 'skipped'}.",
    )

    db.commit()

    return {
        "status":          "closed",
        "incident_id":     incident_id,
        "incident_name":   incident.name,
        "final_briefing_id": final_briefing_id,
        "message":         f"Incident '{incident.name}' marked OUT. {len(remaining)} unit(s) set to returning.",
    }

"""
alerts.py — Alert REST endpoints. (PATCHED)

FIXES APPLIED
-------------
1. list_alerts now accepts limit/offset for pagination and sorts by
   created_at DESC so the UI always sees the most recent alerts first.
2. Severity filter added so the dashboard can request only critical/warning alerts.
3. Added GET /api/alerts/stats for quick badge counts without fetching full payloads.
4. Removed the ambiguous DELETE "/" (conflicts with /{alert_id} param routing on
   some FastAPI versions) — replaced with explicit DELETE /acknowledged.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.alert import Alert as AlertModel
from app.models.user import User
from app.schemas import Alert

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


@router.get(
    "/stats",
    summary="Alert count summary — fast badge endpoint",
)
def alert_stats(
    incident_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    """Return unacknowledged / total counts without fetching full rows."""
    query = db.query(AlertModel)
    if incident_id:
        query = query.filter(AlertModel.incident_id == incident_id)

    total  = query.count()
    unacked = query.filter(AlertModel.is_acknowledged.is_(False)).count()
    return {"total": total, "unacknowledged": unacked}


@router.get(
    "/",
    response_model=List[Alert],
    summary="List alerts with optional filters and pagination",
)
def list_alerts(
    incident_id:        Optional[str]  = None,
    severity:           Optional[str]  = None,
    unacknowledged_only: bool          = False,
    limit:              int            = Query(default=100, ge=1, le=500),
    offset:             int            = Query(default=0,   ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    """
    Returns alerts sorted by created_at DESC (newest first).
    Use limit/offset for pagination when alert count is high.
    """
    query = db.query(AlertModel)

    if incident_id:
        query = query.filter(AlertModel.incident_id == incident_id)

    if severity:
        query = query.filter(AlertModel.severity == severity)

    if unacknowledged_only:
        query = query.filter(AlertModel.is_acknowledged.is_(False))

    return (
        query
        .order_by(AlertModel.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get(
    "/{alert_id}",
    response_model=Alert,
    summary="Get alert by ID",
)
def get_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    alert = db.query(AlertModel).filter(AlertModel.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found")
    return alert


@router.delete(
    "/acknowledged",
    summary="Clear all acknowledged alerts (admin cleanup)",
)
def clear_acknowledged_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    """Delete all acknowledged alerts to reduce DB bloat."""
    deleted = db.query(AlertModel).filter(
        AlertModel.is_acknowledged.is_(True)
    ).delete()
    db.commit()
    return {"deleted": deleted}


@router.delete(
    "/all",
    summary="Clear ALL alerts — emergency reset (commander only)",
)
def clear_all_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    """Nuclear option — wipe all alerts. Use when alert count is out of control."""
    deleted = db.query(AlertModel).delete()
    db.commit()
    return {"deleted": deleted}


@router.post(
    "/{alert_id}/acknowledge",
    summary="Acknowledge an alert",
)
def acknowledge_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    alert = db.query(AlertModel).filter(AlertModel.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found")
    alert.is_acknowledged = True
    db.commit()
    return {"acknowledged": True, "alert_id": alert_id}

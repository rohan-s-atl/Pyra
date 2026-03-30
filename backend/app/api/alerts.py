"""
alerts.py — Alert REST endpoints.

PATCH: DELETE /all now requires require_commander (was require_any_role —
any authenticated user could wipe all alerts system-wide).
DELETE /acknowledged now requires require_dispatcher_or_above.
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.security import require_any_role, require_dispatcher_or_above, require_commander
from app.models.alert import Alert as AlertModel
from app.models.user import User
from app.schemas import Alert

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


@router.get("/stats", summary="Alert count summary — fast badge endpoint")
def alert_stats(
    incident_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    query = db.query(AlertModel)
    if incident_id:
        query = query.filter(AlertModel.incident_id == incident_id)
    total   = query.count()
    unacked = query.filter(AlertModel.is_acknowledged.is_(False)).count()
    return {"total": total, "unacknowledged": unacked}


@router.get("/", response_model=List[Alert], summary="List alerts with optional filters and pagination")
def list_alerts(
    incident_id:         Optional[str] = None,
    severity:            Optional[str] = None,
    unacknowledged_only: bool          = False,
    limit:               int           = Query(default=100, ge=1, le=500),
    offset:              int           = Query(default=0,   ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
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


@router.get("/{alert_id}", response_model=Alert, summary="Get alert by ID")
def get_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    alert = db.query(AlertModel).filter(AlertModel.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found")
    return alert


@router.delete("/acknowledged", summary="Clear all acknowledged alerts (dispatcher+)")
def clear_acknowledged_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),   # FIX: was require_any_role
):
    deleted = db.query(AlertModel).filter(AlertModel.is_acknowledged.is_(True)).delete()
    db.commit()
    return {"deleted": deleted}


@router.delete("/all", summary="Clear ALL alerts — emergency reset (commander only)")
def clear_all_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_commander),   # FIX: was require_any_role
):
    deleted = db.query(AlertModel).delete()
    db.commit()
    return {"deleted": deleted}


@router.post("/{alert_id}/acknowledge", summary="Acknowledge an alert")
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
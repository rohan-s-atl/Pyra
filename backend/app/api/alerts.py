from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.alert import Alert as AlertModel
from app.models.user import User
from app.schemas import Alert

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


@router.get(
    "/",
    response_model=List[Alert],
    summary="List all alerts",
)
def list_alerts(
    incident_id: Optional[str] = None,
    unacknowledged_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    query = db.query(AlertModel)

    if incident_id:
        query = query.filter(AlertModel.incident_id == incident_id)

    if unacknowledged_only:
        query = query.filter(AlertModel.is_acknowledged.is_(False))  # Fixed: use .is_(False)

    return query.all()


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
        raise HTTPException(
            status_code=404,
            detail=f"Alert '{alert_id}' not found",
        )

    return alert

@router.delete(
    "/",
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
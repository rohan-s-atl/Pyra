import csv
import io
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_any_role, require_commander
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.audit_service import verify_log_integrity

router = APIRouter(prefix="/api/audit", tags=["Audit"])


@router.get("/", summary="Get audit log entries")
def get_audit_logs(
    limit:  int = Query(100, le=500),
    offset: int = Query(0),
    db:     Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    entries = (
        db.query(AuditLog)
        .order_by(AuditLog.timestamp.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    total = db.query(AuditLog).count()

    return {
        "total":  total,
        "offset": offset,
        "limit":  limit,
        "entries": [
            {
                "id":            e.id,
                "timestamp":     e.timestamp.isoformat() + "Z",
                "action":        e.action,
                "actor":         e.actor,
                "actor_role":    e.actor_role,
                "incident_id":   e.incident_id,
                "incident_name": e.incident_name,
                "unit_ids":      e.unit_ids.split(",") if e.unit_ids else [],
                "details":       e.details,
                "checksum":      e.checksum,
            }
            for e in entries
        ],
    }


@router.get("/verify", summary="Verify audit log integrity (commander only)")
def verify_audit_integrity(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_commander),
):
    entries = db.query(AuditLog).order_by(AuditLog.timestamp.asc()).all()
    results = verify_log_integrity(entries)
    tampered = [r for r in results if not r["valid"]]
    return {
        "total":    len(results),
        "valid":    len(results) - len(tampered),
        "tampered": len(tampered),
        "integrity": "PASS" if not tampered else "FAIL",
        "details":   tampered if tampered else [],
    }


@router.get("/export.csv", summary="Export audit log as CSV")
def export_audit_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    entries = db.query(AuditLog).order_by(AuditLog.timestamp.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "timestamp", "action", "actor", "actor_role",
        "incident_id", "incident_name", "unit_ids", "details", "checksum",
    ])
    for e in entries:
        writer.writerow([
            e.timestamp.isoformat() + "Z",
            e.action,
            e.actor,
            e.actor_role,
            e.incident_id or "",
            e.incident_name or "",
            e.unit_ids or "",
            e.details or "",
            e.checksum,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pyra_audit_log.csv"},
    )
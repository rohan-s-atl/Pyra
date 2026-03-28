import hashlib
import uuid
from datetime import datetime, UTC
from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog


def _checksum(timestamp: str, action: str, actor: str, actor_role: str,
              incident_id: str, unit_ids: str, details: str) -> str:
    """SHA-256 of the row's core fields — tamper-evident."""
    raw = f"{timestamp}|{action}|{actor}|{actor_role}|{incident_id or ''}|{unit_ids or ''}|{details or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def write_audit_log(
    db: Session,
    action: str,
    actor: str,
    actor_role: str,
    incident_id: str   = None,
    incident_name: str = None,
    unit_ids: list     = None,
    details: str       = None,
) -> AuditLog:
    timestamp   = datetime.now(UTC)
    unit_ids_str = ",".join(unit_ids) if unit_ids else None
    checksum    = _checksum(
        timestamp.isoformat(), action, actor, actor_role,
        incident_id, unit_ids_str, details,
    )

    entry = AuditLog(
        id            = str(uuid.uuid4()),
        timestamp     = timestamp,
        action        = action,
        actor         = actor,
        actor_role    = actor_role,
        incident_id   = incident_id,
        incident_name = incident_name,
        unit_ids      = unit_ids_str,
        details       = details,
        checksum      = checksum,
    )
    db.add(entry)
    return entry


def verify_log_integrity(entries: list[AuditLog]) -> list[dict]:
    """Re-compute checksums and flag any tampered rows."""
    results = []
    for e in entries:
        expected = _checksum(
            e.timestamp.isoformat(), e.action, e.actor, e.actor_role,
            e.incident_id, e.unit_ids, e.details,
        )
        results.append({
            "id":       e.id,
            "valid":    e.checksum == expected,
            "checksum": e.checksum,
        })
    return results
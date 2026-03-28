from sqlalchemy import Column, String, DateTime, Text
from app.core.database import Base
from datetime import datetime, UTC


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id           = Column(String,   primary_key=True, index=True)
    timestamp    = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC), index=True)
    action       = Column(String,   nullable=False)          # DISPATCH | ALERT_DISPATCH | LOGIN | LOGOUT
    actor        = Column(String,   nullable=False)          # username
    actor_role   = Column(String,   nullable=False)          # commander | dispatcher | viewer
    incident_id  = Column(String,   nullable=True)
    incident_name= Column(String,   nullable=True)
    unit_ids     = Column(Text,     nullable=True)           # comma-separated
    details      = Column(Text,     nullable=True)           # free-text summary
    checksum     = Column(String,   nullable=False)          # SHA-256 of the row content
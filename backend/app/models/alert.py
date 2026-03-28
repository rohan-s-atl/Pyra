from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.core.database import Base


class Alert(Base):
    __tablename__ = "alerts"

    # IDs are generated as "ALT-{uuid4}" = 40 chars.  String without length
    # is unbounded in PostgreSQL (TEXT), which is fine and removes the need to
    # ever migrate this column again if the format changes.
    id = Column(String, primary_key=True, index=True)

    incident_id   = Column(String, ForeignKey("incidents.id"), nullable=False, index=True)
    alert_type    = Column(String, nullable=False, index=True)
    severity      = Column(String, nullable=False, index=True)
    title         = Column(String, nullable=False)
    description   = Column(String, nullable=False)
    is_acknowledged = Column(Boolean, default=False, nullable=False, index=True)
    created_at    = Column(DateTime(timezone=True), nullable=False, index=True)
    expires_at    = Column(DateTime(timezone=True), nullable=True, index=True)

    incident = relationship("Incident", back_populates="alerts")

    __table_args__ = (
        # Fast lookup for the dedup query run on every simulation tick:
        # WHERE incident_id = ? AND alert_type = ? AND is_acknowledged = false
        Index("idx_alert_dedup", "incident_id", "alert_type", "is_acknowledged"),
        # Dashboard / command panel query:
        # WHERE incident_id = ? AND is_acknowledged = false ORDER BY created_at DESC
        Index("idx_alert_incident_ack", "incident_id", "is_acknowledged"),
        # Severity-based filtering with time ordering
        Index("idx_alert_severity_created", "severity", "created_at"),
    )

from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.core.database import Base


class ShiftBriefing(Base):
    __tablename__ = "shift_briefings"

    id          = Column(String, primary_key=True, index=True)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False, index=True)
    generated_at = Column(DateTime, nullable=False, index=True)
    generated_by = Column(String, nullable=True)   # username of actor who triggered it
    trigger      = Column(String, nullable=False, default="manual")  # "manual" | "incident_close"
    period_hours = Column(String, nullable=False, default="12")      # data window
    content      = Column(Text, nullable=False)     # full AI-generated briefing text

    incident = relationship("Incident", back_populates="shift_briefings")

    __table_args__ = (
        Index("idx_shift_briefing_incident_time", "incident_id", "generated_at"),
    )

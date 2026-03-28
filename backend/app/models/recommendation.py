from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class Recommendation(Base):
    __tablename__ = "recommendations"

    id               = Column(String,   primary_key=True, index=True)
    incident_id      = Column(String,   ForeignKey("incidents.id"), nullable=False, index=True)
    generated_at     = Column(DateTime, nullable=False)
    confidence       = Column(String,   nullable=False)
    loadout_profile  = Column(String,   nullable=False)
    summary          = Column(Text,     nullable=False)
    tactical_notes   = Column(Text,     nullable=True)

    # unit_recommendations, route_options, resource_recommendations
    # stored as JSON text for now — will normalize in a later stage
    unit_recommendations_json     = Column(Text, nullable=True)
    route_options_json            = Column(Text, nullable=True)
    resource_recommendations_json = Column(Text, nullable=True)

    incident = relationship("Incident", back_populates="recommendations")
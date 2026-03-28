from sqlalchemy import Column, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class Resource(Base):
    __tablename__ = "resources"

    id              = Column(String, primary_key=True, index=True)
    name            = Column(String, nullable=False)
    resource_type   = Column(String, nullable=False)
    status          = Column(String, nullable=False)
    latitude        = Column(Float,  nullable=False)
    longitude       = Column(Float,  nullable=False)
    incident_id     = Column(String, ForeignKey("incidents.id"), nullable=True, index=True)
    capacity_notes  = Column(String, nullable=True)
    access_notes    = Column(String, nullable=True)
    contact         = Column(String, nullable=True)
    last_updated    = Column(DateTime, nullable=False)

    incident = relationship("Incident", back_populates="resources")
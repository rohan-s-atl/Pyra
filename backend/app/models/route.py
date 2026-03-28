from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class Route(Base):
    __tablename__ = "routes"

    id                      = Column(String,  primary_key=True, index=True)
    incident_id             = Column(String,  ForeignKey("incidents.id"), nullable=False, index=True)
    label                   = Column(String,  nullable=False)
    rank                    = Column(String,  nullable=False)
    origin_label            = Column(String,  nullable=False)
    destination_label       = Column(String,  nullable=False)
    origin_lat              = Column(Float,   nullable=False)
    origin_lon              = Column(Float,   nullable=False)
    destination_lat         = Column(Float,   nullable=False)
    destination_lon         = Column(Float,   nullable=False)
    estimated_travel_minutes= Column(Integer, nullable=True)
    distance_miles          = Column(Float,   nullable=True)
    terrain_accessibility   = Column(String,  nullable=False)
    fire_exposure_risk      = Column(String,  nullable=False)
    safety_rating           = Column(String,  nullable=False)
    is_currently_passable   = Column(Boolean, default=True)
    notes                   = Column(String,  nullable=True)
    last_verified_at        = Column(DateTime, nullable=False)

    incident = relationship("Incident", back_populates="routes")
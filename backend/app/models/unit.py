from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.core.database import Base


class Unit(Base):
    __tablename__ = "units"

    id = Column(String, primary_key=True, index=True)

    designation = Column(String, nullable=False)

    unit_type = Column(String, nullable=False, index=True)
    status    = Column(String, nullable=False, index=True)

    station_id = Column(String, nullable=True, index=True)

    assigned_incident_id = Column(
        String,
        ForeignKey("incidents.id"),
        nullable=True,
        index=True
    )

    # GPS coordinates — Float for proper arithmetic in simulation + GPS updates
    latitude  = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # GPS metadata — set when position comes from a real device, null for simulated
    gps_accuracy_m   = Column(Float,    nullable=True)   # metres
    gps_source       = Column(String,   nullable=True)   # "device" | "simulated" | "manual"
    gps_updated_at   = Column(DateTime, nullable=True)   # timestamp of last real GPS fix

    personnel_count        = Column(Integer, nullable=True)
    water_capacity_gallons = Column(Integer, nullable=True)

    has_structure_protection = Column(Boolean, default=False, index=True)
    has_air_attack           = Column(Boolean, default=False, index=True)

    # ICS unit typing — standard ICS resource kind/type (e.g. "Type 1", "Type 2", "VLAT")
    # Used by recommendation logic to prefer higher-typed units for critical incidents
    ics_type = Column(String, nullable=True, index=True)  # e.g. "Type 1", "Type 2", "Type 3"

    on_scene_since = Column(DateTime, nullable=True)   # set on arrival, cleared on departure

    last_updated = Column(DateTime, nullable=False, index=True)

    incident = relationship("Incident", back_populates="units")

    __table_args__ = (
        Index("idx_unit_incident_status", "assigned_incident_id", "status"),
        Index("idx_unit_type_status",     "unit_type",            "status"),
    )
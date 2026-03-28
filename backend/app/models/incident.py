from sqlalchemy import Column, String, Float, Integer, DateTime, Index, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class IncidentSeverity(str, enum.Enum):
    low = "low"
    moderate = "moderate"
    high = "high"
    critical = "critical"


class IncidentStatus(str, enum.Enum):
    active = "active"
    contained = "contained"
    controlled = "controlled"
    out = "out"


class FireType(str, enum.Enum):
    wildland = "wildland"
    wildland_urban_interface = "wildland_urban_interface"
    structure = "structure"


class SpreadRisk(str, enum.Enum):
    low = "low"
    moderate = "moderate"
    high = "high"
    extreme = "extreme"


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)

    # 🔥 Indexed fields (high query frequency)
    fire_type = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, index=True)
    spread_risk = Column(String, nullable=False, index=True)

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    acres_burned = Column(Float, nullable=True)
    spread_direction = Column(String, nullable=True)
    wind_speed_mph = Column(Float, nullable=True)
    humidity_percent = Column(Float, nullable=True)
    containment_percent = Column(Float, nullable=True)
    structures_threatened = Column(Integer, nullable=True)

    started_at = Column(DateTime, nullable=False, index=True)  # 🔥 useful for sorting/time queries
    updated_at = Column(DateTime, nullable=False, index=True)

    notes = Column(String, nullable=True)

    # ── Terrain data (Open-Elevation) ──────────────────────────────────────
    elevation_m     = Column(Float,   nullable=True)   # metres above sea level
    slope_percent   = Column(Float,   nullable=True)   # terrain slope %
    aspect_cardinal = Column(String,  nullable=True)   # uphill direction (N/NE/E/…)

    # ── Air quality / sensor data (AirNow) ────────────────────────────────
    aqi             = Column(Integer, nullable=True)   # Air Quality Index
    aqi_category    = Column(String,  nullable=True)   # "good" / "moderate" / … / "hazardous"

    # Relationships
    alerts = relationship("Alert", back_populates="incident", cascade="all, delete-orphan")
    units = relationship("Unit", back_populates="incident")
    routes = relationship("Route", back_populates="incident", cascade="all, delete-orphan")
    resources = relationship("Resource", back_populates="incident")
    recommendations = relationship("Recommendation", back_populates="incident", cascade="all, delete-orphan")
    shift_briefings = relationship("ShiftBriefing", back_populates="incident", cascade="all, delete-orphan")

    # 🔥 Composite indexes (VERY useful)
    __table_args__ = (
        Index("idx_incident_status_severity", "status", "severity"),
        Index("idx_incident_location", "latitude", "longitude"),
    )
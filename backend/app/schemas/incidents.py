from pydantic import BaseModel
from typing import Optional
from enum import Enum
from datetime import datetime


class IncidentSeverity(str, Enum):
    low = "low"
    moderate = "moderate"
    high = "high"
    critical = "critical"


class IncidentStatus(str, Enum):
    active = "active"
    contained = "contained"
    controlled = "controlled"
    out = "out"


class FireType(str, Enum):
    wildland = "wildland"
    wildland_urban_interface = "wildland_urban_interface"
    structure = "structure"


class SpreadRisk(str, Enum):
    low = "low"
    moderate = "moderate"
    high = "high"
    extreme = "extreme"


class Incident(BaseModel):
    id: str
    name: str
    fire_type: FireType
    severity: IncidentSeverity
    status: IncidentStatus
    latitude: float
    longitude: float
    acres_burned: Optional[float] = None
    spread_risk: SpreadRisk
    spread_direction: Optional[str] = None
    wind_speed_mph: Optional[float] = None
    humidity_percent: Optional[float] = None
    containment_percent: Optional[float] = None
    structures_threatened: Optional[int] = None
    started_at: datetime
    updated_at: datetime
    notes: Optional[str] = None
    # Terrain enrichment
    elevation_m:     Optional[float] = None
    slope_percent:   Optional[float] = None
    aspect_cardinal: Optional[str]   = None
    # Air quality
    aqi:             Optional[int]   = None
    aqi_category:    Optional[str]   = None

    model_config = {"from_attributes": True}
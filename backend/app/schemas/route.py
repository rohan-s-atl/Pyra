from pydantic import BaseModel
from typing import Optional
from enum import Enum
from datetime import datetime


class TerrainAccessibility(str, Enum):
    good = "good"
    limited = "limited"
    poor = "poor"
    impassable = "impassable"


class FireExposureRisk(str, Enum):
    low = "low"
    moderate = "moderate"
    high = "high"
    extreme = "extreme"


class SafetyRating(str, Enum):
    safe = "safe"
    caution = "caution"
    avoid = "avoid"


class RouteRank(str, Enum):
    primary = "primary"
    alternate = "alternate"
    emergency_only = "emergency_only"


class Route(BaseModel):
    id: str
    incident_id: str
    label: str
    rank: RouteRank
    origin_label: str
    destination_label: str
    origin_lat: float
    origin_lon: float
    destination_lat: float
    destination_lon: float
    estimated_travel_minutes: int
    distance_miles: Optional[float] = None
    terrain_accessibility: TerrainAccessibility
    fire_exposure_risk: FireExposureRisk
    safety_rating: SafetyRating
    is_currently_passable: bool = True
    notes: Optional[str] = None
    last_verified_at: datetime
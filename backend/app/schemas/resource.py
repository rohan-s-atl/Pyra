from pydantic import BaseModel
from typing import Optional
from enum import Enum
from datetime import datetime


class ResourceType(str, Enum):
    water_source = "water_source"
    staging_area = "staging_area"
    fuel_point = "fuel_point"
    retardant_base = "retardant_base"
    shelter_zone = "shelter_zone"
    helispot = "helispot"
    medical_station = "medical_station"


class ResourceStatus(str, Enum):
    available = "available"
    limited = "limited"
    depleted = "depleted"
    unavailable = "unavailable"


class Resource(BaseModel):
    id: str
    name: str
    resource_type: ResourceType
    status: ResourceStatus
    latitude: float
    longitude: float
    incident_id: Optional[str] = None
    capacity_notes: Optional[str] = None
    access_notes: Optional[str] = None
    contact: Optional[str] = None
    last_updated: datetime
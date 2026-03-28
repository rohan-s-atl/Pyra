from pydantic import BaseModel
from typing import List, Optional
from enum import Enum
from datetime import datetime


class LoadoutProfile(str, Enum):
    initial_attack = "initial_attack"
    extended_suppression = "extended_suppression"
    structure_protection = "structure_protection"
    containment_support = "containment_support"
    remote_access_support = "remote_access_support"
    aerial_suppression = "aerial_suppression"


class RouteOption(BaseModel):
    route_id: str
    label: str
    estimated_travel_minutes: int
    terrain_accessibility: str
    fire_exposure_risk: str
    safety_rating: str
    notes: Optional[str] = None


class UnitRecommendation(BaseModel):
    unit_type: str
    quantity: int
    priority: str
    rationale: str


class ResourceRecommendation(BaseModel):
    resource_type: str
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    notes: Optional[str] = None


class Recommendation(BaseModel):
    id: str
    incident_id: str
    generated_at: datetime
    confidence: str
    loadout_profile: LoadoutProfile
    summary: str
    unit_recommendations: List[UnitRecommendation]
    route_options: List[RouteOption]
    resource_recommendations: List[ResourceRecommendation]
    tactical_notes: Optional[str] = None
from pydantic import BaseModel
from typing import Optional
from enum import Enum
from datetime import datetime


class UnitType(str, Enum):
    engine       = "engine"
    hand_crew    = "hand_crew"
    dozer        = "dozer"
    water_tender = "water_tender"
    helicopter   = "helicopter"
    air_tanker   = "air_tanker"
    command_unit = "command_unit"
    rescue       = "rescue"


class UnitStatus(str, Enum):
    available      = "available"
    en_route       = "en_route"
    on_scene       = "on_scene"
    staging        = "staging"
    returning      = "returning"
    out_of_service = "out_of_service"


class Unit(BaseModel):
    id:                    str
    designation:           str
    unit_type:             UnitType
    status:                UnitStatus
    station_id:            Optional[str]   = None
    assigned_incident_id:  Optional[str]   = None
    latitude:              Optional[float] = None   # native float
    longitude:             Optional[float] = None   # native float
    gps_accuracy_m:        Optional[float] = None
    gps_source:            Optional[str]   = None   # "device" | "simulated" | "manual"
    gps_updated_at:        Optional[datetime] = None
    station_lat:           Optional[float] = None
    station_lon:           Optional[float] = None
    station_type:          Optional[str]   = None
    personnel_count:       Optional[int]   = None
    water_capacity_gallons:Optional[int]   = None
    has_structure_protection: bool = False
    has_air_attack:           bool = False
    ics_type:              Optional[str]   = None   # "Type 1" | "Type 2" | "Type 3" etc.
    last_updated:          datetime
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class Alert(BaseModel):
    id: str
    incident_id: str
    alert_type: str
    severity: str
    title: str
    description: str
    is_acknowledged: bool = False
    created_at: datetime
    expires_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# Keep these exports so __init__.py and any other imports don't break
AlertType = str
AlertSeverity = str
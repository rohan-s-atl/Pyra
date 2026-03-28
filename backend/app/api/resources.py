from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.resource import Resource as ResourceModel
from app.models.user import User
from app.schemas import Resource

router = APIRouter(prefix="/api/resources", tags=["Resources"])


@router.get("/", response_model=List[Resource], summary="List all resources")
def list_resources(
    incident_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    query = db.query(ResourceModel)
    if incident_id:
        query = query.filter(ResourceModel.incident_id == incident_id)
    if resource_type:
        query = query.filter(ResourceModel.resource_type == resource_type)
    if status:
        query = query.filter(ResourceModel.status == status)
    return query.all()


@router.get("/{resource_id}", response_model=Resource, summary="Get resource by ID")
def get_resource(
    resource_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    resource = db.query(ResourceModel).filter(ResourceModel.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail=f"Resource '{resource_id}' not found")
    return resource
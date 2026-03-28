from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import httpx
from datetime import datetime, UTC, timedelta

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.user import User

router = APIRouter(prefix="/api/perimeters", tags=["Perimeters"])

# NIFC Active Fire Perimeters — public ArcGIS REST endpoint
NIFC_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Interagency_Perimeters/FeatureServer/0/query"
    "?where=1%3D1"
    "&outFields=IncidentName,GISAcres,PercentContained,CreateDate,IncidentTypeCategory"
    "&f=geojson"
    "&resultRecordCount=100"
    "&orderByFields=CreateDate+DESC"
)

_cache: dict = {"data": None, "fetched_at": None}
CACHE_TTL_MINUTES = 15


@router.get("/", summary="Get active fire perimeters from NIFC")
async def get_perimeters(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),  # Added authentication
):
    global _cache

    # Return cache if fresh
    if _cache["data"] and _cache["fetched_at"]:
        age = datetime.now(UTC) - _cache["fetched_at"]
        if age < timedelta(minutes=CACHE_TTL_MINUTES):
            return _cache["data"]

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res  = await client.get(NIFC_URL)
            data = res.json()

        features = data.get("features", [])

        # Normalize into a clean list for the frontend
        perimeters = []
        for f in features:
            geom  = f.get("geometry")
            props = f.get("properties", {})

            if not geom or not geom.get("coordinates"):
                continue

            # Handle both Polygon and MultiPolygon
            geom_type = geom.get("type", "")
            if geom_type not in ("Polygon", "MultiPolygon"):
                continue

            perimeters.append({
                "id":           f.get("id", str(hash(str(props.get("IncidentName", ""))))),
                "name":         props.get("IncidentName", "Unknown Fire"),
                "acres":        props.get("GISAcres"),
                "containment":  props.get("PercentContained"),
                "type":         props.get("IncidentTypeCategory", "WF"),
                "geometry":     geom,
            })

        result = {"perimeters": perimeters, "fetched_at": datetime.now(UTC).isoformat(), "count": len(perimeters)}
        _cache = {"data": result, "fetched_at": datetime.now(UTC)}
        return result

    except Exception as e:
        print(f"[perimeters] NIFC fetch failed: {e}")
        # Return empty on failure — don't crash the app
        return {"perimeters": [], "fetched_at": None, "count": 0, "error": str(e)}
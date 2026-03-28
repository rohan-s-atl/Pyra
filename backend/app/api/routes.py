"""
routes.py — Route API.

Provides:
  GET  /api/routes/              — list saved routes (from DB)
  GET  /api/routes/{id}          — get single saved route
  GET  /api/routes/safety/{iid}  — score all routes for an incident
  GET  /api/routes/safety/{iid}/{rid} — score single route
  POST /api/routes/compute       — compute a live road route (OSRM/Mapbox/fallback)
                                   Returns polyline for frontend map visualization.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
import math

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.route import Route as RouteModel
from app.models.user import User
from app.schemas import Route
from app.services.route_safety import score_all_routes, score_route
from app.models.incident import Incident
from app.services.routing import _fetch_road_route, _straight_line, get_travel_time_minutes

router = APIRouter(prefix="/api/routes", tags=["Routes"])


# ---------------------------------------------------------------------------
# Saved routes (DB-backed)
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[Route], summary="List all routes")
def list_routes(
    incident_id: Optional[str] = None,
    passable_only: bool = False,
    safety_rating: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    query = db.query(RouteModel)
    if incident_id:
        query = query.filter(RouteModel.incident_id == incident_id)
    if passable_only:
        query = query.filter(RouteModel.is_currently_passable.is_(True))
    if safety_rating:
        query = query.filter(RouteModel.safety_rating == safety_rating)
    return query.all()


@router.get("/{route_id}", response_model=Route, summary="Get route by ID")
def get_route(
    route_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    route = db.query(RouteModel).filter(RouteModel.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail=f"Route '{route_id}' not found")
    return route


# ---------------------------------------------------------------------------
# Route safety scoring
# ---------------------------------------------------------------------------

@router.get("/safety/{incident_id}", summary="Score all routes for an incident")
def get_route_safety(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    """
    Evaluates every route attached to the incident against:
    - Active fire spread cones
    - Terrain accessibility and fire exposure attributes
    - Route passability status

    Returns each route with safety_score (0-100), status, risk_factors, explanation.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    scored = score_all_routes(db, incident_id)
    return {
        "incident_id":   incident_id,
        "incident_name": incident.name,
        "routes": scored,
        "summary": {
            "total":   len(scored),
            "safe":    sum(1 for r in scored if r["status"] == "safe"),
            "risky":   sum(1 for r in scored if r["status"] == "risky"),
            "blocked": sum(1 for r in scored if r["status"] == "blocked"),
        },
    }


@router.get("/safety/{incident_id}/{route_id}", summary="Score a single route")
def get_single_route_safety(
    incident_id: str,
    route_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    route = db.query(RouteModel).filter(
        RouteModel.id == route_id,
        RouteModel.incident_id == incident_id,
    ).first()
    if not route:
        raise HTTPException(status_code=404, detail=f"Route '{route_id}' not found")

    active_incidents = db.query(Incident).filter(
        Incident.status.in_(["active", "contained"])
    ).all()

    return score_route(route, active_incidents)


# ---------------------------------------------------------------------------
# Live route computation — polyline for frontend map
# ---------------------------------------------------------------------------

class RouteComputeRequest(BaseModel):
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float
    unit_type: Optional[str] = "engine"
    label: Optional[str] = "Computed Route"


class RouteComputeResponse(BaseModel):
    polyline: List[List[float]]     # [[lat, lon], ...] for Leaflet/MapLibre
    is_road_routed: bool            # False = straight-line fallback
    distance_km: float
    estimated_minutes: float
    routing_source: str             # "osrm_public" | "osrm_local" | "mapbox" | "straight_line"
    label: str


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(d_lon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(min(1.0, a)))


@router.post("/compute", response_model=RouteComputeResponse, summary="Compute a live road route")
async def compute_route(
    body: RouteComputeRequest,
    current_user: User = Depends(require_any_role),
):
    """
    Compute a road route between two points for frontend map visualization.

    Returns a polyline ([[lat, lon], ...]) that can be drawn directly on Leaflet
    or MapLibre maps. Uses the same routing backend stack as the simulation:
      1. Public OSRM (free, no key required)
      2. Local OSRM (if running on localhost:5001)
      3. Mapbox (if MAPBOX_TOKEN env var is set)
      4. Straight-line fallback (always succeeds, is_road_routed=False)

    Air units (helicopter, air_tanker) always return straight-line routes.
    """
    from_lat, from_lon = body.from_lat, body.from_lon
    to_lat,   to_lon   = body.to_lat,   body.to_lon

    # Validate coordinates
    if not (-90 <= from_lat <= 90 and -180 <= from_lon <= 180):
        raise HTTPException(status_code=422, detail="Invalid origin coordinates")
    if not (-90 <= to_lat <= 90 and -180 <= to_lon <= 180):
        raise HTTPException(status_code=422, detail="Invalid destination coordinates")

    unit_type = (body.unit_type or "engine").lower()
    is_air    = unit_type in ("helicopter", "air_tanker", "heli", "tanker", "air_tanker")

    polyline: List[List[float]]
    is_road_routed: bool
    routing_source: str

    if is_air:
        polyline       = _straight_line(from_lat, from_lon, to_lat, to_lon, num_points=30)
        is_road_routed = False
        routing_source = "straight_line"
    else:
        waypoints = await _fetch_road_route(from_lat, from_lon, to_lat, to_lon)
        if waypoints is not None:
            polyline       = waypoints
            is_road_routed = True
            # Determine which backend responded (heuristic via endpoint health)
            from app.services.routing import _health, PUBLIC_OSRM_URL, LOCAL_OSRM_URL
            if not _health[PUBLIC_OSRM_URL].is_cooling_down():
                routing_source = "osrm_public"
            elif not _health.get(LOCAL_OSRM_URL, type("x", (), {"is_cooling_down": lambda self: True})()).is_cooling_down():
                routing_source = "osrm_local"
            else:
                routing_source = "mapbox"
        else:
            polyline       = _straight_line(from_lat, from_lon, to_lat, to_lon)
            is_road_routed = False
            routing_source = "straight_line"

    # Compute distance along polyline
    distance_km = 0.0
    for i in range(1, len(polyline)):
        distance_km += _haversine_km(
            polyline[i-1][0], polyline[i-1][1],
            polyline[i][0],   polyline[i][1],
        )

    # ETA estimate
    if is_road_routed and not is_air:
        est_minutes = await get_travel_time_minutes(from_lat, from_lon, to_lat, to_lon)
    else:
        # Air: ~100 mph for heli, ground straight-line: assume 40 mph
        speed_kmh = 160.0 if is_air else 65.0
        est_minutes = round((distance_km / speed_kmh) * 60.0, 1)

    return RouteComputeResponse(
        polyline        = polyline,
        is_road_routed  = is_road_routed,
        distance_km     = round(distance_km, 2),
        estimated_minutes = round(est_minutes, 1),
        routing_source  = routing_source,
        label           = body.label or "Computed Route",
    )
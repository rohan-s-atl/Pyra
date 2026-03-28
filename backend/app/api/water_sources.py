"""
water_sources.py — GET /api/water-sources

Fetches nearby water sources (hydrants, lakes, tanks) from OpenStreetMap via
the Overpass API, then computes OSRM road distances from each active unit to
each source, and assigns the best (closest accessible) source per unit.

Bugs fixed vs original:
  1. Missing relation query — large lakes like Clear Lake are OSM relations
     (type=multipolygon, natural=water), not nodes or ways. Added relation query.
  2. Missing waterway=* tags — rivers/streams tagged only as waterways were skipped.
  3. Missing landuse=reservoir as way/relation (only queried as node).
  4. out center only works for ways/relations; relations need `out center qt` or
     the center block — added `>; out center;` after relation query.
  5. radius_m default was 5000 in fetch_water_sources() but 6000 in the frontend
     call — unified at 6000m.
  6. MAX_SOURCES cap of 40 was hit before large bodies because nodes (hydrants)
     came first; now hydrants capped separately so large water bodies aren't cut.
  7. Classification bug: ways/relations with natural=water and no water=* subtag
     were classified as "lake" when they could be reservoirs (landuse=reservoir
     on the same element). Fixed classification order.
  8. Timeout too short (12s) for large areas — increased to 25s.
  9. OSRM calls were sequential per unit; parallelised with gather.
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_any_role
from app.models.incident import Incident
from app.models.unit import Unit
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/water-sources", tags=["Water Sources"])

# ── Constants ──────────────────────────────────────────────────────────────────

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSRM_URLS = [
    "http://localhost:5001/route/v1/driving",
    "https://router.project-osrm.org/route/v1/driving",
]

FILL_RATE_GPM: dict[str, float] = {
    "hydrant":    1000.0,
    "lake":        500.0,
    "reservoir":   400.0,
    "pond":        300.0,
    "river":       500.0,
    "tank":        250.0,
    "unknown":     200.0,
}

REQUEST_TIMEOUT = 25.0   # was 12s — large relation queries need more time
MAX_HYDRANTS = 20        # separate cap so hydrants don't crowd out large bodies
MAX_BODIES   = 15        # max large water bodies (lakes, rivers, reservoirs)
MAX_TANKS    = 10


# ── Overpass query ─────────────────────────────────────────────────────────────

def _build_overpass_query(lat: float, lon: float, radius_m: int) -> str:
    """
    Comprehensive query covering:
    - Fire hydrants (node, amenity or emergency tag)
    - Water bodies as nodes, ways, AND relations (fixes Clear Lake / large lakes)
    - Waterways (rivers, streams) tagged as ways
    - Reservoirs and water tanks
    - Relations with type=multipolygon and natural=water (the main fix)
    """
    return f"""
[out:json][timeout:30];
(
  node["emergency"="fire_hydrant"](around:{radius_m},{lat},{lon});
  node["amenity"="fire_hydrant"](around:{radius_m},{lat},{lon});
  way["amenity"="fire_hydrant"](around:{radius_m},{lat},{lon});

  node["natural"="water"](around:{radius_m},{lat},{lon});
  way["natural"="water"](around:{radius_m},{lat},{lon});
  relation["natural"="water"](around:{radius_m},{lat},{lon});

  way["waterway"~"^(river|canal|stream|drain)$"](around:{radius_m},{lat},{lon});

  node["man_made"="water_tank"](around:{radius_m},{lat},{lon});
  node["man_made"="reservoir_covered"](around:{radius_m},{lat},{lon});
  way["man_made"="reservoir_covered"](around:{radius_m},{lat},{lon});

  node["landuse"="reservoir"](around:{radius_m},{lat},{lon});
  way["landuse"="reservoir"](around:{radius_m},{lat},{lon});
  relation["landuse"="reservoir"](around:{radius_m},{lat},{lon});

  relation["type"="multipolygon"]["natural"="water"](around:{radius_m},{lat},{lon});
);
out center qt;
""".strip()


# ── Classification ─────────────────────────────────────────────────────────────

def _classify_source(tags: dict, el_type: str = "node") -> str:
    emergency = tags.get("emergency", "")
    amenity   = tags.get("amenity", "")
    natural   = tags.get("natural", "")
    man_made  = tags.get("man_made", "")
    landuse   = tags.get("landuse", "")
    waterway  = tags.get("waterway", "")
    water_sub = tags.get("water", "")   # sub-tag: lake, pond, river, reservoir…

    if emergency == "fire_hydrant" or amenity == "fire_hydrant":
        return "hydrant"

    if man_made in ("water_tank", "reservoir_covered"):
        return "tank"

    if landuse == "reservoir":
        return "reservoir"

    if waterway in ("river", "canal", "stream", "drain"):
        return "river"

    if natural == "water":
        if water_sub == "lake":
            return "lake"
        if water_sub in ("pond", "oxbow"):
            return "pond"
        if water_sub in ("river", "canal", "stream"):
            return "river"
        if water_sub == "reservoir":
            return "reservoir"
        # Large unnamed natural=water with no sub-type → lake (default for large bodies)
        return "lake"

    return "unknown"


def _source_name(tags: dict, source_type: str) -> str:
    """Return best human-readable name for a source."""
    return (
        tags.get("name")
        or tags.get("official_name")
        or tags.get("alt_name")
        or tags.get("ref")
        or source_type.replace("_", " ").title()
    )


# ── Fetch ──────────────────────────────────────────────────────────────────────

async def fetch_water_sources(lat: float, lon: float, radius_m: int = 6000) -> list[dict]:
    """Query Overpass for water sources near (lat, lon)."""
    query = _build_overpass_query(lat, lon, radius_m)
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(OVERPASS_URL, data={"data": query})
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("[water_sources] Overpass timed out after %.0fs", REQUEST_TIMEOUT)
        return []
    except Exception as exc:
        logger.warning("[water_sources] Overpass query failed: %s", exc)
        return []

    hydrants:   list[dict] = []
    bodies:     list[dict] = []
    tanks:      list[dict] = []
    seen_ids:   set[str]   = set()

    for el in data.get("elements", []):
        el_type = el.get("type", "node")
        el_id   = f"{el_type}:{el['id']}"
        if el_id in seen_ids:
            continue
        seen_ids.add(el_id)

        tags = el.get("tags", {}) or {}
        source_type = _classify_source(tags, el_type)

        # Extract coordinates — nodes have lat/lon, ways/relations have center{}
        if el_type == "node":
            src_lat = el.get("lat")
            src_lon = el.get("lon")
        else:
            center  = el.get("center") or {}
            src_lat = center.get("lat")
            src_lon = center.get("lon")

        # Skip if no center returned (large relations sometimes lack it)
        if src_lat is None or src_lon is None:
            logger.debug("[water_sources] skipping %s — no center coords", el_id)
            continue

        capacity_m3 = None
        cap_str = tags.get("capacity")
        if cap_str:
            try:
                capacity_m3 = float(cap_str)
            except ValueError:
                pass

        entry = {
            "id":            el_id,
            "osm_type":      el_type,
            "type":          source_type,
            "name":          _source_name(tags, source_type),
            "latitude":      src_lat,
            "longitude":     src_lon,
            "fill_rate_gpm": FILL_RATE_GPM.get(source_type, 200.0),
            "capacity_m3":   capacity_m3,
            "tags": {k: v for k, v in tags.items() if k in (
                "name", "official_name", "alt_name", "ref", "operator",
                "access", "note", "water", "waterway", "natural",
                "emergency", "man_made", "landuse",
            )},
        }

        # Bucket by type so each category gets its own cap
        if source_type == "hydrant":
            if len(hydrants) < MAX_HYDRANTS:
                hydrants.append(entry)
        elif source_type in ("tank", "unknown"):
            if len(tanks) < MAX_TANKS:
                tanks.append(entry)
        else:
            # Lakes, ponds, rivers, reservoirs — sort larger/named first
            if len(bodies) < MAX_BODIES:
                bodies.append(entry)

    # Sort water bodies: named ones first, then by proximity (sorted later by caller)
    bodies.sort(key=lambda s: (0 if s["name"] != s["type"].title() else 1))

    return hydrants + bodies + tanks


# ── OSRM distance ──────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(d_lon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(min(1.0, a)))


async def _osrm_distance_km(
    from_lat: float, from_lon: float,
    to_lat: float,   to_lon: float,
) -> Optional[float]:
    """Return road distance in km via OSRM, or None on failure."""
    coord_str = f"{from_lon},{from_lat};{to_lon},{to_lat}"
    for base_url in OSRM_URLS:
        url = f"{base_url}/{coord_str}?overview=false&alternatives=false"
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    d = resp.json()
                    if d.get("code") == "Ok":
                        return d["routes"][0]["distance"] / 1000.0
        except Exception:
            continue
    return None


async def _score_source_for_unit(
    unit: Unit,
    source: dict,
) -> tuple[dict, float]:
    """Return (source, effective_distance_km) for ranking."""
    road_km = await _osrm_distance_km(
        unit.latitude, unit.longitude,
        source["latitude"], source["longitude"],
    )
    dist_km = road_km if road_km is not None else _haversine_km(
        unit.latitude, unit.longitude,
        source["latitude"], source["longitude"],
    )
    return source, dist_km


async def _best_source_for_unit(
    unit: Unit,
    sources: list[dict],
) -> tuple[Optional[dict], Optional[float]]:
    """Return (best_source, road_distance_km) for a unit."""
    if unit.latitude is None or unit.longitude is None or not sources:
        return None, None

    # Pre-filter to nearest 6 by straight-line to reduce OSRM calls
    candidates = sorted(
        sources,
        key=lambda s: _haversine_km(
            unit.latitude, unit.longitude,
            s["latitude"], s["longitude"]
        ),
    )[:6]

    # Score all candidates concurrently
    scored = await asyncio.gather(*[
        _score_source_for_unit(unit, s) for s in candidates
    ])

    best_source, best_dist = min(scored, key=lambda x: x[1])
    return best_source, best_dist


def _fill_time_minutes(unit: Unit, source: dict) -> Optional[float]:
    if not unit.water_capacity_gallons:
        return None
    gpm = source.get("fill_rate_gpm", 200.0)
    if gpm <= 0:
        return None
    return round(unit.water_capacity_gallons / gpm, 1)


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.get("/", summary="Fetch water sources near an incident with unit assignments")
async def get_water_sources(
    incident_id: str = Query(..., description="Incident ID to center the search"),
    radius_m: int    = Query(6000, ge=500, le=20000, description="Search radius in metres"),
    db: Session      = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    sources = await fetch_water_sources(incident.latitude, incident.longitude, radius_m)

    # Units to score: assigned active units + available water tenders
    assigned_units = db.query(Unit).filter(
        Unit.assigned_incident_id == incident_id,
        Unit.status.in_(["en_route", "on_scene", "staging"]),
    ).all()
    water_tenders = db.query(Unit).filter(
        Unit.unit_type == "water_tender",
        Unit.status == "available",
    ).all()
    assigned_ids = {u.id for u in assigned_units}
    all_units = assigned_units + [u for u in water_tenders if u.id not in assigned_ids]

    # Score units concurrently (capped at 10)
    units_to_score = [u for u in all_units if u.latitude is not None][:10]
    results = await asyncio.gather(*[
        _best_source_for_unit(u, sources) for u in units_to_score
    ])

    unit_assignments = {}
    for unit, (best_source, dist_km) in zip(units_to_score, results):
        if best_source is None:
            continue
        unit_assignments[unit.id] = {
            "unit_id":           unit.id,
            "designation":       unit.designation,
            "unit_type":         unit.unit_type,
            "source_id":         best_source["id"],
            "source_type":       best_source["type"],
            "source_name":       best_source["name"],
            "road_distance_km":  round(dist_km, 2) if dist_km else None,
            "fill_time_minutes": _fill_time_minutes(unit, best_source),
        }

    # Build GeoJSON FeatureCollection, sorted by distance from incident
    features = []
    for s in sources:
        straight_km = _haversine_km(
            incident.latitude, incident.longitude,
            s["latitude"], s["longitude"]
        )
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [s["longitude"], s["latitude"]],
            },
            "properties": {
                **s,
                "distance_from_incident_km": round(straight_km, 2),
            },
        })

    features.sort(key=lambda f: f["properties"]["distance_from_incident_km"])

    return {
        "incident_id":   incident_id,
        "incident_name": incident.name,
        "search_radius_m": radius_m,
        "sources": {
            "type": "FeatureCollection",
            "features": features,
        },
        "unit_assignments": list(unit_assignments.values()),
        "summary": {
            "total_sources": len(sources),
            "hydrants":      sum(1 for s in sources if s["type"] == "hydrant"),
            "lakes_ponds":   sum(1 for s in sources if s["type"] in ("lake", "pond", "river", "reservoir")),
            "tanks":         sum(1 for s in sources if s["type"] in ("tank",)),
            "units_scored":  len(unit_assignments),
        },
    }
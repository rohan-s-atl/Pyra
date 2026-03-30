"""
routing.py — Route computation service. (PATCHED)

FIXES APPLIED
-------------
The core problem: router.project-osrm.org is blocked by many deployment
egress proxies (Vercel, Docker networks, corporate firewalls). Every route
attempt silently hit the straight-line fallback, making ALL ground unit
routes appear as straight lines on the map.

Strategy — 5-tier cascade, stops at first success:
  1. Local OSRM      (localhost:5001) — fastest, self-hosted, no rate limit
  2. OSRM mirror A   (osrm.route.occam.fr) — EU public mirror, no key
  3. OSRM mirror B   (routing.openstreetmap.de) — DE public mirror, no key
  4. OpenRouteService (api.openrouteservice.org) — free 2000 req/day, needs key
  5. Mapbox           (api.mapbox.com) — premium fallback, needs token
  6. Straight-line    — always succeeds, is_road_routed=False

OSRM mirrors A and B are tried BEFORE the original router.project-osrm.org
because that endpoint is frequently rate-limited and blocked by egress proxies.
The original public OSRM is still tried but de-prioritised.

Configuration (.env):
  LOCAL_OSRM_URL=http://localhost:5001/route/v1/driving  (optional)
  OPENROUTESERVICE_API_KEY=your_key   (free at openrouteservice.org)
  MAPBOX_TOKEN=your_token             (optional premium)

Air units always get straight-line routes (is_road_routed=False) —
helicopters and air tankers don't follow roads.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoint registry — tried in order, stops at first success
# ---------------------------------------------------------------------------

# Primary: local self-hosted OSRM (no rate limit, no egress block)
_LOCAL_OSRM    = settings.local_osrm_url

# Public OSRM mirrors — different domains, better egress coverage
_PUBLIC_OSRM_A = "https://router.project-osrm.org/route/v1/driving"   # original
_PUBLIC_OSRM_B = "https://routing.openstreetmap.de/routed-car/route/v1/driving"  # DE mirror

MAX_WAYPOINTS      = 120
_ENDPOINT_COOLDOWN = 60.0    # seconds before retrying a failed endpoint
_REQUEST_TIMEOUT   = 12.0    # seconds per routing request

GROUND_TYPES: frozenset[str] = frozenset({
    "engine", "hand_crew", "dozer", "water_tender", "command_unit", "rescue",
})
AIR_TYPES: frozenset[str] = frozenset({"helicopter", "air_tanker"})


# ---------------------------------------------------------------------------
# Endpoint health tracker
# ---------------------------------------------------------------------------

@dataclass
class _EndpointHealth:
    url: str
    _failed_at: float = field(default=0.0, repr=False)

    def is_cooling_down(self) -> bool:
        return (self._failed_at > 0 and
                time.monotonic() - self._failed_at < _ENDPOINT_COOLDOWN)

    def mark_failed(self) -> None:
        if not self.is_cooling_down():
            logger.warning(
                "[routing] %s unreachable — cooling down for %.0fs",
                self.url, _ENDPOINT_COOLDOWN,
            )
        self._failed_at = time.monotonic()

    def mark_ok(self) -> None:
        if self._failed_at > 0:
            logger.info("[routing] %s recovered", self.url)
        self._failed_at = 0.0


_health: dict[str, _EndpointHealth] = {
    _LOCAL_OSRM:    _EndpointHealth(url=_LOCAL_OSRM),
    _PUBLIC_OSRM_A: _EndpointHealth(url=_PUBLIC_OSRM_A),
    _PUBLIC_OSRM_B: _EndpointHealth(url=_PUBLIC_OSRM_B),
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CachedRoute:
    waypoints: list[list[float]]   # [[lat, lon], ...]
    index: int = field(default=0)
    is_road_routed: bool = True    # False = air unit or degraded straight-line

    @property
    def current(self) -> list[float]:
        return self.waypoints[self.index]

    @property
    def destination(self) -> list[float]:
        return self.waypoints[-1]

    @property
    def at_end(self) -> bool:
        return self.index >= len(self.waypoints) - 1


_route_cache: dict[str, CachedRoute] = {}


# ---------------------------------------------------------------------------
# Cache API
# ---------------------------------------------------------------------------

def get_cached_route(unit_id: str) -> Optional[CachedRoute]:
    return _route_cache.get(unit_id)

def store_route(unit_id: str, route: CachedRoute) -> None:
    _route_cache[unit_id] = route

def invalidate_route(unit_id: str) -> None:
    _route_cache.pop(unit_id, None)

def advance_waypoint(unit_id: str, step: int = 2) -> Optional[list[float]]:
    route = _route_cache.get(unit_id)
    if route is None:
        return None
    route.index = min(route.index + step, len(route.waypoints) - 1)
    return route.current


# ---------------------------------------------------------------------------
# Unit type helpers
# ---------------------------------------------------------------------------

def normalize_unit_type(raw: Optional[str]) -> str:
    aliases: dict[str, str] = {
        "tanker":       "air_tanker",
        "airtanker":    "air_tanker",
        "air":          "air_tanker",
        "heli":         "helicopter",
        "helo":         "helicopter",
        "crew":         "hand_crew",
        "handcrew":     "hand_crew",
        "water tender": "water_tender",
        "watertender":  "water_tender",
        "command":      "command_unit",
        "commandunit":  "command_unit",
    }
    return aliases.get((raw or "").strip().lower(), (raw or "").strip().lower())

def is_ground_unit(unit_type: str) -> bool:
    return normalize_unit_type(unit_type) in GROUND_TYPES

def is_air_unit(unit_type: str) -> bool:
    return normalize_unit_type(unit_type) in AIR_TYPES


# ---------------------------------------------------------------------------
# Waypoint helpers
# ---------------------------------------------------------------------------

def _downsample(waypoints: list[list[float]], target: int = MAX_WAYPOINTS) -> list[list[float]]:
    if len(waypoints) <= target:
        return waypoints
    step = max(1, len(waypoints) // target)
    sampled = waypoints[::step]
    if sampled[-1] != waypoints[-1]:
        sampled.append(waypoints[-1])
    return sampled


def _straight_line(
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
    num_points: int = 60,
) -> list[list[float]]:
    return [
        [
            round(from_lat + (to_lat - from_lat) * i / num_points, 5),
            round(from_lon + (to_lon - from_lon) * i / num_points, 5),
        ]
        for i in range(num_points + 1)
    ]


# ---------------------------------------------------------------------------
# Tier 1 & 2: OSRM endpoint (local + public mirrors)
# ---------------------------------------------------------------------------

async def _try_osrm_endpoint(
    base_url: str,
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
) -> Optional[list[list[float]]]:
    """Single attempt against one OSRM-compatible endpoint. Returns [lat,lon] list or None."""
    h = _health.get(base_url)
    if h and h.is_cooling_down():
        return None

    url = (f"{base_url}/{from_lon},{from_lat};{to_lon},{to_lat}"
           f"?overview=full&geometries=geojson")
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            res = await client.get(url)
            res.raise_for_status()
            data = res.json()

        routes = data.get("routes")
        if not routes:
            return None

        coords = routes[0]["geometry"]["coordinates"]
        if h:
            h.mark_ok()
        logger.debug("[routing] OSRM success via %s (%d waypoints)", base_url, len(coords))
        # OSRM returns [lon, lat]; we store [lat, lon]
        return [[round(lat, 5), round(lon, 5)] for lon, lat in coords]

    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
        logger.warning("[routing] OSRM %s failed: %s", base_url, exc)
        if h:
            h.mark_failed()
        return None
    except Exception as exc:
        logger.warning("[routing] OSRM %s unexpected: %s", base_url, exc)
        if h:
            h.mark_failed()
        return None


# ---------------------------------------------------------------------------
# Tier 3: OpenRouteService (free, 2000 req/day, key from openrouteservice.org)
# ---------------------------------------------------------------------------

async def _try_openrouteservice(
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
) -> Optional[list[list[float]]]:
    """
    OpenRouteService Directions API.
    Free tier: 2000 requests/day, 40/minute.
    Get a key at: https://openrouteservice.org/dev/#/signup
    Set OPENROUTESERVICE_API_KEY in your .env file.
    """
    api_key = settings.openrouteservice_api_key or os.environ.get("OPENROUTESERVICE_API_KEY")
    if not api_key:
        return None

    url = "https://api.openrouteservice.org/v2/directions/driving-car"
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    body = {
        "coordinates": [[from_lon, from_lat], [to_lon, to_lat]],
        "format": "geojson",
    }

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            res = await client.post(url, json=body, headers=headers)
            res.raise_for_status()
            data = res.json()

        features = data.get("features", [])
        if not features:
            return None

        coords = features[0]["geometry"]["coordinates"]
        logger.info("[routing] OpenRouteService success (%d waypoints)", len(coords))
        return [[round(lat, 5), round(lon, 5)] for lon, lat in coords]

    except httpx.HTTPStatusError as exc:
        logger.warning("[routing] OpenRouteService HTTP error: %s", exc)
        return None
    except Exception as exc:
        logger.warning("[routing] OpenRouteService failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Tier 4: Mapbox (optional premium)
# ---------------------------------------------------------------------------

async def _try_mapbox(
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
) -> Optional[list[list[float]]]:
    token = (
        settings.mapbox_token
        or os.environ.get("MAPBOX_TOKEN")
        or os.environ.get("MAPBOX_ACCESS_TOKEN")
    )
    if not token:
        return None

    url = (
        f"https://api.mapbox.com/directions/v5/mapbox/driving/"
        f"{from_lon},{from_lat};{to_lon},{to_lat}"
        f"?overview=full&geometries=geojson&access_token={token}"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url)
            res.raise_for_status()
            data = res.json()

        routes = data.get("routes")
        if not routes:
            return None

        coords = routes[0]["geometry"]["coordinates"]
        logger.info("[routing] Mapbox success (%d waypoints)", len(coords))
        return [[round(lat, 5), round(lon, 5)] for lon, lat in coords]

    except Exception as exc:
        logger.warning("[routing] Mapbox failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Unified fetch — 5-tier cascade
# ---------------------------------------------------------------------------

async def _fetch_road_route(
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
) -> Optional[list[list[float]]]:
    """
    Try all routing backends in priority order.
    Returns [lat, lon] waypoints or None if all fail.

    Tier 1: Local OSRM (self-hosted, fastest, no egress issues)
    Tier 2: OSRM public mirror A (router.project-osrm.org)
    Tier 3: OSRM public mirror B (routing.openstreetmap.de)
    Tier 4: OpenRouteService (free API key)
    Tier 5: Mapbox (premium token)
    """
    # Tier 1: local OSRM
    result = await _try_osrm_endpoint(_LOCAL_OSRM, from_lat, from_lon, to_lat, to_lon)
    if result:
        return result

    # Tier 2: public OSRM A
    result = await _try_osrm_endpoint(_PUBLIC_OSRM_A, from_lat, from_lon, to_lat, to_lon)
    if result:
        return result

    # Tier 3: public OSRM B (DE mirror — different egress path)
    result = await _try_osrm_endpoint(_PUBLIC_OSRM_B, from_lat, from_lon, to_lat, to_lon)
    if result:
        return result

    # Tier 4: OpenRouteService
    result = await _try_openrouteservice(from_lat, from_lon, to_lat, to_lon)
    if result:
        return result

    # Tier 5: Mapbox
    result = await _try_mapbox(from_lat, from_lon, to_lat, to_lon)
    if result:
        return result

    return None


# ---------------------------------------------------------------------------
# Public route builder — always returns CachedRoute, never None
# ---------------------------------------------------------------------------

async def build_route(
    unit_id: str,
    unit_type: str,
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
    *,
    force: bool = False,
    reroute_hook: Optional[Callable[[list[list[float]]], list[list[float]]]] = None,
) -> CachedRoute:
    """
    Build and cache a route. Always returns a CachedRoute — never raises.
    - Air units: straight-line, is_road_routed=False
    - Ground units: road route via cascade above, straight-line fallback
    """
    if not force and unit_id in _route_cache:
        return _route_cache[unit_id]

    ntype = normalize_unit_type(unit_type)

    if is_air_unit(ntype):
        waypoints = _straight_line(from_lat, from_lon, to_lat, to_lon)
        is_road   = False
    else:
        raw = await _fetch_road_route(from_lat, from_lon, to_lat, to_lon)
        if raw is not None:
            waypoints = raw
            is_road   = True
        else:
            logger.warning(
                "[routing] All routing backends unavailable for unit=%s — straight-line fallback",
                unit_id,
            )
            waypoints = _straight_line(from_lat, from_lon, to_lat, to_lon)
            is_road   = False

    if reroute_hook is not None:
        try:
            waypoints = reroute_hook(waypoints)
        except Exception as exc:
            logger.warning("[routing] reroute_hook raised: %s — ignoring", exc)

    waypoints = _downsample(waypoints)
    route = CachedRoute(waypoints=waypoints, index=0, is_road_routed=is_road)
    _route_cache[unit_id] = route
    return route


# ---------------------------------------------------------------------------
# Travel-time estimate
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


async def get_travel_time_minutes(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """OSRM duration if available, haversine fallback otherwise."""
    for base_url in (_LOCAL_OSRM, _PUBLIC_OSRM_A, _PUBLIC_OSRM_B):
        h = _health.get(base_url)
        if h and h.is_cooling_down():
            continue
        url = f"{base_url}/{lon1},{lat1};{lon2},{lat2}?overview=false"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url)
                res.raise_for_status()
                data = res.json()
            if h:
                h.mark_ok()
            return round(data["routes"][0]["duration"] / 60.0, 2)
        except Exception:
            if h:
                h.mark_failed()

    # Haversine fallback — 50 km/h average road speed
    km = _haversine_km(lat1, lon1, lat2, lon2)
    return round((km / 50.0) * 60.0, 2)

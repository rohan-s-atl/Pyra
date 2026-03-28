"""
routing.py — Route computation service.

Strategy (in priority order):
  1. Public OSRM (router.project-osrm.org) — free, reliable, no key required
  2. Local OSRM (localhost:5001) — only if operator has it running
  3. Mapbox Directions API — if MAPBOX_TOKEN set in env
  4. Straight-line fallback — always succeeds, marks is_road_routed=False

Local OSRM note: localhost:5001 is NOT running by default. Users must start it
via Docker: docker run -t -v /data:/data osrm/osrm-backend osrm-routed ...
This is intentionally optional — the public OSRM handles demo and most prod use.

Endpoint health tracking
------------------------
Each endpoint gets 60-second cooldown on failure so we don't hammer dead services.
On recovery, the cooldown is immediately cleared.

Air units
---------
Helicopters and air tankers always get straight-line routes (is_road_routed=False).

Degraded fallback
-----------------
If all routing services are unavailable, ground units get a straight-line path
so the simulation can still run. The UI should surface is_road_routed=False.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Public OSRM is primary — free, no key, globally available
PUBLIC_OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
# Local OSRM is secondary — only works if operator has it running
LOCAL_OSRM_URL  = "http://localhost:5001/route/v1/driving"

MAX_WAYPOINTS     = 120
_ENDPOINT_COOLDOWN = 60.0   # seconds before retrying a failed endpoint
_REQUEST_TIMEOUT   = 12.0   # seconds per OSRM request

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


# Initialize health trackers — public OSRM first (preferred)
_health: dict[str, _EndpointHealth] = {
    PUBLIC_OSRM_URL: _EndpointHealth(url=PUBLIC_OSRM_URL),
    LOCAL_OSRM_URL:  _EndpointHealth(url=LOCAL_OSRM_URL),
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


def _straight_line(from_lat: float, from_lon: float,
                   to_lat: float, to_lon: float,
                   num_points: int = 60) -> list[list[float]]:
    return [
        [
            round(from_lat + (to_lat - from_lat) * i / num_points, 5),
            round(from_lon + (to_lon - from_lon) * i / num_points, 5),
        ]
        for i in range(num_points + 1)
    ]


# ---------------------------------------------------------------------------
# OSRM fetch — single endpoint attempt
# ---------------------------------------------------------------------------

async def _try_osrm_endpoint(
    base_url: str,
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
) -> Optional[list[list[float]]]:
    """Single attempt against one OSRM endpoint. Returns [lat, lon] waypoints or None."""
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
        # OSRM returns [lon, lat]; we store [lat, lon]
        return [[round(lat, 5), round(lon, 5)] for lon, lat in coords]

    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning("[routing] %s: %s", base_url, exc)
        if h:
            h.mark_failed()
        return None
    except Exception as exc:
        logger.warning("[routing] %s unexpected error: %s", base_url, exc)
        if h:
            h.mark_failed()
        return None


# ---------------------------------------------------------------------------
# Mapbox fallback (optional — only if MAPBOX_TOKEN is set)
# ---------------------------------------------------------------------------

async def _try_mapbox(
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
) -> Optional[list[list[float]]]:
    """Use Mapbox Directions API if MAPBOX_TOKEN env var is set."""
    token = os.environ.get("MAPBOX_TOKEN") or os.environ.get("MAPBOX_ACCESS_TOKEN")
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
        logger.info("[routing] Mapbox route successful")
        return [[round(lat, 5), round(lon, 5)] for lon, lat in coords]

    except Exception as exc:
        logger.warning("[routing] Mapbox failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Unified fetch — tries all routing backends in order
# ---------------------------------------------------------------------------

async def _fetch_road_route(
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
) -> Optional[list[list[float]]]:
    """
    Try routing backends in priority order:
      1. Public OSRM (free, no key)
      2. Local OSRM (only if running)
      3. Mapbox (if MAPBOX_TOKEN set)
    Returns [lat, lon] waypoints or None if all fail.
    """
    # 1. Public OSRM (primary)
    result = await _try_osrm_endpoint(PUBLIC_OSRM_URL, from_lat, from_lon, to_lat, to_lon)
    if result is not None:
        return result

    # 2. Local OSRM (secondary — only if not cooling down, meaning it was healthy before)
    result = await _try_osrm_endpoint(LOCAL_OSRM_URL, from_lat, from_lon, to_lat, to_lon)
    if result is not None:
        return result

    # 3. Mapbox (optional fallback)
    result = await _try_mapbox(from_lat, from_lon, to_lat, to_lon)
    if result is not None:
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
    - Ground units: road route via OSRM/Mapbox, straight-line fallback
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
                "[routing] All routing backends unavailable for unit %s — using straight-line",
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
    # Try public OSRM first
    for base_url in (PUBLIC_OSRM_URL, LOCAL_OSRM_URL):
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

    # Haversine fallback — assume 50 km/h average road speed
    km = _haversine_km(lat1, lon1, lat2, lon2)
    return round((km / 50.0) * 60.0, 2)
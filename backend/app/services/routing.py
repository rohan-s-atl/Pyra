"""
routing.py — Route computation service. (PATCHED v2)

KEY FIX: Local OSRM is silently skipped when LOCAL_OSRM_URL points to
localhost/127.0.0.1 — which is always the case on Railway. This means
the cascade goes straight to public OSRM mirrors and then ORS without
wasting time or hitting the cooldown bug.
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

_LOCAL_OSRM    = settings.local_osrm_url
_PUBLIC_OSRM_A = "https://router.project-osrm.org/route/v1/driving"
_PUBLIC_OSRM_B = "https://routing.openstreetmap.de/routed-car/route/v1/driving"

MAX_WAYPOINTS      = 120
_ENDPOINT_COOLDOWN = 60.0
_REQUEST_TIMEOUT   = 12.0

GROUND_TYPES: frozenset[str] = frozenset({
    "engine", "hand_crew", "dozer", "water_tender", "command_unit", "rescue",
})
AIR_TYPES: frozenset[str] = frozenset({"helicopter", "air_tanker"})


def _local_osrm_is_remote() -> bool:
    """True only if LOCAL_OSRM_URL points at a real remote host (not localhost)."""
    url = (_LOCAL_OSRM or "").lower()
    return url and "localhost" not in url and "127.0.0.1" not in url and "::1" not in url


@dataclass
class _EndpointHealth:
    url: str
    _failed_at: float = field(default=0.0, repr=False)

    def is_cooling_down(self) -> bool:
        return (self._failed_at > 0 and
                time.monotonic() - self._failed_at < _ENDPOINT_COOLDOWN)

    def mark_failed(self) -> None:
        if not self.is_cooling_down():
            logger.warning("[routing] %s unreachable — cooling down for %.0fs",
                           self.url, _ENDPOINT_COOLDOWN)
        self._failed_at = time.monotonic()

    def mark_ok(self) -> None:
        if self._failed_at > 0:
            logger.info("[routing] %s recovered", self.url)
        self._failed_at = 0.0


_health: dict[str, _EndpointHealth] = {
    _PUBLIC_OSRM_A: _EndpointHealth(url=_PUBLIC_OSRM_A),
    _PUBLIC_OSRM_B: _EndpointHealth(url=_PUBLIC_OSRM_B),
}

# ORS gets its own health tracker so 429s trigger a cooldown
_ors_health = _EndpointHealth(url="https://api.openrouteservice.org")


@dataclass
class CachedRoute:
    waypoints: list[list[float]]
    index: int = field(default=0)
    is_road_routed: bool = True

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

# Units whose routes failed all backends — don't retry for 5 minutes
_failed_route_cooldown: dict[str, float] = {}
_FAILED_ROUTE_COOLDOWN_S = 300.0  # 5 minutes


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


def normalize_unit_type(raw: Optional[str]) -> str:
    aliases: dict[str, str] = {
        "tanker": "air_tanker", "airtanker": "air_tanker", "air": "air_tanker",
        "heli": "helicopter", "helo": "helicopter",
        "crew": "hand_crew", "handcrew": "hand_crew",
        "water tender": "water_tender", "watertender": "water_tender",
        "command": "command_unit", "commandunit": "command_unit",
    }
    return aliases.get((raw or "").strip().lower(), (raw or "").strip().lower())

def is_ground_unit(unit_type: str) -> bool:
    return normalize_unit_type(unit_type) in GROUND_TYPES

def is_air_unit(unit_type: str) -> bool:
    return normalize_unit_type(unit_type) in AIR_TYPES


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


async def _try_osrm(base_url: str,
                    from_lat: float, from_lon: float,
                    to_lat: float, to_lon: float,
                    use_health: bool = True) -> Optional[list[list[float]]]:
    h = _health.get(base_url) if use_health else None
    if h and h.is_cooling_down():
        return None

    url = f"{base_url}/{from_lon},{from_lat};{to_lon},{to_lat}?overview=full&geometries=geojson"
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
        logger.info("[routing] OSRM success via %s (%d waypoints)", base_url, len(coords))
        return [[round(lat, 5), round(lon, 5)] for lon, lat in coords]

    except Exception as exc:
        logger.warning("[routing] OSRM %s failed: %s", base_url, exc)
        if h:
            h.mark_failed()
        return None


async def _try_openrouteservice(from_lat: float, from_lon: float,
                                 to_lat: float, to_lon: float) -> Optional[list[list[float]]]:
    api_key = settings.openrouteservice_api_key or os.environ.get("OPENROUTESERVICE_API_KEY")
    if not api_key:
        logger.warning("[routing] OPENROUTESERVICE_API_KEY not configured — skipping ORS")
        return None

    if _ors_health.is_cooling_down():
        return None

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            res = await client.post(
                "https://api.openrouteservice.org/v2/directions/driving-car",
                json={"coordinates": [[from_lon, from_lat], [to_lon, to_lat]], "format": "geojson"},
                headers={"Authorization": api_key, "Content-Type": "application/json"},
            )
            res.raise_for_status()
            data = res.json()

        features = data.get("features", [])
        if not features:
            return None

        coords = features[0]["geometry"]["coordinates"]
        _ors_health.mark_ok()
        logger.info("[routing] OpenRouteService success (%d waypoints)", len(coords))
        return [[round(lat, 5), round(lon, 5)] for lon, lat in coords]

    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        body   = exc.response.text[:200]
        if status == 429:
            logger.warning("[routing] ORS rate limited (429) — cooling down 60s")
            _ors_health.mark_failed()
        elif status == 404:
            # Unroutable point (water / off-road) — not ORS's fault, don't penalise
            logger.warning("[routing] ORS 404 unroutable coordinate: %s", body)
        else:
            logger.warning("[routing] ORS HTTP %s: %s", status, body)
            _ors_health.mark_failed()
        return None
    except Exception as exc:
        logger.warning("[routing] ORS failed: %s", exc)
        return None


async def _try_mapbox(from_lat: float, from_lon: float,
                      to_lat: float, to_lon: float) -> Optional[list[list[float]]]:
    token = (settings.mapbox_token
             or os.environ.get("MAPBOX_TOKEN")
             or os.environ.get("MAPBOX_ACCESS_TOKEN"))
    if not token:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(
                f"https://api.mapbox.com/directions/v5/mapbox/driving/"
                f"{from_lon},{from_lat};{to_lon},{to_lat}"
                f"?overview=full&geometries=geojson&access_token={token}"
            )
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


async def _fetch_road_route(from_lat: float, from_lon: float,
                             to_lat: float, to_lon: float) -> Optional[list[list[float]]]:
    # Tier 1: local OSRM — ONLY if pointed at a real remote host, never localhost
    if _local_osrm_is_remote():
        result = await _try_osrm(_LOCAL_OSRM, from_lat, from_lon, to_lat, to_lon, use_health=False)
        if result:
            return result

    # Tier 2: public OSRM A
    result = await _try_osrm(_PUBLIC_OSRM_A, from_lat, from_lon, to_lat, to_lon)
    if result:
        return result

    # Tier 3: public OSRM B
    result = await _try_osrm(_PUBLIC_OSRM_B, from_lat, from_lon, to_lat, to_lon)
    if result:
        return result

    # Tier 4: OpenRouteService — primary working option on Railway
    result = await _try_openrouteservice(from_lat, from_lon, to_lat, to_lon)
    if result:
        return result

    # Tier 5: Mapbox
    result = await _try_mapbox(from_lat, from_lon, to_lat, to_lon)
    if result:
        return result

    return None


async def build_route(unit_id: str, unit_type: str,
                      from_lat: float, from_lon: float,
                      to_lat: float, to_lon: float,
                      *, force: bool = False,
                      reroute_hook: Optional[Callable[[list[list[float]]], list[list[float]]]] = None,
                      ) -> CachedRoute:
    if not force and unit_id in _route_cache:
        return _route_cache[unit_id]

    # Don't retry recently-failed routes — prevents ORS rate limit hammering
    if not force and unit_id in _failed_route_cooldown:
        since = time.monotonic() - _failed_route_cooldown[unit_id]
        if since < _FAILED_ROUTE_COOLDOWN_S:
            waypoints = _straight_line(from_lat, from_lon, to_lat, to_lon)
            return CachedRoute(waypoints=waypoints, index=0, is_road_routed=False)

    ntype = normalize_unit_type(unit_type)

    if is_air_unit(ntype):
        waypoints = _straight_line(from_lat, from_lon, to_lat, to_lon)
        is_road   = False
    else:
        raw = await _fetch_road_route(from_lat, from_lon, to_lat, to_lon)
        if raw is not None:
            waypoints = raw
            is_road   = True
            _failed_route_cooldown.pop(unit_id, None)  # clear cooldown on success
        else:
            logger.warning("[routing] All backends failed for unit=%s — straight-line fallback", unit_id)
            _failed_route_cooldown[unit_id] = time.monotonic()  # start cooldown
            waypoints = _straight_line(from_lat, from_lon, to_lat, to_lon)
            is_road   = False

    if reroute_hook is not None:
        try:
            waypoints = reroute_hook(waypoints)
        except Exception as exc:
            logger.warning("[routing] reroute_hook raised: %s", exc)

    waypoints = _downsample(waypoints)
    route = CachedRoute(waypoints=waypoints, index=0, is_road_routed=is_road)
    _route_cache[unit_id] = route
    return route


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


async def get_travel_time_minutes(lat1: float, lon1: float,
                                   lat2: float, lon2: float) -> float:
    for base_url in (_PUBLIC_OSRM_A, _PUBLIC_OSRM_B):
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

    km = _haversine_km(lat1, lon1, lat2, lon2)
    return round((km / 50.0) * 60.0, 2)
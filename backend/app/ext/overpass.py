from __future__ import annotations


def road_safety_rating(road: dict) -> str:
    access = (road.get('terrain_accessibility') or 'limited').lower()
    exposure = (road.get('fire_exposure_risk') or 'moderate').lower()
    if access == 'good' and exposure == 'low':
        return 'good'
    if access == 'poor' or exposure == 'high':
        return 'poor'
    return 'fair'


async def fetch_roads_near_incident(lat: float, lon: float, radius_km: float = 6.0) -> list[dict]:
    """Fallback stub when old overpass module is missing.
    Returns a small set of synthetic access routes around the incident so the UI keeps working.
    """
    delta = 0.02
    roads = []
    for idx, (dlat, dlon, name, hwy) in enumerate([
        (delta, 0.0, 'North Access Rd', 'primary'),
        (0.0, delta, 'East Access Rd', 'secondary'),
        (-delta, 0.0, 'South Access Rd', 'tertiary'),
    ], start=1):
        roads.append({
            'osm_id': idx,
            'name': name,
            'highway_type': hwy,
            'terrain_accessibility': 'good' if idx == 1 else 'limited',
            'fire_exposure_risk': 'low' if idx == 1 else 'moderate',
            'lat_start': lat + dlat,
            'lon_start': lon + dlon,
            'surface': 'paved' if idx < 3 else 'gravel',
            'lanes': '2',
            'maxspeed': '35 mph',
            'access': 'public',
        })
    return roads

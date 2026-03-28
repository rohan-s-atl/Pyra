from __future__ import annotations

import httpx

_CARDINAL = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']


def _aspect_from_gradient(north_delta: float, east_delta: float) -> str:
    if abs(north_delta) < 1e-6 and abs(east_delta) < 1e-6:
        return 'N'
    import math
    deg = (math.degrees(math.atan2(east_delta, north_delta)) + 360) % 360
    idx = int((deg + 22.5) // 45) % 8
    return _CARDINAL[idx]


async def estimate_slope(lat: float, lon: float) -> dict:
    """Best-effort terrain lookup using open-elevation. Falls back to flat terrain."""
    delta = 0.0025
    samples = [
        (lat, lon),
        (lat + delta, lon),
        (lat - delta, lon),
        (lat, lon + delta),
        (lat, lon - delta),
    ]
    locs = '|'.join(f'{a},{b}' for a, b in samples)
    url = f'https://api.open-elevation.com/api/v1/lookup?locations={locs}'
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url)
            data = res.json().get('results', []) if res.status_code == 200 else []
            if len(data) >= 5:
                c = data[0]['elevation']
                n = data[1]['elevation']
                s = data[2]['elevation']
                e = data[3]['elevation']
                w = data[4]['elevation']
                north_delta = n - s
                east_delta = e - w
                rise = max(abs(north_delta), abs(east_delta)) / 2.0
                run_m = 111000 * delta
                slope_percent = round((rise / run_m) * 100.0, 2)
                return {
                    'elevation_m': round(float(c), 1),
                    'slope_percent': slope_percent,
                    'aspect_cardinal': _aspect_from_gradient(north_delta, east_delta),
                }
    except Exception:
        pass
    return {
        'elevation_m': 0.0,
        'slope_percent': 0.0,
        'aspect_cardinal': 'N',
    }

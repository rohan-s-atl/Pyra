"""
nasa_firms.py — NASA FIRMS VIIRS hotspot fetcher.

Uses the area/csv endpoint which works with standard MAP_KEYs.
The country/csv endpoint requires special elevated access — skip it.

Get a free MAP_KEY at: https://firms.modaps.eosdis.nasa.gov/api/area/
Set it as NASA_FIRMS_API_KEY in your .env file.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# California bounding box
_CA_LAT_MIN, _CA_LAT_MAX =  32.0, 42.5
_CA_LON_MIN, _CA_LON_MAX = -125.0, -114.0

# Area endpoint — works with all standard MAP_KEYs
_AREA_URL = (
    "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    "/{key}/VIIRS_SNPP_NRT"
    "/{west},{south},{east},{north}/1"
)


def estimate_severity(frp: float | None) -> str:
    frp = float(frp or 0.0)
    if frp >= 80:
        return "critical"
    if frp >= 35:
        return "high"
    if frp >= 10:
        return "moderate"
    return "low"


def estimate_spread_risk(frp: float | None, confidence: Any = None) -> str:
    frp  = float(frp or 0.0)
    conf = str(confidence or "").lower()
    bonus = 10 if conf in {"h", "high"} else 0
    score = frp + bonus
    if score >= 80:
        return "extreme"
    if score >= 35:
        return "high"
    if score >= 10:
        return "moderate"
    return "low"


def _parse_viirs_csv(text: str) -> list[dict]:
    """Parse FIRMS CSV into hotspot dicts. Already filtered to CA bbox by API."""
    rows = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            try:
                lat = float(row.get("latitude") or row.get("lat") or 0)
                lon = float(row.get("longitude") or row.get("lon") or 0)
            except (ValueError, TypeError):
                continue

            # Extra safety filter to California
            if not (_CA_LAT_MIN <= lat <= _CA_LAT_MAX and _CA_LON_MIN <= lon <= _CA_LON_MAX):
                continue

            try:
                frp = float(row.get("frp") or 0.0)
            except (ValueError, TypeError):
                frp = 0.0

            rows.append({
                "latitude":   lat,
                "longitude":  lon,
                "frp":        frp,
                "confidence": row.get("confidence") or row.get("conf") or "nominal",
                "acq_date":   row.get("acq_date"),
            })
    except Exception as exc:
        logger.warning("[nasa_firms] CSV parse error: %s", exc)
    return rows


async def fetch_california_hotspots(days: int = 1) -> list[dict]:
    """
    Fetch VIIRS SNPP NRT hotspots for California using the area endpoint.
    Returns [] on failure — never raises.
    """
    from app.core.config import settings
    api_key = settings.nasa_firms_api_key

    if not api_key:
        logger.warning(
            "[nasa_firms] No API key set. Add NASA_FIRMS_API_KEY to your .env. "
            "Get a free key at https://firms.modaps.eosdis.nasa.gov/api/area/"
        )
        return []

    url = _AREA_URL.format(
        key=api_key,
        west=_CA_LON_MIN, south=_CA_LAT_MIN,
        east=_CA_LON_MAX, north=_CA_LAT_MAX,
    )

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            res = await client.get(url)

        if res.status_code == 400:
            logger.warning("[nasa_firms] HTTP 400 — API key may be invalid or not yet activated")
            return []
        if res.status_code == 429:
            logger.warning("[nasa_firms] HTTP 429 — rate limited (limit: 5000 requests/10min)")
            return []
        if res.status_code != 200:
            logger.warning("[nasa_firms] HTTP %d", res.status_code)
            return []

        text = res.text.strip()
        if not text or "latitude" not in text.split("\n")[0].lower():
            logger.warning("[nasa_firms] Response is not valid CSV")
            return []

        rows = _parse_viirs_csv(text)
        logger.info("[nasa_firms] Fetched %d California hotspots", len(rows))
        return rows

    except httpx.TimeoutException:
        logger.warning("[nasa_firms] Request timed out")
    except httpx.ConnectError:
        logger.warning("[nasa_firms] Connection failed")
    except Exception as exc:
        logger.warning("[nasa_firms] Unexpected error: %s", exc)

    return []
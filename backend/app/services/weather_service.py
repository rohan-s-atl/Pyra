"""
weather_service.py — Fetches weather for active incidents using Open-Meteo.

PATCH: Replaced sequential per-incident fetch loop with asyncio.gather.
Previously N incidents × 10s timeout = could exceed the 5-minute schedule
interval. Now all fetches run concurrently, total time ≈ slowest single fetch.
"""

import asyncio
import logging
import uuid
from datetime import datetime, UTC

import httpx

from app.core.database import SessionLocal
from app.models.incident import Incident
from app.models.alert import Alert

logger = logging.getLogger(__name__)

_CARDINAL = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]


def wind_degrees_to_cardinal(deg: float | None) -> str:
    if deg is None:
        return "N"
    idx = int((float(deg) + 22.5) // 45) % 8
    return _CARDINAL[idx]


async def fetch_weather(lat: float, lon: float) -> dict | None:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat:.4f}&longitude={lon:.4f}"
        "&current=wind_speed_10m,wind_direction_10m,relative_humidity_2m,temperature_2m"
        "&wind_speed_unit=mph&temperature_unit=fahrenheit&timezone=auto&forecast_days=1"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning("[weather_service] Open-Meteo HTTP %d for (%.4f, %.4f)",
                               resp.status_code, lat, lon)
                return None
            data = resp.json()
            current = data.get("current", {})
            if not current:
                return None
            return {
                "wind_speed_mph":     current.get("wind_speed_10m"),
                "wind_direction_deg": current.get("wind_direction_10m"),
                "humidity_percent":   current.get("relative_humidity_2m"),
                "temperature_f":      current.get("temperature_2m"),
            }
    except httpx.TimeoutException:
        logger.warning("[weather_service] Open-Meteo timeout for (%.4f, %.4f)", lat, lon)
        return None
    except httpx.ConnectError:
        logger.warning("[weather_service] Open-Meteo connection failed")
        return None
    except Exception as exc:
        logger.warning("[weather_service] Open-Meteo fetch failed: %s", exc)
        return None


def _update_incident_from_weather(incident: Incident, weather: dict) -> None:
    if weather.get("wind_speed_mph") is not None:
        incident.wind_speed_mph = round(float(weather["wind_speed_mph"]), 1)
    if weather.get("humidity_percent") is not None:
        incident.humidity_percent = round(float(weather["humidity_percent"]), 1)
    if weather.get("wind_direction_deg") is not None:
        incident.spread_direction = wind_degrees_to_cardinal(weather["wind_direction_deg"])
    incident.updated_at = datetime.now(UTC)


def _maybe_create_gust_alert(db, incident: Incident, wind_mph: float) -> None:
    existing = db.query(Alert).filter(
        Alert.incident_id == incident.id,
        Alert.alert_type == "weather_shift",
        Alert.title.contains("Wind"),
        Alert.is_acknowledged.is_(False),
    ).first()
    if existing:
        return
    severity = "critical" if wind_mph >= 50 else "warning"
    db.add(Alert(
        id          = f"ALT-{str(uuid.uuid4())[:8]}",
        incident_id = incident.id,
        alert_type  = "weather_shift",
        severity    = severity,
        title       = f"Extreme Wind — {round(wind_mph)} mph",
        description = (
            f"Sustained winds of {round(wind_mph)} mph recorded near {incident.name}. "
            "Expect rapid rate of spread and long-range spotting. "
            "Reassess all flank exposures and escape routes immediately."
        ),
        is_acknowledged = False,
        created_at  = datetime.now(UTC),
        expires_at  = None,
    ))
    logger.info("[weather_service] Created wind alert for %s (%.0f mph)", incident.name, wind_mph)


async def update_incident_weather() -> dict:
    """
    Background job — fetch weather for all active incidents concurrently.
    Phase 1: read incident coords from DB, then close the session.
    Phase 2: fire all HTTP fetches concurrently with no session held open.
    Phase 3: open a fresh session only to write results back.
    """
    updated = 0
    failed  = 0

    # Phase 1: read — grab coords and IDs, release connection immediately
    db = SessionLocal()
    try:
        incident_snapshots = [
            {"id": inc.id, "lat": inc.latitude, "lon": inc.longitude, "name": inc.name}
            for inc in db.query(Incident).filter(
                Incident.status.in_(["active", "contained"])
            ).all()
        ]
    finally:
        db.close()

    if not incident_snapshots:
        return {"updated": 0, "failed": 0}

    logger.info("[weather_service] Updating weather for %d incidents (concurrent)...",
                len(incident_snapshots))

    # Phase 2: concurrent HTTP — no DB connection held open
    results = await asyncio.gather(
        *[fetch_weather(s["lat"], s["lon"]) for s in incident_snapshots],
        return_exceptions=True,
    )

    # Phase 3: write — open a new session just for the DB updates
    db = SessionLocal()
    try:
        for snapshot, weather in zip(incident_snapshots, results):
            if isinstance(weather, Exception) or weather is None:
                failed += 1
                continue
            incident = db.query(Incident).filter(Incident.id == snapshot["id"]).first()
            if not incident:
                failed += 1
                continue
            _update_incident_from_weather(incident, weather)
            updated += 1
            wind = weather.get("wind_speed_mph") or 0
            if wind >= 35:
                _maybe_create_gust_alert(db, incident, wind)
        db.commit()
        logger.info("[weather_service] Done. Updated: %d, Failed: %d", updated, failed)
    except Exception as exc:
        db.rollback()
        logger.error("[weather_service] Error writing results: %s", exc, exc_info=True)
    finally:
        db.close()

    return {"updated": updated, "failed": failed}
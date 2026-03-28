"""
weather_service.py — Fetches weather for active incidents using Open-Meteo.

Open-Meteo is free, no API key required, returns current conditions including
wind speed (mph), wind direction (degrees), and relative humidity.

Run every 5 minutes via the scheduler.

Generates Alert records on extreme wind events (>= 35 mph).
"""

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
    """Convert wind direction degrees to 8-point cardinal string."""
    if deg is None:
        return "N"
    idx = int((float(deg) + 22.5) // 45) % 8
    return _CARDINAL[idx]


async def fetch_weather(lat: float, lon: float) -> dict | None:
    """
    Fetch current weather from Open-Meteo (free, no key required).

    Returns dict with wind_speed_mph, humidity_percent, wind_direction_deg,
    temperature_f, or None on failure.
    """
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat:.4f}&longitude={lon:.4f}"
        "&current=wind_speed_10m,wind_direction_10m,relative_humidity_2m,temperature_2m"
        "&wind_speed_unit=mph"
        "&temperature_unit=fahrenheit"
        "&timezone=auto"
        "&forecast_days=1"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(
                    "[weather_service] Open-Meteo returned HTTP %d for (%.4f, %.4f)",
                    resp.status_code, lat, lon,
                )
                return None

            data = resp.json()
            current = data.get("current", {})

            # Validate we got actual data
            if not current:
                logger.warning("[weather_service] Empty 'current' block from Open-Meteo")
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
    """Apply weather data to incident model fields."""
    if weather.get("wind_speed_mph") is not None:
        incident.wind_speed_mph = round(float(weather["wind_speed_mph"]), 1)
    if weather.get("humidity_percent") is not None:
        incident.humidity_percent = round(float(weather["humidity_percent"]), 1)
    if weather.get("wind_direction_deg") is not None:
        incident.spread_direction = wind_degrees_to_cardinal(weather["wind_direction_deg"])
    incident.updated_at = datetime.now(UTC)


def _maybe_create_gust_alert(db, incident: Incident, wind_mph: float) -> None:
    """Create a wind gust alert if one doesn't already exist for this incident."""
    existing = db.query(Alert).filter(
        Alert.incident_id == incident.id,
        Alert.alert_type == "weather_shift",
        Alert.title.contains("Wind"),
        Alert.is_acknowledged.is_(False),
    ).first()

    if existing:
        return

    severity = "critical" if wind_mph >= 50 else "warning"
    alert_id = f"ALT-{str(uuid.uuid4())[:8]}"

    db.add(Alert(
        id          = alert_id,
        incident_id = incident.id,
        alert_type  = "weather_shift",
        severity    = severity,
        title       = f"Extreme Wind — {round(wind_mph)} mph",
        description = (
            f"Sustained winds of {round(wind_mph)} mph recorded near {incident.name}. "
            f"Expect rapid rate of spread and long-range spotting. "
            f"Reassess all flank exposures and escape routes immediately."
        ),
        is_acknowledged = False,
        created_at  = datetime.now(UTC),
        expires_at  = None,
    ))
    logger.info(
        "[weather_service] Created wind alert for %s (%.0f mph)", incident.name, wind_mph
    )


async def update_incident_weather() -> dict:
    """
    Background job — fetch current weather for every active incident and update DB.

    Returns dict with updated/failed counts.
    Never raises — all failures are caught and logged.
    """
    db = SessionLocal()
    updated = 0
    failed  = 0

    try:
        active_incidents = db.query(Incident).filter(
            Incident.status.in_(["active", "contained"])
        ).all()

        if not active_incidents:
            logger.debug("[weather_service] No active incidents to update.")
            db.close()
            return {"updated": 0, "failed": 0}

        logger.info(
            "[weather_service] Updating weather for %d incidents...", len(active_incidents)
        )

        for incident in active_incidents:
            weather = await fetch_weather(incident.latitude, incident.longitude)
            if not weather:
                failed += 1
                logger.debug(
                    "[weather_service] Weather fetch failed for %s", incident.name
                )
                continue

            _update_incident_from_weather(incident, weather)
            updated += 1

            # Auto-alert on extreme winds
            wind = weather.get("wind_speed_mph") or 0
            if wind >= 35:
                _maybe_create_gust_alert(db, incident, wind)

        db.commit()
        logger.info(
            "[weather_service] Done. Updated: %d, Failed: %d", updated, failed
        )

    except Exception as exc:
        db.rollback()
        logger.error("[weather_service] Error: %s", exc, exc_info=True)
    finally:
        db.close()

    return {"updated": updated, "failed": failed}
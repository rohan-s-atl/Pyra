"""
aqi_service.py — Fetches air quality index for active incidents using Open-Meteo Air Quality API.

Open-Meteo AQ API is free, no key required, provides US AQI (pm2.5-based).
Run every 30 minutes via the scheduler.
"""

import logging
import httpx
import uuid
from datetime import datetime, UTC

from app.core.database import SessionLocal
from app.models.incident import Incident
from app.models.alert import Alert

logger = logging.getLogger(__name__)


def _aqi_from_pm25(pm25: float) -> int:
    """Convert PM2.5 µg/m³ to US AQI (EPA breakpoints)."""
    breakpoints = [
        (0.0,   12.0,   0,   50),
        (12.1,  35.4,   51,  100),
        (35.5,  55.4,   101, 150),
        (55.5,  150.4,  151, 200),
        (150.5, 250.4,  201, 300),
        (250.5, 500.4,  301, 500),
    ]
    for lo_c, hi_c, lo_i, hi_i in breakpoints:
        if lo_c <= pm25 <= hi_c:
            return round((hi_i - lo_i) / (hi_c - lo_c) * (pm25 - lo_c) + lo_i)
    return 500 if pm25 > 500 else 0


def _aqi_category(aqi: int) -> str:
    if aqi <= 50:  return "Good"
    if aqi <= 100: return "Moderate"
    if aqi <= 150: return "Unhealthy for Sensitive Groups"
    if aqi <= 200: return "Unhealthy"
    if aqi <= 300: return "Very Unhealthy"
    return "Hazardous"


def _aqi_alert_severity(aqi: int) -> str | None:
    if aqi >= 200: return "critical"
    if aqi >= 150: return "warning"
    return None


def _aqi_description(aqi: int) -> str:
    cat = _aqi_category(aqi)
    if aqi >= 300:
        return f"Hazardous air quality (AQI {aqi}). All personnel must use respiratory protection. Limit exposure time."
    if aqi >= 200:
        return f"Very unhealthy air quality (AQI {aqi}). Mandatory N95/P100 respirators for all crews on scene."
    if aqi >= 150:
        return f"Unhealthy air quality (AQI {aqi}) — {cat}. Respiratory protection recommended for extended exposure."
    return f"Air quality: {cat} (AQI {aqi})."


async def fetch_aqi(lat: float, lon: float) -> dict | None:
    """Fetch current AQI from Open-Meteo Air Quality API (no key required)."""
    url = (
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={lat}&longitude={lon}"
        "&current=pm2_5,us_aqi"
        "&timezone=auto"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()
            current = data.get("current", {})
            us_aqi = current.get("us_aqi")
            pm25   = current.get("pm2_5")

            if us_aqi is not None:
                aqi = int(us_aqi)
            elif pm25 is not None:
                aqi = _aqi_from_pm25(float(pm25))
            else:
                return None

            return {"aqi": aqi, "category": _aqi_category(aqi)}
    except Exception as exc:
        logger.warning(f"[aqi_service] Open-Meteo AQ fetch failed: {exc}")
        return None


async def update_incident_aqi():
    """Background job — fetch AQI for all active incidents and update the DB."""
    db = SessionLocal()
    updated = 0
    failed  = 0

    try:
        incidents = db.query(Incident).filter(
            Incident.status.in_(["active", "contained"])
        ).all()

        logger.info(f"[aqi_service] Updating AQI for {len(incidents)} incidents...")

        for incident in incidents:
            try:
                aqi_data = await fetch_aqi(incident.latitude, incident.longitude)
                if aqi_data:
                    incident.aqi          = aqi_data["aqi"]
                    incident.aqi_category = aqi_data["category"]
                    incident.updated_at   = datetime.now(UTC)
                    updated += 1

                    severity = _aqi_alert_severity(aqi_data["aqi"])
                    if severity:
                        _maybe_create_aqi_alert(db, incident, aqi_data, severity)
                else:
                    failed += 1
            except Exception as exc:
                logger.warning(f"[aqi_service] Failed for {incident.name}: {exc}")
                failed += 1

        db.commit()
        logger.info(f"[aqi_service] Done. Updated: {updated}, Skipped/Failed: {failed}")

    except Exception as exc:
        db.rollback()
        logger.error(f"[aqi_service] Error: {exc}")
    finally:
        db.close()

    return {"updated": updated, "failed": failed}


def _maybe_create_aqi_alert(db, incident: Incident, aqi_data: dict, severity: str):
    existing = db.query(Alert).filter(
        Alert.incident_id == incident.id,
        Alert.alert_type == "weather_shift",
        Alert.title.contains("AQI"),
        Alert.is_acknowledged.is_(False),
    ).first()
    if existing:
        existing.description = _aqi_description(aqi_data["aqi"])
        return
    alert_id = f"ALT-{str(uuid.uuid4())}"
    db.add(Alert(
        id=alert_id,
        incident_id=incident.id,
        alert_type="weather_shift",
        severity=severity,
        title=f"Air Quality Alert — AQI {aqi_data['aqi']}",
        description=_aqi_description(aqi_data["aqi"]),
        is_acknowledged=False,
        created_at=datetime.now(UTC),
        expires_at=None,
    ))

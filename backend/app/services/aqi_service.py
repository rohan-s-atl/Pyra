"""
aqi_service.py — Fetches AQI for active incidents using Open-Meteo Air Quality API.

PATCH: Replaced sequential fetch loop with asyncio.gather for concurrent fetches.
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


def _aqi_from_pm25(pm25: float) -> int:
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
            if hi_c == lo_c:
                return lo_i
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
    url = (
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={lat}&longitude={lon}"
        "&current=pm2_5,us_aqi&timezone=auto"
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
        logger.warning("[aqi_service] Open-Meteo AQ fetch failed: %s", exc)
        return None


def _maybe_create_aqi_alert(db, incident: Incident, aqi_data: dict, severity: str) -> None:
    existing = db.query(Alert).filter(
        Alert.incident_id == incident.id,
        Alert.alert_type == "weather_shift",
        Alert.title.contains("AQI"),
        Alert.is_acknowledged.is_(False),
    ).first()
    if existing:
        existing.description = _aqi_description(aqi_data["aqi"])
        return
    db.add(Alert(
        id=f"ALT-{str(uuid.uuid4())}",
        incident_id=incident.id,
        alert_type="weather_shift",
        severity=severity,
        title=f"Air Quality Alert — AQI {aqi_data['aqi']}",
        description=_aqi_description(aqi_data["aqi"]),
        is_acknowledged=False,
        created_at=datetime.now(UTC),
        expires_at=None,
    ))


async def update_incident_aqi() -> dict:
    """
    Background job — fetch AQI for all active incidents concurrently.
    Phase 1: read coords from DB and close session.
    Phase 2: concurrent HTTP fetches with no connection held.
    Phase 3: fresh session to write results.
    """
    updated = 0
    failed  = 0

    # Phase 1: read
    db = SessionLocal()
    try:
        incident_snapshots = [
            {"id": inc.id, "lat": inc.latitude, "lon": inc.longitude}
            for inc in db.query(Incident).filter(
                Incident.status.in_(["active", "contained"])
            ).all()
        ]
    finally:
        db.close()

    if not incident_snapshots:
        return {"updated": 0, "failed": 0}

    logger.info("[aqi_service] Updating AQI for %d incidents (concurrent)...",
                len(incident_snapshots))

    # Phase 2: concurrent HTTP — no DB connection held open
    results = await asyncio.gather(
        *[fetch_aqi(s["lat"], s["lon"]) for s in incident_snapshots],
        return_exceptions=True,
    )

    # Phase 3: write
    db = SessionLocal()
    try:
        for snapshot, aqi_data in zip(incident_snapshots, results):
            if isinstance(aqi_data, Exception) or aqi_data is None:
                failed += 1
                continue
            incident = db.query(Incident).filter(Incident.id == snapshot["id"]).first()
            if not incident:
                failed += 1
                continue
            incident.aqi          = aqi_data["aqi"]
            incident.aqi_category = aqi_data["category"]
            incident.updated_at   = datetime.now(UTC)
            updated += 1
            severity = _aqi_alert_severity(aqi_data["aqi"])
            if severity:
                _maybe_create_aqi_alert(db, incident, aqi_data, severity)
        db.commit()
        logger.info("[aqi_service] Done. Updated: %d, Failed: %d", updated, failed)
    except Exception as exc:
        db.rollback()
        logger.error("[aqi_service] Error writing results: %s", exc)
    finally:
        db.close()

    return {"updated": updated, "failed": failed}
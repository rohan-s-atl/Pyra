"""
triage.py — Alert triage endpoint.

PATCHES
-------
1. Cache key now includes a hash of incident fields that affect urgency
   (wind, humidity, containment). A stale triage result from when containment
   was 10% is no longer served unchanged when it reaches 90%.
2. Cache now uses a 120s TTL instead of indefinite storage — ensures results
   stay fresh through the simulation cycle.
3. _make_cache_key no-op function removed; logic inlined directly.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
import anthropic
import hashlib
import logging
import time

from app.core.database import get_db
from app.core.config import settings
from app.core.security import require_any_role
from app.models.alert import Alert
from app.models.incident import Incident
from app.models.user import User
from app.core.limiter import limiter

router = APIRouter(prefix="/api/triage", tags=["Triage"])
logger = logging.getLogger(__name__)

_triage_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL   = 120.0    # seconds — matches simulation cycle cadence
_CACHE_MAX   = 500


def _cache_key(alert_id: str, incident: Incident | None) -> str:
    """
    Key includes alert ID plus a hash of incident fields that affect urgency.
    Prevents stale results from being served after incident state changes.
    """
    if incident is None:
        return alert_id
    state = (
        f"{incident.wind_speed_mph}:{incident.humidity_percent}"
        f":{incident.containment_percent}:{incident.spread_risk}"
    )
    inc_hash = hashlib.md5(state.encode()).hexdigest()[:8]
    return f"{alert_id}:{inc_hash}"


def _cache_get(key: str) -> dict | None:
    entry = _triage_cache.get(key)
    if not entry:
        return None
    ts, result = entry
    if time.monotonic() - ts > _CACHE_TTL:
        del _triage_cache[key]
        return None
    return result


def _cache_set(key: str, result: dict) -> None:
    if len(_triage_cache) >= _CACHE_MAX:
        keys_to_evict = list(_triage_cache.keys())[:_CACHE_MAX // 10]
        for k in keys_to_evict:
            _triage_cache.pop(k, None)
    _triage_cache[key] = (time.monotonic(), result)


def _urgency_from_text(text: str) -> str:
    upper = text.upper()
    if "IMMEDIATE" in upper:
        return "immediate"
    if "LOW" in upper:
        return "low"
    return "monitor"


@router.get("/{alert_id}", summary="Get AI triage score for an alert")
@limiter.limit("15/minute")
async def triage_alert(
    alert_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        return {"alert_id": alert_id, "triage": "Alert no longer available.", "urgency": "monitor"}

    incident = None
    if alert.incident_id:
        incident = db.query(Incident).filter(Incident.id == alert.incident_id).first()

    cache_key = _cache_key(alert_id, incident)
    cached = _cache_get(cache_key)
    if cached:
        return cached

    # Short-circuit for containment_complete
    if alert.alert_type == "containment_complete":
        result = {
            "alert_id": alert_id,
            "triage":   "MONITOR — Fire fully contained, units recalling to base.",
            "urgency":  "low",
        }
        _cache_set(cache_key, result)
        return result

    # No API key — rule-based fallback
    if not settings.anthropic_api_key:
        urgency_map = {"critical": "immediate", "warning": "monitor", "info": "low"}
        result = {
            "alert_id": alert_id,
            "triage":   f"{alert.severity.upper()} — {alert.title}. Follow standard ICS protocol.",
            "urgency":  urgency_map.get(alert.severity, "monitor"),
        }
        _cache_set(cache_key, result)
        return result

    inc_context = ""
    if incident:
        inc_context = (
            f"Incident: {incident.name} | Severity: {incident.severity} | "
            f"Wind: {incident.wind_speed_mph or 0:.0f}mph | "
            f"Humidity: {incident.humidity_percent or 0:.0f}% | "
            f"Containment: {incident.containment_percent or 0:.0f}%"
        )

    prompt = (
        f"You are a CAL FIRE incident support AI. Triage this alert in exactly ONE sentence (max 15 words).\n\n"
        f"Alert Type: {alert.alert_type}\nSeverity: {alert.severity}\n"
        f"Title: {alert.title}\nDescription: {alert.description}\n"
        f"{inc_context}\n\n"
        f"Respond with: urgency (IMMEDIATE/MONITOR/LOW) + action. No extra text."
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}],
        )
        triage_text = message.content[0].text.strip()
    except Exception as e:
        logger.warning("[triage] AI call failed for alert=%s: %s", alert_id, e)
        urgency_map = {"critical": "immediate", "warning": "monitor", "info": "low"}
        result = {
            "alert_id": alert_id,
            "triage":   f"{alert.severity.upper()} — {alert.title}. Follow standard protocol.",
            "urgency":  urgency_map.get(alert.severity, "monitor"),
        }
        _cache_set(cache_key, result)
        return result

    result = {
        "alert_id": alert_id,
        "triage":   triage_text,
        "urgency":  _urgency_from_text(triage_text),
    }
    _cache_set(cache_key, result)
    return result
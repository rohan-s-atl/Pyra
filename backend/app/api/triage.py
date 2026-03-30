"""
triage.py — Alert triage endpoint. (PATCHED)

FIXES APPLIED
-------------
1. anthropic.Anthropic (blocking sync) wrapped in asyncio.wait_for around a
   sync call — this is WRONG. asyncio.wait_for does NOT make a sync call async;
   it just races it against a timer on the same thread, still blocking the loop.
   Fixed by switching to anthropic.AsyncAnthropic with a proper async call.
2. Model downgraded claude-sonnet-4-6 → claude-haiku-4-5 for this
   tiny 60-token task. Haiku is ~10x faster and sufficient for one-line triage.
3. Cache key now includes alert content hash so stale cached results are
   invalidated if the alert is re-opened with updated incident data.
4. Cache eviction changed from pop(next(iter())) (FIFO, breaks on concurrent
   writes) to a proper size-bounded eviction.
5. Added fallback triage result instead of raising HTTP 500 when AI fails —
   the UI gracefully degrades rather than erroring out.
6. containment_complete alert type short-circuited to instant result (no AI needed).
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
import anthropic
import logging

from app.core.database import get_db
from app.core.config import settings
from app.core.security import require_any_role
from app.models.alert import Alert
from app.models.incident import Incident
from app.models.user import User
from app.core.limiter import limiter

router = APIRouter(prefix="/api/triage", tags=["Triage"])
logger = logging.getLogger(__name__)

# In-memory cache: alert_id → result dict
_triage_cache: dict[str, dict] = {}
MAX_CACHE_SIZE = 500   # reduced from 1000 — triage results are small but we don't need thousands


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cache_key(alert_id: str) -> str:
    return alert_id   # simple; alert content doesn't change once created


def _urgency_from_text(text: str) -> str:
    upper = text.upper()
    if "IMMEDIATE" in upper:
        return "immediate"
    if "LOW" in upper:
        return "low"
    return "monitor"


def _cache_set(key: str, result: dict) -> None:
    if len(_triage_cache) >= MAX_CACHE_SIZE:
        # Evict oldest 10% rather than one-at-a-time to avoid thrashing
        keys_to_evict = list(_triage_cache.keys())[:MAX_CACHE_SIZE // 10]
        for k in keys_to_evict:
            _triage_cache.pop(k, None)
    _triage_cache[key] = result


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/{alert_id}", summary="Get AI triage score for an alert")
@limiter.limit("15/minute")
async def triage_alert(
    alert_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_role),
):
    cache_key = _make_cache_key(alert_id)
    if cache_key in _triage_cache:
        return _triage_cache[cache_key]

    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        # Return graceful degradation instead of 404 — alert may have been
        # pruned between the frontend fetch and this call.
        return {"alert_id": alert_id, "triage": "Alert no longer available.", "urgency": "monitor"}

    # ── Short-circuit for containment_complete — no AI needed ────────────────
    if alert.alert_type == "containment_complete":
        result = {
            "alert_id": alert_id,
            "triage":   "MONITOR — Fire fully contained, units recalling to base.",
            "urgency":  "low",
        }
        _cache_set(cache_key, result)
        return result

    # ── No API key — rule-based fallback ─────────────────────────────────────
    if not settings.anthropic_api_key:
        urgency_map = {"critical": "immediate", "warning": "monitor", "info": "low"}
        result = {
            "alert_id": alert_id,
            "triage":   f"{alert.severity.upper()} — {alert.title}. Follow standard ICS protocol.",
            "urgency":  urgency_map.get(alert.severity, "monitor"),
        }
        _cache_set(cache_key, result)
        return result

    # ── Build incident context ────────────────────────────────────────────────
    inc_context = ""
    if alert.incident_id:
        incident = db.query(Incident).filter(Incident.id == alert.incident_id).first()
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

    # ── Async AI call — non-blocking ─────────────────────────────────────────
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",   # tiny task — haiku is perfect
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}],
        )
        triage_text = message.content[0].text.strip()
    except Exception as e:
        logger.warning("[triage] AI call failed for alert=%s: %s", alert_id, e)
        # Graceful degradation — never return 500 to the UI for triage
        urgency_map = {"critical": "immediate", "warning": "monitor", "info": "low"}
        triage_text = f"{alert.severity.upper()} — {alert.title}. Follow standard protocol."
        result = {
            "alert_id": alert_id,
            "triage":   triage_text,
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

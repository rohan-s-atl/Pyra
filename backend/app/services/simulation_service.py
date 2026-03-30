"""
simulation_service.py — Simulation orchestrator. (PATCHED)

FIXES APPLIED
-------------
1. Alert explosion — hard cap (MAX_UNACKED_ALERTS_PER_INCIDENT=15) + periodic
   prune of acknowledged alerts prevents unbounded DB growth.
2. Containment auto-removal — incidents reaching 100% are marked "contained",
   all units recalled, and a one-shot notification alert is inserted.
3. Acreage growth — active fires grow incrementally so satellite detections
   show non-null acres_burned from the start.
4. Alert check interval raised 15→30 ticks; route alert capped at 3/incident.
5. Dedup title prefix extended to 40 chars.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, UTC

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.alert import Alert
from app.models.incident import Incident
from app.models.resource import Resource
from app.models.route import Route
from app.models.unit import Unit
from app.services import movement as mv
from app.services.routing import (
    build_route,
    get_cached_route,
    is_ground_unit,
    is_air_unit,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

CONTAINMENT_GAIN_PER_UNIT        = 0.02
WIND_VARIATION                   = 2.0
HUMIDITY_VARIATION               = 1.5
WIND_ALERT_THRESHOLD             = 25.0
HUMIDITY_ALERT_THRESHOLD         = 12.0
ROUTE_UPDATE_INTERVAL            = 300
ALERT_CHECK_INTERVAL             = 30    # raised from 15 — halves alert generation rate
PRUNE_INTERVAL                   = 150   # ticks between DB alert pruning (~5 min)
MAX_UNACKED_ALERTS_PER_INCIDENT  = 15    # hard cap on live alerts per incident
MAX_ACKED_ALERTS_PER_INCIDENT    = 50    # keep history but prune oldest
GLOBAL_ACKED_ALERT_PRUNE_LIMIT   = 500   # total acked alerts in DB before bulk purge

_sim_tick:              int  = 0
_running:               bool = False
_route_builder_running: bool = False
_contained_notified:    set[str] = set()   # prevent duplicate "fully contained" alerts


# ---------------------------------------------------------------------------
# Entry point: simulation tick
# ---------------------------------------------------------------------------

async def run_simulation_cycle() -> None:
    global _running
    if _running:
        logger.debug("[simulation] Previous tick still running — skipping")
        return
    _running = True
    try:
        _tick()
    except Exception as exc:
        logger.exception("[simulation] Unhandled error in tick: %s", exc)
    finally:
        _running = False


def _tick() -> None:
    global _sim_tick
    _sim_tick += 1

    db: Session = SessionLocal()
    try:
        _run_phase("advance_positions",    _advance_positions,     db)
        _run_phase("rotate_on_scene",      _rotate_on_scene_units, db)
        _run_phase("progress_containment", _progress_containment,  db)
        _run_phase("grow_acreage",         _grow_acreage,          db)
        _run_phase("vary_weather",         _vary_weather,          db)

        if _sim_tick % ALERT_CHECK_INTERVAL == 0:
            _run_phase("weather_alerts",     _check_weather_alerts,     db)
            _run_phase("operational_alerts", _check_operational_alerts, db)

        if _sim_tick % ROUTE_UPDATE_INTERVAL == 0:
            _run_phase("route_conditions", _update_route_conditions, db)

        if _sim_tick % PRUNE_INTERVAL == 0:
            _run_phase("alert_pruning", _prune_old_alerts, db)

        db.commit()
        logger.debug("[simulation] Tick %d complete", _sim_tick)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _run_phase(name: str, fn, db: Session) -> None:
    try:
        with db.begin_nested():
            fn(db)
    except Exception as exc:
        logger.error(
            "[simulation] Phase '%s' failed (tick %d): %s — savepoint rolled back",
            name, _sim_tick, exc,
        )


# ---------------------------------------------------------------------------
# Entry point: route builder (network I/O lives here)
# ---------------------------------------------------------------------------

async def run_route_builder() -> None:
    global _route_builder_running
    if _route_builder_running:
        logger.debug("[route_builder] Previous run still active — skipping")
        return
    _route_builder_running = True
    try:
        await _build_pending_routes()
    except Exception as exc:
        logger.exception("[route_builder] Unhandled error: %s", exc)
    finally:
        _route_builder_running = False


async def _build_pending_routes() -> None:
    db: Session = SessionLocal()
    pending: list[tuple] = []
    try:
        units = db.query(Unit).filter(
            Unit.status.in_(["en_route", "returning"])
        ).all()

        for unit in units:
            if get_cached_route(unit.id) is not None:
                continue

            if unit.latitude is None or unit.longitude is None:
                if not mv.snap_to_station(db, unit):
                    logger.warning("[route_builder] Unit=%s has no position — skipping", unit.id)
                    continue

            uid      = unit.id
            utype    = unit.unit_type
            from_lat = unit.latitude
            from_lon = unit.longitude

            if unit.status == "en_route" and unit.assigned_incident_id:
                incident = db.query(Incident).filter(
                    Incident.id == unit.assigned_incident_id
                ).first()
                if incident:
                    pending.append((uid, utype, from_lat, from_lon,
                                    incident.latitude, incident.longitude, "incident"))
                else:
                    logger.warning(
                        "[route_builder] Unit=%s en_route to missing incident — resetting", uid
                    )
                    unit.status = "available"
                    unit.assigned_incident_id = None

            elif unit.status == "en_route" and not unit.assigned_incident_id:
                logger.warning(
                    "[route_builder] Unit=%s en_route with no incident — resetting", uid
                )
                unit.status = "available"

            elif unit.status == "returning":
                station = mv.resolve_home_station(db, unit)
                if station:
                    pending.append((uid, utype, from_lat, from_lon,
                                    station.latitude, station.longitude, "base"))

        db.commit()
    finally:
        db.close()

    if not pending:
        return

    logger.info("[route_builder] Building %d route(s)", len(pending))
    tasks = [
        _build_for_unit(uid, utype, flat, flon, tlat, tlon, label)
        for uid, utype, flat, flon, tlat, tlon, label in pending
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            logger.error("[route_builder] Route task raised: %s", r)


async def _build_for_unit(
    unit_id: str, unit_type: str,
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
    destination_label: str,
) -> None:
    route = await build_route(unit_id, unit_type, from_lat, from_lon, to_lat, to_lon)
    if not route.is_road_routed and is_ground_unit(unit_type):
        logger.warning(
            "[route_builder] Unit=%s dest=%s using degraded straight-line",
            unit_id, destination_label,
        )
    else:
        logger.info(
            "[route_builder] Route ready unit=%s dest=%s waypoints=%d road=%s",
            unit_id, destination_label, len(route.waypoints), route.is_road_routed,
        )


# ---------------------------------------------------------------------------
# Phase 1: Position advancement
# ---------------------------------------------------------------------------

def _advance_positions(db: Session) -> None:
    for unit in db.query(Unit).filter(Unit.status == "en_route").all():
        mv.advance_en_route(db, unit, _sim_tick)

    for unit in db.query(Unit).filter(Unit.status == "returning").all():
        mv.advance_returning(db, unit, _sim_tick)

    for unit in db.query(Unit).filter(
        Unit.status == "available",
        Unit.assigned_incident_id.is_(None),
    ).all():
        mv.pin_idle_unit(db, unit)


_ON_SCENE_DURATION: dict[str, int] = {
    "helicopter":   30,
    "air_tanker":   30,
    "engine":       40,
    "water_tender": 40,
    "dozer":        40,
    "hand_crew":    45,
    "command_unit": 45,
}
_ON_SCENE_DEFAULT = 40


def _rotate_on_scene_units(db: Session) -> None:
    now = datetime.now(UTC)
    for unit in db.query(Unit).filter(Unit.status == "on_scene").all():
        if unit.on_scene_since is None:
            unit.on_scene_since = now
            unit.last_updated   = now
            continue

        duration = _ON_SCENE_DURATION.get(unit.unit_type, _ON_SCENE_DEFAULT)
        ts = unit.on_scene_since
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if (now - ts).total_seconds() >= duration:
            unit.status         = "returning"
            unit.on_scene_since = None
            unit.last_updated   = now
            logger.info(
                "[simulation] Unit=%s rotating off scene (type=%s)", unit.id, unit.unit_type
            )


# ---------------------------------------------------------------------------
# Phase 2: Containment + auto-removal at 100%
# ---------------------------------------------------------------------------

def _progress_containment(db: Session) -> None:
    global _contained_notified

    for incident in db.query(Incident).filter(Incident.status == "active").all():
        on_scene = db.query(Unit).filter(
            Unit.assigned_incident_id == incident.id,
            Unit.status == "on_scene",
        ).count()

        if on_scene <= 0:
            continue

        gain    = CONTAINMENT_GAIN_PER_UNIT * on_scene * random.uniform(0.3, 1.2)
        current = incident.containment_percent or 0.0
        new_pct = round(min(100.0, current + gain * 0.1), 1)
        incident.containment_percent = new_pct
        incident.updated_at          = datetime.now(UTC)

        # ── Auto-contain at 100% ────────────────────────────────────────────
        if new_pct >= 100.0 and incident.id not in _contained_notified:
            incident.status              = "contained"
            incident.containment_percent = 100.0
            _contained_notified.add(incident.id)

            # Recall all active units
            for unit in db.query(Unit).filter(
                Unit.assigned_incident_id == incident.id,
                Unit.status.in_(["en_route", "on_scene", "staging"]),
            ).all():
                unit.status       = "returning"
                unit.last_updated = datetime.now(UTC)

            # One-shot notification alert
            _insert_alert_direct(
                db, incident,
                alert_type  = "containment_complete",
                severity    = "info",
                title       = f"Fire Fully Contained — {incident.name}",
                description = (
                    f"{incident.name} has reached 100% containment. "
                    f"All units are being recalled. Incident status set to CONTAINED."
                ),
            )
            logger.info("[simulation] '%s' reached 100%% — status → contained", incident.name)

        # Legacy 90% threshold
        elif new_pct >= 90.0 and incident.status == "active":
            incident.status = "contained"


# ---------------------------------------------------------------------------
# Phase 3: Acreage growth
# ---------------------------------------------------------------------------

_GROWTH_BASE: dict[str, float] = {
    "critical": 0.06,
    "high":     0.04,
    "moderate": 0.02,
    "low":      0.01,
}

_SEED_ACRES: dict[str, float] = {
    "critical": 800.0,
    "high":     200.0,
    "moderate": 50.0,
    "low":      5.0,
}


def _grow_acreage(db: Session) -> None:
    """Grow acres_burned each tick and seed zero-acre fires with a starting estimate."""
    for incident in db.query(Incident).filter(Incident.status == "active").all():
        base      = _GROWTH_BASE.get(incident.severity, 0.02)
        risk_mult = {"extreme": 3.0, "high": 2.0, "moderate": 1.0, "low": 0.5}.get(
            incident.spread_risk or "moderate", 1.0
        )
        wind_mph  = incident.wind_speed_mph or 5.0
        wind_mult = max(0.5, min(2.5, wind_mph / 15.0))

        on_scene  = db.query(Unit).filter(
            Unit.assigned_incident_id == incident.id,
            Unit.status == "on_scene",
        ).count()
        suppress  = max(0.1, 1.0 - on_scene * 0.07)

        growth  = base * risk_mult * wind_mult * suppress * random.uniform(0.5, 1.5)
        current = incident.acres_burned

        # Seed new or zero-acre incidents
        if not current:
            seed    = _SEED_ACRES.get(incident.severity, 20.0)
            current = round(seed * random.uniform(0.5, 2.0), 1)

        incident.acres_burned = round(current + growth, 1)
        incident.updated_at   = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Phase 4: Weather variation
# ---------------------------------------------------------------------------

def _vary_weather(db: Session) -> None:
    for incident in db.query(Incident).filter(
        Incident.status.in_(["active", "contained"])
    ).all():
        if incident.wind_speed_mph is not None:
            incident.wind_speed_mph = max(0.0, round(
                incident.wind_speed_mph + random.uniform(-WIND_VARIATION, WIND_VARIATION), 1))
        if incident.humidity_percent is not None:
            incident.humidity_percent = max(3.0, min(95.0, round(
                incident.humidity_percent + random.uniform(-HUMIDITY_VARIATION, HUMIDITY_VARIATION), 1)))
        incident.updated_at = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Phase 5: Weather alerts
# ---------------------------------------------------------------------------

def _check_weather_alerts(db: Session) -> None:
    for incident in db.query(Incident).filter(Incident.status == "active").all():
        if _unacked_count(db, incident.id) >= MAX_UNACKED_ALERTS_PER_INCIDENT:
            continue

        if incident.wind_speed_mph and incident.wind_speed_mph > WIND_ALERT_THRESHOLD:
            _maybe_add_alert(
                db, incident, "weather_shift", "critical",
                f"High Wind Warning — {incident.wind_speed_mph} mph",
                f"Wind speed exceeded {WIND_ALERT_THRESHOLD} mph at {incident.name}. "
                f"Expect rapid spread potential. Reassess all flank exposures immediately.",
            )
        if incident.humidity_percent and incident.humidity_percent < HUMIDITY_ALERT_THRESHOLD:
            _maybe_add_alert(
                db, incident, "weather_shift", "warning",
                f"Critical Low Humidity — {incident.humidity_percent}%",
                f"Humidity dropped below {HUMIDITY_ALERT_THRESHOLD}% at {incident.name}. "
                f"Extreme fire behavior possible. Red Flag conditions in effect.",
            )


# ---------------------------------------------------------------------------
# Phase 6: Operational alerts
# ---------------------------------------------------------------------------

def _check_operational_alerts(db: Session) -> None:
    for incident in db.query(Incident).filter(Incident.status == "active").all():
        if _unacked_count(db, incident.id) >= MAX_UNACKED_ALERTS_PER_INCIDENT:
            continue

        # Water resupply check
        tenders = db.query(Unit).filter(
            Unit.assigned_incident_id == incident.id,
            Unit.unit_type == "water_tender",
            Unit.status == "on_scene",
        ).count()
        water_sources = db.query(Resource).filter(
            Resource.incident_id == incident.id,
            Resource.resource_type == "water_source",
            Resource.status == "available",
        ).count()
        if tenders > 0 and water_sources == 0:
            _maybe_add_alert(
                db, incident, "water_source_constraint", "warning",
                f"Water Resupply Needed — {incident.name}",
                f"{tenders} water tender(s) on scene with no confirmed water source. "
                f"Identify and confirm water supply point before tender capacity is depleted.",
            )

        # Structure threat check
        if (incident.structures_threatened and incident.structures_threatened > 0 and
                incident.spread_risk in ("extreme", "high") and
                incident.containment_percent is not None and
                incident.containment_percent < 25):
            _maybe_add_alert(
                db, incident, "asset_at_risk", "critical",
                f"Structure Threat Escalating — {incident.structures_threatened} at Risk",
                f"{incident.structures_threatened} structures threatened with "
                f"{incident.spread_risk.upper()} spread risk and only "
                f"{incident.containment_percent}% containment. "
                f"Immediate structure protection deployment recommended.",
            )

        # Engine depletion check
        total_engines     = db.query(Unit).filter(Unit.unit_type == "engine").count()
        available_engines = db.query(Unit).filter(
            Unit.unit_type == "engine", Unit.status == "available",
        ).count()
        if total_engines > 0 and available_engines == 0:
            _maybe_add_alert(
                db, incident, "resource_shortage", "warning",
                "Engine Resources Depleted — No Units Available",
                f"All {total_engines} engines are currently deployed or unavailable. "
                f"Request mutual aid or await returning units before committing additional resources.",
            )

        # Route exposure check — cap at 3 routes per incident to limit alert volume
        if incident.spread_direction and incident.spread_risk in ("extreme", "high"):
            routes = db.query(Route).filter(
                Route.incident_id == incident.id,
                Route.is_currently_passable.is_(True),
                Route.fire_exposure_risk.in_(["high", "moderate"]),
            ).limit(3).all()

            for route in routes:
                if _unacked_count(db, incident.id) >= MAX_UNACKED_ALERTS_PER_INCIDENT:
                    break
                _maybe_add_alert(
                    db, incident, "route_blocked", "warning",
                    f"Route Exposure Risk — {route.label[:40]}",
                    f"Fire spreading {incident.spread_direction} with {incident.spread_risk} risk. "
                    f"{route.label} has {route.fire_exposure_risk} fire exposure. "
                    f"Monitor closely — may become impassable. Identify alternate routes now.",
                    dedup_key=route.id,
                )


# ---------------------------------------------------------------------------
# Alert helpers
# ---------------------------------------------------------------------------

def _unacked_count(db: Session, incident_id: str) -> int:
    return (
        db.query(func.count(Alert.id))
        .filter(Alert.incident_id == incident_id, Alert.is_acknowledged.is_(False))
        .scalar() or 0
    )


def _maybe_add_alert(
    db: Session,
    incident: Incident,
    alert_type: str,
    severity: str,
    title: str,
    description: str,
    dedup_key: str = "",
) -> None:
    if _unacked_count(db, incident.id) >= MAX_UNACKED_ALERTS_PER_INCIDENT:
        return

    title_prefix = title[:40]
    query = db.query(Alert).filter(
        Alert.incident_id == incident.id,
        Alert.alert_type == alert_type,
        Alert.is_acknowledged.is_(False),
    )
    if dedup_key:
        query = query.filter(Alert.title.contains(dedup_key[:20]))
    else:
        query = query.filter(Alert.title.contains(title_prefix))
    if query.first():
        return

    _insert_alert_direct(db, incident, alert_type, severity, title, description)


def _insert_alert_direct(
    db: Session,
    incident: Incident,
    alert_type: str,
    severity: str,
    title: str,
    description: str,
) -> None:
    alert_id = f"ALT-{uuid.uuid4()}"
    try:
        stmt = (
            pg_insert(Alert.__table__)
            .values(
                id=alert_id,
                incident_id=incident.id,
                alert_type=alert_type,
                severity=severity,
                title=title,
                description=description,
                is_acknowledged=False,
                created_at=datetime.now(UTC),
                expires_at=None,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        db.execute(stmt)
    except Exception:
        db.add(Alert(
            id=alert_id,
            incident_id=incident.id,
            alert_type=alert_type,
            severity=severity,
            title=title,
            description=description,
            is_acknowledged=False,
            created_at=datetime.now(UTC),
            expires_at=None,
        ))


# ---------------------------------------------------------------------------
# Phase 7: Alert pruning
# ---------------------------------------------------------------------------

def _prune_old_alerts(db: Session) -> None:
    total_acked = (
        db.query(func.count(Alert.id))
        .filter(Alert.is_acknowledged.is_(True))
        .scalar() or 0
    )

    if total_acked > GLOBAL_ACKED_ALERT_PRUNE_LIMIT:
        cutoff = total_acked - GLOBAL_ACKED_ALERT_PRUNE_LIMIT // 2
        oldest_ids = (
            db.query(Alert.id)
            .filter(Alert.is_acknowledged.is_(True))
            .order_by(Alert.created_at.asc())
            .limit(cutoff)
            .all()
        )
        ids = [r[0] for r in oldest_ids]
        if ids:
            db.query(Alert).filter(Alert.id.in_(ids)).delete(synchronize_session=False)
            logger.info("[simulation] Pruned %d old acked alerts (global limit)", len(ids))
        return

    incidents = (
        db.query(Alert.incident_id, func.count(Alert.id).label("cnt"))
        .filter(Alert.is_acknowledged.is_(True))
        .group_by(Alert.incident_id)
        .having(func.count(Alert.id) > MAX_ACKED_ALERTS_PER_INCIDENT)
        .all()
    )
    for inc_id, cnt in incidents:
        excess = cnt - MAX_ACKED_ALERTS_PER_INCIDENT
        oldest_ids = (
            db.query(Alert.id)
            .filter(Alert.incident_id == inc_id, Alert.is_acknowledged.is_(True))
            .order_by(Alert.created_at.asc())
            .limit(excess)
            .all()
        )
        ids = [r[0] for r in oldest_ids]
        if ids:
            db.query(Alert).filter(Alert.id.in_(ids)).delete(synchronize_session=False)
            logger.debug("[simulation] Pruned %d acked alerts for incident %s", len(ids), inc_id)


# ---------------------------------------------------------------------------
# Phase 8: Route condition updates (every 300 ticks)
# ---------------------------------------------------------------------------

def _update_route_conditions(db: Session) -> None:
    for incident in db.query(Incident).filter(Incident.status == "active").all():
        for route in db.query(Route).filter(Route.incident_id == incident.id).all():
            now = datetime.now(UTC)

            if (incident.spread_risk in ("extreme", "high") and
                    route.fire_exposure_risk == "high" and
                    route.is_currently_passable and
                    random.random() < 0.15):
                route.is_currently_passable = False
                route.last_verified_at = now
                logger.info("[simulation] Route '%s' blocked by fire spread", route.label)

            elif (not route.is_currently_passable and
                  incident.spread_risk in ("low", "moderate") and
                  random.random() < 0.20):
                route.is_currently_passable = True
                route.last_verified_at = now
                logger.info("[simulation] Route '%s' reopened", route.label)

            if (incident.containment_percent is not None and
                    incident.containment_percent < 20 and
                    route.fire_exposure_risk == "low" and
                    incident.spread_risk in ("extreme", "high") and
                    random.random() < 0.10):
                route.fire_exposure_risk = "moderate"
                route.last_verified_at   = now
            elif (route.fire_exposure_risk == "moderate" and
                  incident.spread_risk in ("extreme", "high") and
                  random.random() < 0.08):
                route.fire_exposure_risk = "high"
                route.last_verified_at   = now
            elif (incident.containment_percent is not None and
                  incident.containment_percent > 60 and
                  route.fire_exposure_risk in ("high", "moderate") and
                  random.random() < 0.15):
                route.fire_exposure_risk = (
                    "low" if route.fire_exposure_risk == "moderate" else "moderate"
                )
                route.last_verified_at = now

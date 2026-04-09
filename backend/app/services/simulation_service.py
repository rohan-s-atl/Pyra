"""
simulation_service.py — Simulation orchestrator.

PATCH: _contained_notified set is now pruned when incidents transition to
'out' status, preventing unbounded memory growth in long-running deployments.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time as _time
import uuid
from datetime import datetime, UTC, timezone, timedelta

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, SimSessionLocal
from app.models.alert import Alert
from app.models.incident import Incident
from app.models.resource import Resource
from app.models.route import Route
from app.models.unit import Unit
from app.services import movement as mv
from app.services.routing import (
    build_route, get_cached_route, is_ground_unit, is_air_unit,
)

logger = logging.getLogger(__name__)

CONTAINMENT_GAIN_PER_UNIT        = 0.06   # full dispatch of ~10 units reaches 100% in ~5-8 min on-scene; 2-3 batches puts fire out
CONTAINMENT_LOSS_BASE           = 0.025  # slow, realistic decay after grace period
CONTAINMENT_GRACE_MINUTES       = 12     # no loss for first 12 real-time minutes after incident start
WIND_VARIATION                   = 2.0
HUMIDITY_VARIATION               = 1.5
WIND_ALERT_THRESHOLD             = 25.0
HUMIDITY_ALERT_THRESHOLD         = 12.0
ROUTE_UPDATE_INTERVAL            = 300
ALERT_CHECK_INTERVAL             = 30
PRUNE_INTERVAL                   = 150
MAX_UNACKED_ALERTS_PER_INCIDENT  = 15
MAX_ACKED_ALERTS_PER_INCIDENT    = 50
GLOBAL_ACKED_ALERT_PRUNE_LIMIT   = 500

_sim_tick:              int  = 0
_running:               bool = False
_route_builder_running: bool = False
_contained_notified:    set[str] = set()

# Demo fire templates — used to respawn the 3 hardcoded demo fires 15 minutes
# after they are fully contained.  Keys match incident names exactly.
_DEMO_FIRE_TEMPLATES: dict[str, dict] = {
    "LNU Lightning Complex": dict(
        fire_type="wildland", severity="high", spread_risk="high",
        latitude=38.9200, longitude=-122.6500,
        acres_burned=5800, wind_speed_mph=24, humidity_percent=16,
        containment_percent=7, structures_threatened=180,
        spread_direction="NE",
        notes="Multiple ignitions from dry lightning. Merging heads on east flank.",
    ),
    "Shasta River Fire": dict(
        fire_type="wildland", severity="moderate", spread_risk="moderate",
        latitude=40.5200, longitude=-122.4100,
        acres_burned=1400, wind_speed_mph=11, humidity_percent=28,
        containment_percent=40, structures_threatened=32,
        spread_direction="SW",
        notes="Good line on north and west flanks. Head running into rocky terrain.",
    ),
    "San Jose Structure Fire": dict(
        fire_type="structure", severity="critical", spread_risk="high",
        latitude=37.3382, longitude=-121.8863,
        acres_burned=0, wind_speed_mph=5, humidity_percent=52,
        containment_percent=0, structures_threatened=6,
        spread_direction="N",
        notes="3-alarm. Commercial structure. Exposure risk to adjacent buildings.",
    ),
}
_DEMO_RESPAWN_DELAY = 15 * 60  # 15 real-world minutes in seconds
# Maps demo fire name → monotonic timestamp after which it should respawn
_demo_respawn_queue: dict[str, float] = {}

_SEVERITY_PRESSURE: dict[str, float] = {
    "low": 0.6,
    "moderate": 0.95,
    "high": 1.3,
    "critical": 1.7,
}

_SPREAD_PRESSURE: dict[str, float] = {
    "low": 0.7,
    "moderate": 1.0,
    "high": 1.35,
    "extreme": 1.8,
}


async def run_simulation_cycle() -> None:
    global _running
    if _running:
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

    # Each phase gets its own short-lived session so the DB connection is
    # acquired and released per-phase rather than held open for the whole tick.
    # This keeps pool usage at 1 connection at a time instead of accumulating
    # open connections across phases when ticks run long or overlap slightly.
    _run_phase("advance_positions",    _advance_positions)
    _run_phase("rotate_on_scene",      _rotate_on_scene_units)
    _run_phase("progress_containment", _progress_containment)
    _run_phase("demo_respawns",        _check_demo_respawns)
    _run_phase("grow_acreage",         _grow_acreage)
    _run_phase("vary_weather",         _vary_weather)

    if _sim_tick % ALERT_CHECK_INTERVAL == 0:
        _run_phase("weather_alerts",     _check_weather_alerts)
        _run_phase("operational_alerts", _check_operational_alerts)

    if _sim_tick % ROUTE_UPDATE_INTERVAL == 0:
        _run_phase("route_conditions", _update_route_conditions)

    if _sim_tick % PRUNE_INTERVAL == 0:
        _run_phase("alert_pruning", _prune_old_alerts)


def _run_phase(name: str, fn) -> None:
    """
    Run a single simulation phase in its own session.

    Opening and closing the session per-phase means the connection returns to
    the pool immediately after each phase completes — even if the phase fails.
    A failed phase no longer poisons the session for subsequent phases.
    """
    db: Session = SimSessionLocal()
    try:
        fn(db)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("[simulation] Phase '%s' failed (tick %d): %s", name, _sim_tick, exc)
    finally:
        db.close()


async def run_route_builder() -> None:
    global _route_builder_running
    if _route_builder_running:
        return
    _route_builder_running = True
    try:
        await _build_pending_routes()
    except Exception as exc:
        logger.exception("[route_builder] Unhandled error: %s", exc)
    finally:
        _route_builder_running = False


async def _build_pending_routes() -> None:
    # Phase 1: collect pending work in a short-lived session, then close it
    # BEFORE doing any async OSRM network I/O. This is critical — holding a
    # session open across awaits ties up a pool connection for the full
    # duration of the HTTP calls (potentially many seconds).
    pending: list[tuple] = []
    db: Session = SessionLocal()
    try:
        units = db.query(Unit).filter(Unit.status.in_(["en_route", "returning"])).all()

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
                    logger.warning("[route_builder] Unit=%s en_route to missing incident — resetting", uid)
                    unit.status = "available"
                    unit.assigned_incident_id = None
            elif unit.status == "en_route" and not unit.assigned_incident_id:
                logger.warning("[route_builder] Unit=%s en_route with no incident — resetting", uid)
                unit.status = "available"
            elif unit.status == "returning":
                station = mv.resolve_home_station(db, unit)
                if station:
                    pending.append((uid, utype, from_lat, from_lon,
                                    station.latitude, station.longitude, "base"))

        db.commit()
    finally:
        db.close()  # Release connection BEFORE async I/O begins

    if not pending:
        return

    # Phase 2: async OSRM calls with no session held open
    logger.info("[route_builder] Building %d route(s)", len(pending))
    BATCH_SIZE = 5
    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i:i + BATCH_SIZE]
        tasks = [
            _build_for_unit(uid, utype, flat, flon, tlat, tlon, label)
            for uid, utype, flat, flon, tlat, tlon, label in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.error("[route_builder] Route task raised: %s", r)
        if i + BATCH_SIZE < len(pending):
            await asyncio.sleep(1.5)


async def _build_for_unit(unit_id, unit_type, from_lat, from_lon, to_lat, to_lon, destination_label):
    route = await build_route(unit_id, unit_type, from_lat, from_lon, to_lat, to_lon)
    if not route.is_road_routed and is_ground_unit(unit_type):
        logger.warning("[route_builder] Unit=%s dest=%s using degraded straight-line",
                       unit_id, destination_label)
    else:
        logger.info("[route_builder] Route ready unit=%s dest=%s waypoints=%d road=%s",
                    unit_id, destination_label, len(route.waypoints), route.is_road_routed)


def _advance_positions(db: Session) -> None:
    for unit in db.query(Unit).filter(Unit.status == "en_route").all():
        mv.advance_en_route(db, unit, _sim_tick)
    for unit in db.query(Unit).filter(Unit.status == "returning").all():
        mv.advance_returning(db, unit, _sim_tick)
    for unit in db.query(Unit).filter(
        Unit.status == "available", Unit.assigned_incident_id.is_(None)
    ).all():
        mv.pin_idle_unit(db, unit)


_ON_SCENE_DURATION: dict[str, int] = {
    "helicopter": 180, "air_tanker": 180, "engine": 300, "water_tender": 300,
    "dozer": 300, "hand_crew": 360, "command_unit": 360,
}
_ON_SCENE_DEFAULT = 300


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
            logger.info("[simulation] Unit=%s rotating off scene (type=%s)", unit.id, unit.unit_type)


def _containment_delta(incident: Incident, on_scene: int, en_route: int) -> float:
    """
    Positive delta means containment improves; negative means the incident is
    outpacing available suppression coverage.

    Grace period: no loss for the first CONTAINMENT_GRACE_MINUTES of real time
    after incident.started_at — containment holds steady while the first
    dispatch wave is en route.
    """
    severity_pressure = _SEVERITY_PRESSURE.get((incident.severity or "moderate").lower(), 1.0)
    spread_pressure = _SPREAD_PRESSURE.get((incident.spread_risk or "moderate").lower(), 1.0)
    wind_mph = incident.wind_speed_mph if incident.wind_speed_mph is not None else 10.0
    wind_pressure = min(max(wind_mph / 18.0, 0.7), 1.8)
    humidity = incident.humidity_percent if incident.humidity_percent is not None else 25.0
    humidity_pressure = 1.25 if humidity < 15 else 1.1 if humidity < 25 else 0.95
    containment_drag = 1.1 if (incident.containment_percent or 0.0) >= 85.0 else 1.0

    incident_pressure = (
        severity_pressure *
        spread_pressure *
        wind_pressure *
        humidity_pressure *
        containment_drag
    )
    effective_coverage = on_scene + (en_route * 0.45)

    if on_scene > 0 and effective_coverage >= incident_pressure:
        surplus = effective_coverage - incident_pressure
        gain = CONTAINMENT_GAIN_PER_UNIT * (on_scene + max(0.0, surplus * 0.65))
        return gain * random.uniform(0.65, 1.25)

    # Check grace period — no loss for the first N minutes after incident start
    in_grace = False
    if incident.started_at:
        started = incident.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed_mins = (datetime.now(UTC) - started).total_seconds() / 60.0
        in_grace = elapsed_mins < CONTAINMENT_GRACE_MINUTES

    if in_grace:
        return 0.0  # Hold steady; first dispatch wave is still en route

    coverage_gap = max(0.0, incident_pressure - effective_coverage)
    if on_scene <= 0:
        coverage_gap += 0.4  # reduced from 0.8 — no panic-spiral on zero units
    loss = CONTAINMENT_LOSS_BASE * coverage_gap
    return -loss * random.uniform(0.6, 1.2)


def _progress_containment(db: Session) -> None:
    global _contained_notified

    for incident in db.query(Incident).filter(Incident.status.in_(["active", "contained"])).all():
        on_scene = db.query(Unit).filter(
            Unit.assigned_incident_id == incident.id, Unit.status == "on_scene",
        ).count()
        en_route = db.query(Unit).filter(
            Unit.assigned_incident_id == incident.id, Unit.status == "en_route",
        ).count()
        current = incident.containment_percent or 0.0
        new_pct = round(min(100.0, max(0.0, current + _containment_delta(incident, on_scene, en_route))), 1)
        incident.containment_percent = new_pct
        incident.updated_at          = datetime.now(UTC)

        if new_pct >= 100.0 and incident.id not in _contained_notified:
            incident.containment_percent = 100.0
            _contained_notified.add(incident.id)

            for unit in db.query(Unit).filter(
                Unit.assigned_incident_id == incident.id,
                Unit.status.in_(["en_route", "on_scene", "staging"]),
            ).all():
                unit.status       = "returning"
                unit.last_updated = datetime.now(UTC)

            _insert_alert_direct(
                db, incident,
                alert_type  = "containment_complete",
                severity    = "info",
                title       = f"Fire Fully Contained — {incident.name}",
                description = (
                    f"{incident.name} has reached 100% containment. "
                    f"All units are being recalled. Incident closed out."
                ),
            )

            # Remove the fire from the active system
            incident.status = "out"
            logger.info("[simulation] '%s' reached 100%% — status → out", incident.name)

            # Queue demo fires to respawn after 15 real minutes
            if incident.name in _DEMO_FIRE_TEMPLATES:
                _demo_respawn_queue[incident.name] = _time.monotonic() + _DEMO_RESPAWN_DELAY
                logger.info("[simulation] '%s' queued for respawn in 15 min", incident.name)

        elif new_pct >= 90.0:
            incident.status = "contained"
        elif incident.status == "contained" and new_pct < 90.0:
            incident.status = "active"
            logger.info("[simulation] '%s' dropped below containment threshold; status -> active", incident.name)

    # FIX: prune _contained_notified for incidents that have been closed (status='out')
    # to prevent unbounded memory growth in long-running deployments.
    if _sim_tick % 300 == 0:  # every ~10 minutes
        closed_ids = {
            row[0] for row in
            db.query(Incident.id)
            .filter(Incident.id.in_(list(_contained_notified)), Incident.status == "out")
            .all()
        }
        _contained_notified -= closed_ids
        if closed_ids:
            logger.debug("[simulation] Pruned %d closed incident IDs from _contained_notified",
                         len(closed_ids))


def _check_demo_respawns(db: Session) -> None:
    """Recreate demo fires 15 real minutes after they were fully contained."""
    now = _time.monotonic()
    ready = [name for name, ts in list(_demo_respawn_queue.items()) if now >= ts]
    for name in ready:
        # Only spawn if the fire isn't already active/contained in DB
        existing = db.query(Incident).filter(
            Incident.name == name,
            Incident.status.in_(["active", "contained"]),
        ).first()
        if existing:
            del _demo_respawn_queue[name]
            continue

        tpl = _DEMO_FIRE_TEMPLATES[name]
        now_dt = datetime.now(UTC)
        new_inc = Incident(
            id=str(uuid.uuid4()),
            name=name,
            status="active",
            started_at=now_dt,
            updated_at=now_dt,
            **tpl,
        )
        db.add(new_inc)
        del _demo_respawn_queue[name]
        logger.info("[simulation] Demo fire '%s' respawned", name)


_GROWTH_BASE: dict[str, float] = {
    "critical": 0.06, "high": 0.04, "moderate": 0.02, "low": 0.01,
}
_SEED_ACRES: dict[str, float] = {
    "critical": 800.0, "high": 200.0, "moderate": 50.0, "low": 5.0,
}


def _grow_acreage(db: Session) -> None:
    for incident in db.query(Incident).filter(Incident.status == "active").all():
        base      = _GROWTH_BASE.get(incident.severity, 0.02)
        risk_mult = {"extreme": 3.0, "high": 2.0, "moderate": 1.0, "low": 0.5}.get(
            incident.spread_risk or "moderate", 1.0
        )
        wind_mph  = incident.wind_speed_mph or 5.0
        wind_mult = max(0.5, min(2.5, wind_mph / 15.0))
        on_scene  = db.query(Unit).filter(
            Unit.assigned_incident_id == incident.id, Unit.status == "on_scene",
        ).count()
        suppress  = max(0.1, 1.0 - on_scene * 0.07)
        growth    = base * risk_mult * wind_mult * suppress * random.uniform(0.5, 1.5)
        current   = incident.acres_burned
        if not current:
            seed    = _SEED_ACRES.get(incident.severity, 20.0)
            current = round(seed * random.uniform(0.5, 2.0), 1)
        incident.acres_burned = round(current + growth, 1)
        incident.updated_at   = datetime.now(UTC)


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


def _check_weather_alerts(db: Session) -> None:
    for incident in db.query(Incident).filter(Incident.status == "active").all():
        if _unacked_count(db, incident.id) >= MAX_UNACKED_ALERTS_PER_INCIDENT:
            continue
        if incident.wind_speed_mph and incident.wind_speed_mph > WIND_ALERT_THRESHOLD:
            _maybe_add_alert(db, incident, "weather_shift", "critical",
                             f"High Wind Warning — {incident.wind_speed_mph} mph",
                             f"Wind speed exceeded {WIND_ALERT_THRESHOLD} mph at {incident.name}. "
                             f"Expect rapid spread potential. Reassess all flank exposures immediately.")
        if incident.humidity_percent and incident.humidity_percent < HUMIDITY_ALERT_THRESHOLD:
            _maybe_add_alert(db, incident, "weather_shift", "warning",
                             f"Critical Low Humidity — {incident.humidity_percent}%",
                             f"Humidity dropped below {HUMIDITY_ALERT_THRESHOLD}% at {incident.name}. "
                             f"Extreme fire behavior possible. Red Flag conditions in effect.")


def _check_operational_alerts(db: Session) -> None:
    for incident in db.query(Incident).filter(Incident.status == "active").all():
        if _unacked_count(db, incident.id) >= MAX_UNACKED_ALERTS_PER_INCIDENT:
            continue

        tenders = db.query(Unit).filter(
            Unit.assigned_incident_id == incident.id,
            Unit.unit_type == "water_tender", Unit.status == "on_scene",
        ).count()
        water_sources = db.query(Resource).filter(
            Resource.incident_id == incident.id, Resource.resource_type == "water_source",
            Resource.status == "available",
        ).count()
        if tenders > 0 and water_sources == 0:
            _maybe_add_alert(db, incident, "water_source_constraint", "warning",
                             f"Water Resupply Needed — {incident.name}",
                             f"{tenders} water tender(s) on scene with no confirmed water source. "
                             "Identify and confirm water supply point before tender capacity is depleted.")

        if (incident.structures_threatened and incident.structures_threatened > 0 and
                incident.spread_risk in ("extreme", "high") and
                incident.containment_percent is not None and
                incident.containment_percent < 25):
            _maybe_add_alert(db, incident, "asset_at_risk", "critical",
                             f"Structure Threat Escalating — {incident.structures_threatened} at Risk",
                             f"{incident.structures_threatened} structures threatened with "
                             f"{incident.spread_risk.upper()} spread risk and only "
                             f"{incident.containment_percent}% containment. "
                             "Immediate structure protection deployment recommended.")

        total_engines     = db.query(Unit).filter(Unit.unit_type == "engine").count()
        available_engines = db.query(Unit).filter(
            Unit.unit_type == "engine", Unit.status == "available"
        ).count()
        if total_engines > 0 and available_engines == 0:
            _maybe_add_alert(db, incident, "resource_shortage", "warning",
                             "Engine Resources Depleted — No Units Available",
                             f"All {total_engines} engines are currently deployed or unavailable. "
                             "Request mutual aid or await returning units before committing additional resources.")

        if incident.spread_direction and incident.spread_risk in ("extreme", "high"):
            routes = db.query(Route).filter(
                Route.incident_id == incident.id,
                Route.is_currently_passable.is_(True),
                Route.fire_exposure_risk.in_(["high", "moderate"]),
            ).limit(3).all()
            for route in routes:
                if _unacked_count(db, incident.id) >= MAX_UNACKED_ALERTS_PER_INCIDENT:
                    break
                _maybe_add_alert(db, incident, "route_blocked", "warning",
                                 f"Route Exposure Risk — {route.label[:40]}",
                                 f"Fire spreading {incident.spread_direction} with {incident.spread_risk} risk. "
                                 f"{route.label} has {route.fire_exposure_risk} fire exposure. "
                                 "Monitor closely — may become impassable. Identify alternate routes now.",
                                 dedup_key=route.id)


def _unacked_count(db: Session, incident_id: str) -> int:
    return (
        db.query(func.count(Alert.id))
        .filter(Alert.incident_id == incident_id, Alert.is_acknowledged.is_(False))
        .scalar() or 0
    )


def _maybe_add_alert(db, incident, alert_type, severity, title, description, dedup_key=""):
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


def _insert_alert_direct(db, incident, alert_type, severity, title, description):
    alert_id = f"ALT-{uuid.uuid4()}"
    try:
        stmt = (
            pg_insert(Alert.__table__)
            .values(
                id=alert_id, incident_id=incident.id, alert_type=alert_type,
                severity=severity, title=title, description=description,
                is_acknowledged=False, created_at=datetime.now(UTC), expires_at=None,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        db.execute(stmt)
    except Exception:
        db.add(Alert(
            id=alert_id, incident_id=incident.id, alert_type=alert_type,
            severity=severity, title=title, description=description,
            is_acknowledged=False, created_at=datetime.now(UTC), expires_at=None,
        ))


def _prune_old_alerts(db: Session) -> None:
    total_acked = (
        db.query(func.count(Alert.id)).filter(Alert.is_acknowledged.is_(True)).scalar() or 0
    )
    if total_acked > GLOBAL_ACKED_ALERT_PRUNE_LIMIT:
        cutoff = total_acked - GLOBAL_ACKED_ALERT_PRUNE_LIMIT // 2
        oldest_ids = (
            db.query(Alert.id).filter(Alert.is_acknowledged.is_(True))
            .order_by(Alert.created_at.asc()).limit(cutoff).all()
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
            .order_by(Alert.created_at.asc()).limit(excess).all()
        )
        ids = [r[0] for r in oldest_ids]
        if ids:
            db.query(Alert).filter(Alert.id.in_(ids)).delete(synchronize_session=False)


def _update_route_conditions(db: Session) -> None:
    for incident in db.query(Incident).filter(Incident.status == "active").all():
        for route in db.query(Route).filter(Route.incident_id == incident.id).all():
            now = datetime.now(UTC)
            if (incident.spread_risk in ("extreme", "high") and
                    route.fire_exposure_risk == "high" and
                    route.is_currently_passable and random.random() < 0.15):
                route.is_currently_passable = False
                route.last_verified_at = now
            elif (not route.is_currently_passable and
                  incident.spread_risk in ("low", "moderate") and random.random() < 0.20):
                route.is_currently_passable = True
                route.last_verified_at = now
            if (incident.containment_percent is not None and
                    incident.containment_percent < 20 and
                    route.fire_exposure_risk == "low" and
                    incident.spread_risk in ("extreme", "high") and random.random() < 0.10):
                route.fire_exposure_risk = "moderate"
                route.last_verified_at   = now
            elif (route.fire_exposure_risk == "moderate" and
                  incident.spread_risk in ("extreme", "high") and random.random() < 0.08):
                route.fire_exposure_risk = "high"
                route.last_verified_at   = now
            elif (incident.containment_percent is not None and
                  incident.containment_percent > 60 and
                  route.fire_exposure_risk in ("high", "moderate") and random.random() < 0.15):
                route.fire_exposure_risk = (
                    "low" if route.fire_exposure_risk == "moderate" else "moderate"
                )
                route.last_verified_at = now

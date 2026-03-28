"""
simulation_service.py — Simulation orchestrator.

Architecture
------------
The simulation tick (run every 2 seconds) must NEVER do network I/O.
OSRM route building is async network I/O and is explicitly separated into a
dedicated background job (`run_route_builder_job`) that runs every 10 seconds.

Tick budget (target < 50 ms):
  Phase 1  advance_positions       — pure in-memory + DB writes
  Phase 2  progress_containment    — pure DB
  Phase 3  vary_weather            — pure DB
  Phase 4  weather_alerts          — pure DB
  Phase 5  operational_alerts      — pure DB
  Phase 6  route_conditions        — pure DB (every 300 ticks)

Route builder job (separate, every 10 s):
  - Queries units that need routes (en_route / returning with no cache entry)
  - Fires OSRM calls; backoff if OSRM is down
  - Populates the in-process route cache
  - If OSRM is unreachable, writes a degraded straight-line route so units
    can still move

The `_running` guard on the tick prevents overlap if DB is slow.
The route builder has its own `_route_builder_running` guard.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, UTC

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
    invalidate_route,
    normalize_unit_type,
    is_ground_unit,
    is_air_unit,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

CONTAINMENT_GAIN_PER_UNIT = 0.02  # was 2.5 — 30 units now takes ~45min to reach 85%, not 32s
WIND_VARIATION            = 2.0
HUMIDITY_VARIATION        = 1.5
WIND_ALERT_THRESHOLD      = 25.0
HUMIDITY_ALERT_THRESHOLD  = 12.0
ROUTE_UPDATE_INTERVAL     = 300   # ticks between route-condition updates
ALERT_CHECK_INTERVAL      = 15    # ticks between alert checks (~30 seconds)

_sim_tick:             int  = 0
_running:              bool = False   # simulation tick overlap guard
_route_builder_running: bool = False  # route builder overlap guard


# ---------------------------------------------------------------------------
# Entry point: simulation tick  (called every 2 s — NO network I/O here)
# ---------------------------------------------------------------------------

async def run_simulation_cycle() -> None:
    """
    Fast synchronous-only tick.  Must complete well under 2 seconds.
    Never calls OSRM or any other network endpoint.
    """
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
        _run_phase("advance_positions",   _advance_positions,    db)
        _run_phase("progress_containment",_progress_containment, db)
        _run_phase("vary_weather",        _vary_weather,         db)
        # Alert checks run every 15 ticks (~30s) — not every 2s.
        # Running every tick creates thousands of dedup SELECT queries under load
        # and races between savepoints on persistent conditions.
        if _sim_tick % ALERT_CHECK_INTERVAL == 0:
            _run_phase("weather_alerts",      _check_weather_alerts, db)
            _run_phase("operational_alerts",  _check_operational_alerts, db)
        if _sim_tick % ROUTE_UPDATE_INTERVAL == 0:
            _run_phase("route_conditions", _update_route_conditions, db)

        db.commit()
        logger.debug("[simulation] Tick %d complete", _sim_tick)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _run_phase(name: str, fn, db: Session) -> None:
    """
    Execute one simulation phase inside a savepoint.
    On failure: roll back the savepoint, log, and continue — other phases
    in the same tick are unaffected.
    """
    try:
        with db.begin_nested():
            fn(db)
    except Exception as exc:
        logger.error(
            "[simulation] Phase '%s' failed (tick %d): %s — savepoint rolled back",
            name, _sim_tick, exc,
        )


# ---------------------------------------------------------------------------
# Entry point: route builder  (called every 10 s — network I/O lives here)
# ---------------------------------------------------------------------------

async def run_route_builder() -> None:
    """
    Background job that builds OSRM routes for units that need them.
    Runs on its own 10-second interval, completely separate from the tick.
    Has its own overlap guard so a slow OSRM call can never pile up.
    """
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
    """
    Query units that need routes and build them concurrently.

    IMPORTANT: all SQLAlchemy ORM objects are converted to plain dicts before
    the session closes.  The async gather runs after db.close(), so any lazy
    attribute access on a detached Unit/Incident would raise
    "Instance is not bound to a Session".  We avoid this by extracting every
    field we need as a plain Python value inside the session block.
    """
    db: Session = SessionLocal()
    # Each entry: (unit_id, unit_type, from_lat, from_lon, to_lat, to_lon, label)
    pending: list[tuple] = []
    try:
        units = db.query(Unit).filter(
            Unit.status.in_(["en_route", "returning"])
        ).all()

        for unit in units:
            if get_cached_route(unit.id) is not None:
                continue   # already cached

            if unit.latitude is None or unit.longitude is None:
                if not mv.snap_to_station(db, unit):
                    logger.warning("[route_builder] Unit=%s has no position — skipping", unit.id)
                    continue

            # Extract plain values NOW while session is open
            uid       = unit.id
            utype     = unit.unit_type
            from_lat  = unit.latitude
            from_lon  = unit.longitude

            if unit.status == "en_route" and unit.assigned_incident_id:
                incident = db.query(Incident).filter(
                    Incident.id == unit.assigned_incident_id
                ).first()
                if incident:
                    pending.append((uid, utype, from_lat, from_lon,
                                    incident.latitude, incident.longitude, "incident"))
                else:
                    # Incident deleted — reset orphaned unit
                    logger.warning("[route_builder] Unit=%s en_route to missing incident — resetting to available", uid)
                    unit.status = "available"
                    unit.assigned_incident_id = None

            elif unit.status == "en_route" and not unit.assigned_incident_id:
                # Stale unit left in en_route with no incident (e.g. from previous server run)
                logger.warning("[route_builder] Unit=%s en_route with no incident — resetting to available", uid)
                unit.status = "available"

            elif unit.status == "returning":
                station = mv.resolve_home_station(db, unit)
                if station:
                    pending.append((uid, utype, from_lat, from_lon,
                                    station.latitude, station.longitude, "base"))

        db.commit()   # persist any station_id corrections from resolve_home_station
    finally:
        db.close()    # session closed here — no ORM objects used after this point

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
    unit_id: str,
    unit_type: str,
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
    destination_label: str,
) -> None:
    """Build and cache a route using only plain primitive values — no ORM objects."""
    route = await build_route(
        unit_id, unit_type,
        from_lat, from_lon,
        to_lat, to_lon,
    )
    if not route.is_road_routed and is_ground_unit(unit_type):
        logger.warning(
            "[route_builder] Unit=%s dest=%s using degraded straight-line (OSRM unavailable)",
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

    for unit in db.query(Unit).filter(\
        Unit.status == "available",
        Unit.assigned_incident_id.is_(None),
    ).all():
        mv.pin_idle_unit(db, unit)

    _rotate_on_scene_units(db)


# Seconds a unit of each type stays on scene before rotating off (demo-speed)
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
    """Rotate units off scene once they've exceeded their on-scene duration.
    Units with no on_scene_since stamp (arrived before this feature) are
    stamped now and will rotate on the next eligible tick.
    """
    now = datetime.now(UTC)
    on_scene_units = db.query(Unit).filter(Unit.status == "on_scene").all()

    for unit in on_scene_units:
        # Stamp units that arrived before on_scene_since existed
        if unit.on_scene_since is None:
            unit.on_scene_since = now
            unit.last_updated = now
            continue

        duration = _ON_SCENE_DURATION.get(unit.unit_type, _ON_SCENE_DEFAULT)
        ts = unit.on_scene_since
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        elapsed = (now - ts).total_seconds()
        if elapsed >= duration:
            unit.status = "returning"
            unit.on_scene_since = None
            unit.last_updated = now
            logger.info(
                "[simulation] Unit=%s rotating off scene after %.0fs (type=%s)",
                unit.id, elapsed, unit.unit_type,
            )


# ---------------------------------------------------------------------------
# Phase 2: Containment
# ---------------------------------------------------------------------------

def _progress_containment(db: Session) -> None:
    for incident in db.query(Incident).filter(Incident.status == "active").all():
        on_scene = db.query(Unit).filter(
            Unit.assigned_incident_id == incident.id,
            Unit.status == "on_scene",
        ).count()
        if on_scene > 0:
            gain    = CONTAINMENT_GAIN_PER_UNIT * on_scene * random.uniform(0.3, 1.2)
            current = incident.containment_percent or 0.0
            incident.containment_percent = round(min(95.0, current + gain * 0.1), 1)
            if incident.containment_percent >= 90.0:
                incident.status = "contained"
            incident.updated_at = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Phase 3: Weather variation
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
# Phase 4: Weather alerts
# ---------------------------------------------------------------------------

def _check_weather_alerts(db: Session) -> None:
    for incident in db.query(Incident).filter(Incident.status == "active").all():
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
# Phase 5: Operational alerts
# ---------------------------------------------------------------------------

def _check_operational_alerts(db: Session) -> None:
    for incident in db.query(Incident).filter(Incident.status == "active").all():
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

        if incident.spread_direction and incident.spread_risk in ("extreme", "high"):
            for route in db.query(Route).filter(
                Route.incident_id == incident.id,
                Route.is_currently_passable.is_(True),
                Route.fire_exposure_risk.in_(["high", "moderate"]),
            ).all():
                _maybe_add_alert(
                    db, incident, "route_blocked", "warning",
                    f"Route Exposure Risk — {route.label[:40]}",
                    f"Fire spreading {incident.spread_direction} with {incident.spread_risk} risk. "
                    f"{route.label} has {route.fire_exposure_risk} fire exposure. "
                    f"Monitor closely — may become impassable. Identify alternate routes now.",
                    dedup_key=route.id,
                )


# ---------------------------------------------------------------------------
# Alert: deduplication + idempotent insert
# ---------------------------------------------------------------------------

def _maybe_add_alert(
    db: Session,
    incident: Incident,
    alert_type: str,
    severity: str,
    title: str,
    description: str,
    dedup_key: str = "",
) -> None:
    """
    Insert an alert only if no unacknowledged alert of the same type exists.

    ID  — uuid4, globally unique, no clock dependency.
    Insert — ON CONFLICT DO NOTHING makes this safe for concurrent writers.
    """
    # Check for any existing unacknowledged alert of this type for this incident.
    # Also match on the first 30 chars of title so "High Wind — 25.1mph" deduplicates
    # against "High Wind — 25.3mph" (same alert, just slightly different value).
    title_prefix = title[:30]
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
        # SQLite fallback (used in tests)
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
# Phase 6: Route condition updates (infrequent — every 300 ticks)
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
                route.last_verified_at = now
            elif (route.fire_exposure_risk == "moderate" and
                  incident.spread_risk in ("extreme", "high") and
                  random.random() < 0.08):
                route.fire_exposure_risk = "high"
                route.last_verified_at = now
            elif (incident.containment_percent is not None and
                  incident.containment_percent > 60 and
                  route.fire_exposure_risk in ("high", "moderate") and
                  random.random() < 0.15):
                route.fire_exposure_risk = (
                    "low" if route.fire_exposure_risk == "moderate" else "moderate"
                )
                route.last_verified_at = now
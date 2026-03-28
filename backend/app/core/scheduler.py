"""
scheduler.py — APScheduler background job registry.

Job schedule
------------
  simulation_job    2 s   — pure DB tick, NO network I/O
  route_builder_job 10 s  — OSRM route building (async, has its own overlap guard)
  weather_job       5 min — Open-Meteo weather fetch
  firms_job         10 min — NASA FIRMS hotspot sync
  aqi_job           30 min — AirNow AQI update
  terrain_job       1 h   — Open-Elevation terrain enrichment
  roads_job         2 h   — OSM road data seeding

All jobs:
  - max_instances=1 + coalesce=True → slow runs are skipped, not stacked
  - Wrapped in try/except → a failing job never kills the scheduler
  - job_status updated on every run (success or failure) for /api/ingestion/status

Simulation tick: misfire_grace_time=1 (tight) — stale ticks are discarded fast.
Route builder: misfire_grace_time=15 — tolerates slow OSRM without declaring missed.
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

job_status: dict[str, dict] = {
    "simulation":    {"last_run": None, "last_result": None, "last_error": None},
    "route_builder": {"last_run": None, "last_result": None, "last_error": None},
    "weather":       {"last_run": None, "last_result": None, "last_error": None},
    "firms":         {"last_run": None, "last_result": None, "last_error": None},
    "terrain":       {"last_run": None, "last_result": None, "last_error": None},
    "aqi":           {"last_run": None, "last_result": None, "last_error": None},
    "roads":         {"last_run": None, "last_result": None, "last_error": None},
}


# ---------------------------------------------------------------------------
# Job wrappers — all wrapped in try/except so APScheduler never crashes
# ---------------------------------------------------------------------------

async def run_simulation_job() -> None:
    try:
        from app.services.simulation_service import run_simulation_cycle
        await run_simulation_cycle()
        job_status["simulation"]["last_run"]    = datetime.now(UTC).isoformat()
        job_status["simulation"]["last_error"]  = None
    except Exception as exc:
        logger.error("[scheduler] simulation_job error: %s", exc)
        job_status["simulation"]["last_error"] = str(exc)
        job_status["simulation"]["last_run"]   = datetime.now(UTC).isoformat()


async def run_route_builder_job() -> None:
    try:
        from app.services.simulation_service import run_route_builder
        await run_route_builder()
        job_status["route_builder"]["last_run"]   = datetime.now(UTC).isoformat()
        job_status["route_builder"]["last_error"] = None
    except Exception as exc:
        logger.error("[scheduler] route_builder_job error: %s", exc)
        job_status["route_builder"]["last_error"] = str(exc)
        job_status["route_builder"]["last_run"]   = datetime.now(UTC).isoformat()


async def run_weather_job() -> None:
    logger.debug("[scheduler] weather job starting")
    try:
        from app.services.weather_service import update_incident_weather
        result = await update_incident_weather()
        job_status["weather"]["last_run"]    = datetime.now(UTC).isoformat()
        job_status["weather"]["last_result"] = result
        job_status["weather"]["last_error"]  = None
    except Exception as exc:
        logger.error("[scheduler] weather_job error: %s", exc)
        job_status["weather"]["last_error"] = str(exc)
        job_status["weather"]["last_run"]   = datetime.now(UTC).isoformat()


async def run_firms_job() -> None:
    logger.debug("[scheduler] firms job starting")
    try:
        from app.services.firms_service import sync_firms_hotspots
        result = await sync_firms_hotspots()
        job_status["firms"]["last_run"]    = datetime.now(UTC).isoformat()
        job_status["firms"]["last_result"] = result
        job_status["firms"]["last_error"]  = None
    except Exception as exc:
        logger.error("[scheduler] firms_job error: %s", exc)
        job_status["firms"]["last_error"] = str(exc)
        job_status["firms"]["last_run"]   = datetime.now(UTC).isoformat()


async def run_terrain_job() -> None:
    logger.debug("[scheduler] terrain job starting")
    try:
        from app.services.terrain_service import enrich_incidents_terrain
        result = await enrich_incidents_terrain()
        job_status["terrain"]["last_run"]    = datetime.now(UTC).isoformat()
        job_status["terrain"]["last_result"] = result
        job_status["terrain"]["last_error"]  = None
    except Exception as exc:
        logger.error("[scheduler] terrain_job error: %s", exc)
        job_status["terrain"]["last_error"] = str(exc)
        job_status["terrain"]["last_run"]   = datetime.now(UTC).isoformat()


async def run_aqi_job() -> None:
    logger.debug("[scheduler] AQI job starting")
    try:
        from app.services.aqi_service import update_incident_aqi
        result = await update_incident_aqi()
        job_status["aqi"]["last_run"]    = datetime.now(UTC).isoformat()
        job_status["aqi"]["last_result"] = result
        job_status["aqi"]["last_error"]  = None
    except Exception as exc:
        logger.error("[scheduler] aqi_job error: %s", exc)
        job_status["aqi"]["last_error"] = str(exc)
        job_status["aqi"]["last_run"]   = datetime.now(UTC).isoformat()


async def run_roads_job() -> None:
    logger.debug("[scheduler] roads job starting")
    try:
        from app.services.road_service import seed_incident_routes
        result = await seed_incident_routes()
        job_status["roads"]["last_run"]    = datetime.now(UTC).isoformat()
        job_status["roads"]["last_result"] = result
        job_status["roads"]["last_error"]  = None
    except Exception as exc:
        logger.error("[scheduler] roads_job error: %s", exc)
        job_status["roads"]["last_error"] = str(exc)
        job_status["roads"]["last_run"]   = datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Scheduler initialisation
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    if scheduler.running:
        return

    # Tight tick — must finish in < 2 s. misfire_grace_time=1 discards stale ticks fast.
    _add(run_simulation_job,    "simulation_job",    "Run simulation cycle",
         IntervalTrigger(seconds=2),   misfire=1)

    # Route builder — network I/O, runs independently every 10 s.
    _add(run_route_builder_job, "route_builder_job", "Build pending OSRM routes",
         IntervalTrigger(seconds=10),  misfire=15)

    _add(run_weather_job,  "weather_job",  "Update incident weather",
         IntervalTrigger(minutes=5),   misfire=30)

    _add(run_firms_job,    "firms_job",    "Sync NASA FIRMS hotspots",
         IntervalTrigger(minutes=10),  misfire=30)

    _add(run_terrain_job,  "terrain_job",  "Enrich incidents with terrain data",
         IntervalTrigger(hours=1),     misfire=120)

    _add(run_aqi_job,      "aqi_job",      "Update incident AQI",
         IntervalTrigger(minutes=30),  misfire=60)

    _add(run_roads_job,    "roads_job",    "Seed incident routes from OSM",
         IntervalTrigger(hours=2),     misfire=120)

    scheduler.start()
    logger.info(
        "[scheduler] Started — "
        "simulation: 2s | route_builder: 10s | weather: 5m | "
        "FIRMS: 10m | terrain: 1h | AQI: 30m | roads: 2h"
    )


def _add(func, job_id: str, name: str, trigger, misfire: int = 30) -> None:
    scheduler.add_job(
        func,
        trigger=trigger,
        id=job_id,
        name=name,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=misfire,
    )
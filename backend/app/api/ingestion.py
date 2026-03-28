from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.scheduler import (
    job_status,
    run_weather_job,
    run_firms_job,
    run_terrain_job,
    run_aqi_job,
    run_roads_job,
)
from app.core.security import require_dispatcher_or_above
from app.models.user import User

router = APIRouter(prefix="/api/ingestion", tags=["Ingestion"])

JOB_SCHEDULES = {
    "weather":  "every 5 minutes (Open-Meteo + NWS stations)",
    "firms":    "every 10 minutes (NASA FIRMS VIIRS)",
    "terrain":  "every 1 hour (Open-Elevation)",
    "aqi":      "every 30 minutes (AirNow)",
    "roads":    "every 2 hours (OpenStreetMap Overpass)",
}


@router.get("/status", summary="Get ingestion job status for all data sources")
def get_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),
):
    return {
        "jobs": {
            name: {
                "schedule":    JOB_SCHEDULES.get(name, "scheduled"),
                "last_run":    job_status[name]["last_run"],
                "last_result": job_status[name]["last_result"],
            }
            for name in ("weather", "firms", "terrain", "aqi", "roads")
        }
    }


@router.post("/trigger/weather", summary="Manually trigger weather update (Open-Meteo + NWS)")
async def trigger_weather(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),
):
    await run_weather_job()
    return {"status": "ok", "result": job_status["weather"]["last_result"]}


@router.post("/trigger/firms", summary="Manually trigger NASA FIRMS satellite sync")
async def trigger_firms(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),
):
    await run_firms_job()
    return {"status": "ok", "result": job_status["firms"]["last_result"]}


@router.post("/trigger/terrain", summary="Manually trigger terrain enrichment (Open-Elevation)")
async def trigger_terrain(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),
):
    await run_terrain_job()
    return {"status": "ok", "result": job_status["terrain"]["last_result"]}


@router.post("/trigger/aqi", summary="Manually trigger AQI update (AirNow)")
async def trigger_aqi(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),
):
    await run_aqi_job()
    return {"status": "ok", "result": job_status["aqi"]["last_result"]}


@router.post("/trigger/roads", summary="Manually trigger OSM road data seeding (Overpass)")
async def trigger_roads(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),
):
    await run_roads_job()
    return {"status": "ok", "result": job_status["roads"]["last_result"]}
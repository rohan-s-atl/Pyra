from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from slowapi.middleware import SlowAPIMiddleware

from app.core.limiter import limiter
from app.api import (
    alerts,
    auth,
    audit,
    briefing,
    chat,
    dispatch,
    dispatch_advice,
    evac_zones,
    fire_growth,
    heatmap,
    incidents,
    ingestion,
    intelligence,
    loadout,
    multi_incident,
    perimeters,
    recommendations,
    report,
    resources,
    review,
    routes,
    triage,
    units,
    water_sources,
)
from app.api.auth import seed_users
from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.scheduler import (
    start_scheduler,
)

import app.models  # noqa


logger = logging.getLogger(__name__)


def seed_default_users() -> None:
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB check
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection verified.")
    except Exception as exc:
        logger.error(f"Database connection failed on startup: {exc}")
        raise

    if settings.is_development:
        seed_default_users()

    start_scheduler()

    # Background jobs run on their scheduled intervals (weather: 5m, FIRMS: 10m, etc.)
    # No eager startup probes — they fail in dev when no incidents exist yet
    # and produce confusing log noise. The scheduler handles first-run automatically.

    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Pyra — Wildfire Response Intelligence & Command-Support Platform",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# CORS
cors_origins = settings.cors_origins
if "*" in cors_origins and settings.is_production:
    raise RuntimeError("Wildcard CORS is not allowed in production.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Core routers
app.include_router(incidents.router)
app.include_router(alerts.router)
app.include_router(units.router)
app.include_router(routes.router)
app.include_router(resources.router)
app.include_router(dispatch.router)
app.include_router(auth.router)

# Intelligence & operational routers
app.include_router(recommendations.router)
app.include_router(dispatch_advice.router)
app.include_router(intelligence.router)
app.include_router(loadout.router)
app.include_router(briefing.router)
app.include_router(chat.router)
app.include_router(triage.router)
app.include_router(review.router)
app.include_router(multi_incident.router)

# Map overlay routers
app.include_router(fire_growth.router)
app.include_router(evac_zones.router)
app.include_router(heatmap.router)
app.include_router(perimeters.router)
app.include_router(water_sources.router)

# Data & utility routers
app.include_router(report.router)
app.include_router(audit.router)
app.include_router(ingestion.router)


@app.get("/health", tags=["System"])
def health_check():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Health check DB error: {e}")
        db_status = "error"

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.env,
        "db": db_status,
    }
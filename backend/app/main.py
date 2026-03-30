"""
main.py — FastAPI application entry point.

PATCH: seed_default_users now only runs when ENV is explicitly set to a
development value. Previously it ran whenever `is_development` returned True,
which includes the case where ENV is not set at all — risking seeder running
on Railway if ENV was accidentally omitted from the environment config.
"""
from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from slowapi.middleware import SlowAPIMiddleware

from app.core.limiter import limiter
from app.api import (
    alerts, auth, audit, briefing, chat, dispatch, dispatch_advice,
    evac_zones, fire_growth, heatmap, incidents, ingestion, intelligence,
    loadout, multi_incident, perimeters, recommendations, report, resources,
    review, routes, triage, units, water_sources,
)
from app.api.auth import seed_users
from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.scheduler import start_scheduler

import app.models  # noqa

logger = logging.getLogger(__name__)

_DEV_ENVS = {"dev", "development", "local"}


def seed_default_users() -> None:
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection verified.")
    except Exception as exc:
        logger.error("Database connection failed on startup: %s", exc)
        raise

    # FIX: only seed when ENV is explicitly a development value.
    # Previously ran whenever is_development was True, which includes
    # cases where ENV is unset — risking seeder running in production.
    env_val = os.environ.get("ENV", settings.env).lower()
    if env_val in _DEV_ENVS:
        seed_default_users()
    else:
        logger.info("Skipping user seed (ENV=%s)", env_val)

    start_scheduler()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Pyra — Wildfire Response Intelligence & Command-Support Platform",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

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

app.include_router(incidents.router)
app.include_router(alerts.router)
app.include_router(units.router)
app.include_router(routes.router)
app.include_router(resources.router)
app.include_router(dispatch.router)
app.include_router(auth.router)

app.include_router(recommendations.router)
app.include_router(dispatch_advice.router)
app.include_router(intelligence.router)
app.include_router(loadout.router)
app.include_router(briefing.router)
app.include_router(chat.router)
app.include_router(triage.router)
app.include_router(review.router)
app.include_router(multi_incident.router)

app.include_router(fire_growth.router)
app.include_router(evac_zones.router)
app.include_router(heatmap.router)
app.include_router(perimeters.router)
app.include_router(water_sources.router)

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
        logger.error("Health check DB error: %s", e)
        db_status = "error"
    return {
        "status":   "ok",
        "app":      settings.app_name,
        "version":  settings.app_version,
        "env":      settings.env,
        "db":       db_status,
        "ai_ready": bool(settings.anthropic_api_key),
    }
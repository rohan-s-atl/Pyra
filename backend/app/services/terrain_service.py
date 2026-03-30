"""
Terrain enrichment service — fetches elevation, slope, and aspect for active incidents
and persists them to the database. Run on a slow schedule (hourly) since terrain doesn't change.

Also computes and stores a terrain spread multiplier used by the intelligence layer.
"""

import logging
from sqlalchemy.orm import Session
from datetime import datetime, UTC

from app.core.database import SessionLocal
from app.models.incident import Incident
from app.ext.open_elevation import estimate_slope

logger = logging.getLogger(__name__)


async def enrich_incidents_terrain():
    """
    Background job — fetch terrain data for all active incidents and update the DB.

    Phase 1: read incident list, close session.
    Phase 2: sequential async terrain fetches with no connection held.
    Phase 3: fresh session to write results.
    """
    # Phase 1: read
    db: Session = SessionLocal()
    try:
        incident_snapshots = [
            {"id": inc.id, "name": inc.name, "lat": inc.latitude, "lon": inc.longitude}
            for inc in db.query(Incident).filter(
                Incident.status.in_(["active", "contained"]),
                Incident.elevation_m.is_(None),
            ).all()
        ]
    finally:
        db.close()

    if not incident_snapshots:
        logger.info("[terrain_service] All incidents already have terrain data.")
        return {"updated": 0, "failed": 0}

    logger.info("[terrain_service] Fetching terrain for %d incidents...", len(incident_snapshots))

    # Phase 2: async fetches — no DB connection held open
    fetch_results = []
    for snap in incident_snapshots:
        try:
            terrain = await estimate_slope(snap["lat"], snap["lon"])
            fetch_results.append((snap, terrain))
            logger.info(
                "[terrain_service] %s: %dm, slope=%s%%, aspect=%s",
                snap["name"], terrain["elevation_m"],
                terrain["slope_percent"], terrain["aspect_cardinal"],
            )
        except Exception as e:
            logger.warning("[terrain_service] Failed for %s: %s", snap["name"], e)
            fetch_results.append((snap, None))

    # Phase 3: write
    updated = 0
    failed  = 0
    db = SessionLocal()
    try:
        for snap, terrain in fetch_results:
            if terrain is None:
                failed += 1
                continue
            incident = db.query(Incident).filter(Incident.id == snap["id"]).first()
            if not incident:
                failed += 1
                continue
            incident.elevation_m     = terrain["elevation_m"]
            incident.slope_percent   = terrain["slope_percent"]
            incident.aspect_cardinal = terrain["aspect_cardinal"]
            incident.updated_at      = datetime.now(UTC)
            updated += 1
        db.commit()
        logger.info("[terrain_service] Done. Updated: %d, Failed: %d", updated, failed)
    except Exception as e:
        db.rollback()
        logger.error("[terrain_service] Error writing terrain: %s", e)
    finally:
        db.close()

    return {"updated": updated, "failed": failed}
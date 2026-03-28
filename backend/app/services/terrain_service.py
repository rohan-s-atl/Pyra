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
    Only fetches for incidents that don't yet have terrain data or whose data is stale.
    """
    db: Session = SessionLocal()
    updated = 0
    failed  = 0

    try:
        # Target incidents missing terrain data
        incidents = db.query(Incident).filter(
            Incident.status.in_(["active", "contained"]),
            Incident.elevation_m.is_(None),
        ).all()

        if not incidents:
            logger.info("[terrain_service] All incidents already have terrain data.")
            db.close()
            return {"updated": 0, "failed": 0}

        logger.info(f"[terrain_service] Fetching terrain for {len(incidents)} incidents...")

        for incident in incidents:
            try:
                terrain = await estimate_slope(incident.latitude, incident.longitude)

                incident.elevation_m     = terrain["elevation_m"]
                incident.slope_percent   = terrain["slope_percent"]
                incident.aspect_cardinal = terrain["aspect_cardinal"]
                incident.updated_at      = datetime.now(UTC)
                updated += 1

                logger.info(
                    f"[terrain_service] {incident.name}: "
                    f"{terrain['elevation_m']}m, "
                    f"slope={terrain['slope_percent']}%, "
                    f"aspect={terrain['aspect_cardinal']}"
                )

            except Exception as e:
                logger.warning(f"[terrain_service] Failed for {incident.name}: {e}")
                failed += 1

        db.commit()
        logger.info(f"[terrain_service] Done. Updated: {updated}, Failed: {failed}")

    except Exception as e:
        db.rollback()
        logger.error(f"[terrain_service] Error: {e}")
    finally:
        db.close()

    return {"updated": updated, "failed": failed}
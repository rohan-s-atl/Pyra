"""
firms_service.py — NASA FIRMS hotspot ingestion.

Run every 10 minutes via the scheduler.

Cluster hotspots -> upsert incidents.
  - Clusters within 0.15 degrees (~15 km) are merged.
  - Significant clusters (FRP >= 10 MW) become incidents.
  - Existing incidents near the cluster are updated, not duplicated.
  - All DB operations are atomic; failures rollback cleanly.
"""

import logging
from datetime import datetime, UTC

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.incident import Incident
from app.ext.nasa_firms import (
    fetch_california_hotspots,
    estimate_severity,
    estimate_spread_risk,
)

logger = logging.getLogger(__name__)


def _cluster_hotspots(hotspots: list, radius_deg: float = 0.15) -> list:
    """
    Simple greedy clustering — group hotspots within radius_deg of each other.
    Returns list of cluster dicts with centroid and aggregated FRP.
    """
    clusters = []

    for hotspot in hotspots:
        lat = hotspot["latitude"]
        lon = hotspot["longitude"]
        frp = hotspot.get("frp") or 0

        matched = False
        for cluster in clusters:
            if (abs(cluster["lat"] - lat) < radius_deg and
                    abs(cluster["lon"] - lon) < radius_deg):
                cluster["hotspots"].append(hotspot)
                cluster["total_frp"] += frp
                n = len(cluster["hotspots"])
                cluster["lat"] = (cluster["lat"] * (n - 1) + lat) / n
                cluster["lon"] = (cluster["lon"] * (n - 1) + lon) / n
                matched = True
                break

        if not matched:
            clusters.append({
                "lat":       lat,
                "lon":       lon,
                "hotspots":  [hotspot],
                "total_frp": frp,
            })

    return clusters


def _make_incident_id(lat: float, lon: float) -> str:
    """Generate a stable, DB-safe incident ID from coordinates."""
    lat_s = f"{lat:.3f}".replace(".", "p").replace("-", "S")
    lon_s = f"{lon:.3f}".replace(".", "p").replace("-", "W")
    return f"SAT{lat_s}N{lon_s}"[:32]


async def sync_firms_hotspots() -> dict:
    """
    Background job — fetch NASA FIRMS hotspots, cluster, upsert incidents.

    Returns dict with created/updated/skipped/hotspot counts.
    Never raises — all failures are logged and return safe defaults.
    """
    db: Session = SessionLocal()
    created  = 0
    updated  = 0
    skipped  = 0
    hotspots = []

    try:
        logger.info("[firms_service] Fetching NASA FIRMS hotspots...")
        hotspots = await fetch_california_hotspots(days=1)

        if not hotspots:
            logger.info("[firms_service] No hotspots returned (API may be unavailable).")
            return {"created": 0, "updated": 0, "skipped": 0, "hotspots": 0}

        logger.info("[firms_service] Got %d hotspots. Clustering...", len(hotspots))
        clusters = _cluster_hotspots(hotspots, radius_deg=0.15)
        logger.info("[firms_service] %d clusters formed.", len(clusters))

        significant = [c for c in clusters if c["total_frp"] >= 10]
        logger.info("[firms_service] %d significant clusters (FRP >= 10 MW).", len(significant))

        for cluster in significant:
            lat = round(cluster["lat"], 4)
            lon = round(cluster["lon"], 4)
            frp = cluster["total_frp"]
            confidence = cluster["hotspots"][0].get("confidence", "nominal")

            severity   = estimate_severity(frp)
            spread_risk = estimate_spread_risk(frp, confidence)

            # Check for existing incident within ~0.2 degrees (~22 km)
            existing = db.query(Incident).filter(
                Incident.latitude.between(lat - 0.2, lat + 0.2),
                Incident.longitude.between(lon - 0.2, lon + 0.2),
                Incident.status.in_(["active", "contained"]),
            ).first()

            if existing:
                # Update risk data on existing incident
                existing.severity    = severity
                existing.spread_risk = spread_risk
                existing.updated_at  = datetime.now(UTC)
                updated += 1
            else:
                incident_id = _make_incident_id(lat, lon)

                # Avoid creating duplicate if ID already exists
                existing_by_id = db.query(Incident).filter(Incident.id == incident_id).first()
                if existing_by_id:
                    skipped += 1
                    continue

                new_incident = Incident(
                    id           = incident_id,
                    name         = f"Satellite Detection {lat:.2f}N {abs(lon):.2f}W",
                    fire_type    = "wildland",
                    severity     = severity,
                    status       = "active",
                    latitude     = lat,
                    longitude    = lon,
                    acres_burned = None,
                    spread_risk  = spread_risk,
                    spread_direction     = None,
                    wind_speed_mph       = None,
                    humidity_percent     = None,
                    containment_percent  = 0.0,
                    structures_threatened= 0,
                    started_at   = datetime.now(UTC),
                    updated_at   = datetime.now(UTC),
                    notes        = (
                        f"Auto-detected via NASA FIRMS VIIRS. "
                        f"FRP: {frp:.1f} MW. Confidence: {confidence}. "
                        f"Hotspots in cluster: {len(cluster['hotspots'])}."
                    ),
                )
                db.add(new_incident)
                created += 1

        db.commit()
        logger.info(
            "[firms_service] Done. Created: %d, Updated: %d, Skipped: %d",
            created, updated, skipped,
        )

    except Exception as exc:
        db.rollback()
        logger.error("[firms_service] Error during sync: %s", exc, exc_info=True)
    finally:
        db.close()

    return {
        "created":  created,
        "updated":  updated,
        "skipped":  skipped,
        "hotspots": len(hotspots),
    }
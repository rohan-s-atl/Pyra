"""
Road data ingestion service — fetches OSM road network data near incidents
and seeds Route records with real road names, accessibility ratings, and risk levels.

Only runs once per incident (or when triggered manually) since road data
changes rarely. The simulation service then evolves route conditions dynamically.
"""

import logging
from datetime import datetime, UTC
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.incident import Incident
from app.models.route import Route
from app.ext.overpass import fetch_roads_near_incident, road_safety_rating

logger = logging.getLogger(__name__)

# Only seed routes for incidents that don't have any yet
MAX_ROUTES_PER_INCIDENT = 5
SEARCH_RADIUS_KM = 6.0


async def seed_incident_routes():
    """
    Background job — for each active incident with no routes yet,
    fetch nearby OSM roads and create Route records.

    Phase 1: read incident list from DB, close session.
    Phase 2: async Overpass fetches per incident with no connection held.
    Phase 3: fresh session to write all new Route records.
    """
    # Phase 1: read — find incidents that need seeding
    db: Session = SessionLocal()
    try:
        incidents_needing_routes = []
        for incident in db.query(Incident).filter(
            Incident.status.in_(["active", "contained"])
        ).all():
            existing_count = db.query(Route).filter(
                Route.incident_id == incident.id
            ).count()
            if existing_count == 0:
                incidents_needing_routes.append({
                    "id":   incident.id,
                    "name": incident.name,
                    "lat":  incident.latitude,
                    "lon":  incident.longitude,
                })
    finally:
        db.close()

    seeded  = 0
    skipped = len([]) # will be set below

    if not incidents_needing_routes:
        logger.info("[road_service] All incidents already have routes — nothing to seed.")
        return {"seeded": 0, "skipped": 0}

    # Phase 2: async Overpass fetches — no DB connection held open
    fetch_results = []
    for snap in incidents_needing_routes:
        logger.info("[road_service] Fetching roads for %s...", snap["name"])
        try:
            roads = await fetch_roads_near_incident(
                snap["lat"], snap["lon"], radius_km=SEARCH_RADIUS_KM,
            )
            fetch_results.append((snap, roads))
        except Exception as e:
            logger.warning("[road_service] Overpass failed for %s: %s", snap["name"], e)
            fetch_results.append((snap, None))

    # Phase 3: write — single session for all inserts
    db = SessionLocal()
    try:
        for snap, roads in fetch_results:
            if not roads:
                logger.info("[road_service] No roads found for %s", snap["name"])
                continue

            access_order = {"good": 0, "limited": 1, "poor": 2}
            risk_order   = {"low": 0, "moderate": 1, "high": 2}
            top_roads = sorted(
                roads,
                key=lambda r: (
                    access_order.get(r["terrain_accessibility"], 1),
                    risk_order.get(r["fire_exposure_risk"], 1),
                )
            )[:MAX_ROUTES_PER_INCIDENT]

            for i, road in enumerate(top_roads):
                rank  = "primary" if i == 0 else "alternate"
                safety = road_safety_rating(road)

                road_type_label = {
                    "primary":      "Primary Road",
                    "secondary":    "Secondary Road",
                    "tertiary":     "Local Road",
                    "unclassified": "Local Road",
                    "track":        "Forest Track",
                    "service":      "Service Road",
                    "residential":  "Residential Road",
                }.get(road["highway_type"], "Road")

                label    = f"{road['name']} ({road_type_label})"
                route_id = f"RT-OSM-{snap['id'][:8]}-{road['osm_id'] % 100000}"[:32]

                notes_parts = []
                if road.get("surface"):    notes_parts.append(f"Surface: {road['surface']}")
                if road.get("lanes"):      notes_parts.append(f"{road['lanes']}-lane road")
                if road.get("maxspeed"):   notes_parts.append(f"Speed limit: {road['maxspeed']}")
                if road.get("access") and road["access"] not in ("yes", "public"):
                    notes_parts.append(f"Access: {road['access']}")
                notes = ". ".join(notes_parts) if notes_parts else "OSM road data — verify before use."

                db.add(Route(
                    id=route_id,
                    incident_id=snap["id"],
                    label=label,
                    rank=rank,
                    origin_label="Nearest access point",
                    destination_label=f"{snap['name']} — Command Area",
                    origin_lat=road["lat_start"],
                    origin_lon=road["lon_start"],
                    destination_lat=snap["lat"],
                    destination_lon=snap["lon"],
                    estimated_travel_minutes=None,
                    distance_miles=None,
                    terrain_accessibility=road["terrain_accessibility"],
                    fire_exposure_risk=road["fire_exposure_risk"],
                    safety_rating=safety,
                    is_currently_passable=True,
                    notes=notes,
                    last_verified_at=datetime.now(UTC),
                ))

            seeded += 1
            logger.info("[road_service] Seeded %d routes for %s", len(top_roads), snap["name"])

        db.commit()
        logger.info("[road_service] Done. Incidents seeded: %d", seeded)

    except Exception as e:
        db.rollback()
        logger.error("[road_service] Error writing routes: %s", e)
    finally:
        db.close()

    return {"seeded": seeded, "skipped": len(incidents_needing_routes) - seeded}
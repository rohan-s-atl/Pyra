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
    """
    db: Session = SessionLocal()
    seeded = 0
    skipped = 0

    try:
        incidents = db.query(Incident).filter(
            Incident.status.in_(["active", "contained"])
        ).all()

        for incident in incidents:
            existing_count = db.query(Route).filter(
                Route.incident_id == incident.id
            ).count()

            if existing_count > 0:
                skipped += 1
                continue

            logger.info(f"[road_service] Seeding routes for {incident.name}...")

            try:
                roads = await fetch_roads_near_incident(
                    incident.latitude, incident.longitude,
                    radius_km=SEARCH_RADIUS_KM,
                )
            except Exception as e:
                logger.warning(f"[road_service] Overpass failed for {incident.name}: {e}")
                continue

            if not roads:
                logger.info(f"[road_service] No roads found near {incident.name}")
                continue

            # Sort: good accessibility first, then by fire exposure risk ascending
            access_order = {"good": 0, "limited": 1, "poor": 2}
            risk_order   = {"low": 0, "moderate": 1, "high": 2}
            roads_sorted = sorted(
                roads,
                key=lambda r: (
                    access_order.get(r["terrain_accessibility"], 1),
                    risk_order.get(r["fire_exposure_risk"], 1),
                )
            )

            # Take top N roads
            top_roads = roads_sorted[:MAX_ROUTES_PER_INCIDENT]

            for i, road in enumerate(top_roads):
                rank = "primary" if i == 0 else "alternate"
                safety = road_safety_rating(road)

                # Build human-readable label
                road_type_label = {
                    "primary":      "Primary Road",
                    "secondary":    "Secondary Road",
                    "tertiary":     "Local Road",
                    "unclassified": "Local Road",
                    "track":        "Forest Track",
                    "service":      "Service Road",
                    "residential":  "Residential Road",
                }.get(road["highway_type"], "Road")

                label = f"{road['name']} ({road_type_label})"

                # Generate a unique route ID
                route_id = f"RT-OSM-{incident.id[:8]}-{road['osm_id'] % 100000}"[:32]

                # Build notes from OSM attributes
                notes_parts = []
                if road.get("surface"):
                    notes_parts.append(f"Surface: {road['surface']}")
                if road.get("lanes"):
                    notes_parts.append(f"{road['lanes']}-lane road")
                if road.get("maxspeed"):
                    notes_parts.append(f"Speed limit: {road['maxspeed']}")
                if road.get("access") and road["access"] not in ("yes", "public"):
                    notes_parts.append(f"Access: {road['access']}")
                notes = ". ".join(notes_parts) if notes_parts else "OSM road data — verify before use."

                db.add(Route(
                    id=route_id,
                    incident_id=incident.id,
                    label=label,
                    rank=rank,
                    origin_label=f"Nearest access point",
                    destination_label=f"{incident.name} — Command Area",
                    origin_lat=road["lat_start"],
                    origin_lon=road["lon_start"],
                    destination_lat=incident.latitude,
                    destination_lon=incident.longitude,
                    estimated_travel_minutes=None,   # OSRM will fill this in
                    distance_miles=None,
                    terrain_accessibility=road["terrain_accessibility"],
                    fire_exposure_risk=road["fire_exposure_risk"],
                    safety_rating=safety,
                    is_currently_passable=True,
                    notes=notes,
                    last_verified_at=datetime.now(UTC),
                ))

            seeded += 1
            logger.info(
                f"[road_service] Seeded {len(top_roads)} routes for {incident.name}"
            )

        db.commit()
        logger.info(f"[road_service] Done. Incidents seeded: {seeded}, Skipped: {skipped}")

    except Exception as e:
        db.rollback()
        logger.error(f"[road_service] Error: {e}")
    finally:
        db.close()

    return {"seeded": seeded, "skipped": skipped}
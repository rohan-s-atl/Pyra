from datetime import datetime, UTC, timedelta

from app.models.incident import Incident
from app.models.unit import Unit
from app.services import simulation_service as sim


def make_incident(**overrides):
    base = {
        "id": "inc-sim",
        "name": "Sim Fire",
        "fire_type": "wildland",
        "severity": "high",
        "status": "active",
        "spread_risk": "high",
        "latitude": 37.75,
        "longitude": -122.42,
        "acres_burned": 120.0,
        "containment_percent": 40.0,
        "structures_threatened": 12,
        "wind_speed_mph": 20.0,
        "humidity_percent": 15.0,
        "started_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    return Incident(**{**base, **overrides})


def make_unit(unit_id: str, status: str, incident_id: str):
    return Unit(
        id=unit_id,
        designation=unit_id.upper(),
        unit_type="engine",
        status=status,
        station_id="station-1",
        assigned_incident_id=incident_id,
        latitude=37.80,
        longitude=-122.45,
        last_updated=datetime.now(UTC),
    )


def test_containment_improves_with_crews_on_scene(db, monkeypatch):
    incident = make_incident(containment_percent=40.0)
    db.add(incident)
    db.add_all([
        make_unit("unit-1", "on_scene", incident.id),
        make_unit("unit-2", "on_scene", incident.id),
        make_unit("unit-3", "en_route", incident.id),
    ])
    db.commit()

    monkeypatch.setattr(sim.random, "uniform", lambda a, b: 1.0)
    sim._progress_containment(db)
    db.flush()
    db.refresh(incident)

    assert incident.containment_percent > 40.0


def test_containment_slips_without_scene_coverage(db, monkeypatch):
    # started_at must be outside the 12-minute grace period so loss is not suppressed
    incident = make_incident(containment_percent=35.0, wind_speed_mph=28.0, humidity_percent=9.0,
                             started_at=datetime.now(UTC) - timedelta(minutes=20))
    db.add(incident)
    db.commit()

    monkeypatch.setattr(sim.random, "uniform", lambda a, b: 1.0)
    sim._progress_containment(db)
    db.flush()
    db.refresh(incident)

    assert incident.containment_percent < 35.0


def test_contained_incident_can_reactivate_if_staffing_collapses(db, monkeypatch):
    # started_at must be outside the 12-minute grace period so loss is not suppressed
    incident = make_incident(status="contained", containment_percent=90.05, wind_speed_mph=30.0, humidity_percent=8.0,
                             started_at=datetime.now(UTC) - timedelta(minutes=20))
    db.add(incident)
    db.commit()

    monkeypatch.setattr(sim.random, "uniform", lambda a, b: 1.2)
    sim._progress_containment(db)
    db.flush()
    db.refresh(incident)

    assert incident.status == "active"
    assert incident.containment_percent < 90.05

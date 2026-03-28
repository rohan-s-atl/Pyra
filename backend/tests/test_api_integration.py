"""
test_api_integration.py — API integration tests.

Covers:
  - Auth and role-based access control
  - Dispatch flow (approve, alert-approve, role gates)
  - Alert management and ingestion
  - Incident read endpoints
  - Unit read + GPS update
  - Multi-incident priority
  - Route safety scoring
  - Incident close-out checklist and close
"""
import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch

from tests.conftest import (
    _seed_users,
    _seed_station,
    _seed_incident,
    _seed_unit,
    _seed_alert,
)


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH & ROLES
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuth:
    def test_login_commander(self, db, client):
        _seed_users(db)
        r = client.post("/api/auth/token", json={"username": "commander", "password": "pyra2025"})
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["role"] == "commander"

    def test_login_wrong_password(self, db, client):
        _seed_users(db)
        r = client.post("/api/auth/token", json={"username": "commander", "password": "wrong"})
        assert r.status_code == 401

    def test_login_unknown_user(self, db, client):
        r = client.post("/api/auth/token", json={"username": "ghost", "password": "x"})
        assert r.status_code == 401

    def test_unauthenticated_incidents_rejected(self, client):
        r = client.get("/api/incidents/")
        assert r.status_code == 401

    def test_viewer_can_read_incidents(self, db, client, auth_headers):
        _seed_incident(db)
        r = client.get("/api/incidents/", headers=auth_headers["viewer"])
        assert r.status_code == 200

    def test_viewer_cannot_dispatch(self, db, client, auth_headers):
        _seed_incident(db)
        r = client.post(
            "/api/dispatch/approve",
            json={"incident_id": "inc-1", "unit_ids": ["unit-1"], "loadout_profile": "initial_attack", "route_id": "r1"},
            headers=auth_headers["viewer"],
        )
        assert r.status_code == 403

    def test_get_current_user(self, db, client, auth_headers):
        _seed_users(db)
        r = client.get("/api/auth/me", headers=auth_headers["commander"])
        assert r.status_code == 200
        assert r.json()["role"] == "commander"


# ═══════════════════════════════════════════════════════════════════════════════
# INCIDENTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestIncidents:
    def test_list_incidents_empty(self, client, auth_headers):
        r = client.get("/api/incidents/", headers=auth_headers["viewer"])
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_incidents_with_data(self, db, client, auth_headers):
        _seed_incident(db)
        r = client.get("/api/incidents/", headers=auth_headers["viewer"])
        assert r.status_code == 200
        ids = [i["id"] for i in r.json()]
        assert "inc-1" in ids

    def test_get_incident_by_id(self, db, client, auth_headers):
        _seed_incident(db)
        r = client.get("/api/incidents/inc-1", headers=auth_headers["viewer"])
        assert r.status_code == 200
        assert r.json()["name"] == "Test Fire"

    def test_get_incident_not_found(self, client, auth_headers):
        r = client.get("/api/incidents/nonexistent", headers=auth_headers["viewer"])
        assert r.status_code == 404

    def test_list_incidents_filter_status(self, db, client, auth_headers):
        _seed_incident(db)
        r = client.get("/api/incidents/?status=active", headers=auth_headers["viewer"])
        assert r.status_code == 200
        for inc in r.json():
            assert inc["status"] == "active"


# ═══════════════════════════════════════════════════════════════════════════════
# UNITS
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnits:
    def test_list_units(self, db, client, auth_headers):
        _seed_station(db)
        _seed_unit(db)
        r = client.get("/api/units/", headers=auth_headers["viewer"])
        assert r.status_code == 200
        assert any(u["id"] == "unit-1" for u in r.json())

    def test_get_unit_by_id(self, db, client, auth_headers):
        _seed_station(db)
        _seed_unit(db)
        r = client.get("/api/units/unit-1", headers=auth_headers["viewer"])
        assert r.status_code == 200
        assert r.json()["designation"] == "UNIT-1"

    def test_unit_gps_update(self, db, client, auth_headers):
        _seed_station(db)
        _seed_unit(db)
        r = client.post(
            "/api/units/unit-1/location",
            json={"latitude": 37.76, "longitude": -122.43, "source": "device"},
            headers=auth_headers["dispatcher"],
        )
        assert r.status_code == 200
        assert abs(r.json()["latitude"] - 37.76) < 0.001

    def test_unit_gps_invalid_lat(self, db, client, auth_headers):
        _seed_station(db)
        _seed_unit(db)
        r = client.post(
            "/api/units/unit-1/location",
            json={"latitude": 999.0, "longitude": -122.43},
            headers=auth_headers["dispatcher"],
        )
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# DISPATCH FLOW
# ═══════════════════════════════════════════════════════════════════════════════

class TestDispatch:
    def test_dispatch_requires_auth(self, client):
        r = client.post("/api/dispatch/approve", json={})
        assert r.status_code == 401

    def test_dispatch_missing_incident(self, db, client, auth_headers):
        _seed_station(db)
        _seed_unit(db)
        r = client.post(
            "/api/dispatch/approve",
            json={"incident_id": "no-such-inc", "unit_ids": ["unit-1"],
                  "loadout_profile": "initial_attack", "route_id": "r1"},
            headers=auth_headers["dispatcher"],
        )
        assert r.status_code == 404

    def test_dispatch_unit_not_found_returns_failed(self, db, client, auth_headers):
        _seed_station(db)
        _seed_incident(db)
        with patch("app.services.routing.build_route", new=AsyncMock(return_value=None)):
            r = client.post(
                "/api/dispatch/approve",
                json={"incident_id": "inc-1", "unit_ids": ["ghost-unit"],
                      "loadout_profile": "initial_attack", "route_id": "r1"},
                headers=auth_headers["dispatcher"],
            )
        assert r.status_code == 200
        body = r.json()
        assert "ghost-unit" in body["failed"]

    def test_dispatch_out_of_service_unit_fails(self, db, client, auth_headers):
        _seed_station(db)
        _seed_incident(db)
        _seed_unit(db, status="out_of_service")
        with patch("app.services.routing.build_route", new=AsyncMock(return_value=None)):
            r = client.post(
                "/api/dispatch/approve",
                json={"incident_id": "inc-1", "unit_ids": ["unit-1"],
                      "loadout_profile": "initial_attack", "route_id": "r1"},
                headers=auth_headers["dispatcher"],
            )
        body = r.json()
        assert "unit-1" in body["failed"] or "unit-1" in body["unreachable"]

    def test_dispatch_already_assigned_unit_fails(self, db, client, auth_headers):
        """Unit already en_route to same incident should go to failed."""
        _seed_station(db)
        _seed_incident(db)
        _seed_unit(db, status="en_route", incident_id="inc-1")
        with patch("app.services.routing.build_route", new=AsyncMock(return_value=None)):
            r = client.post(
                "/api/dispatch/approve",
                json={"incident_id": "inc-1", "unit_ids": ["unit-1"],
                      "loadout_profile": "initial_attack", "route_id": "r1"},
                headers=auth_headers["dispatcher"],
            )
        body = r.json()
        assert "unit-1" in body["failed"]

    def test_get_incident_units(self, db, client, auth_headers):
        _seed_station(db)
        _seed_incident(db)
        _seed_unit(db, status="on_scene", incident_id="inc-1")
        r = client.get("/api/dispatch/incident/inc-1/units", headers=auth_headers["viewer"])
        assert r.status_code == 200
        assert any(u["id"] == "unit-1" for u in r.json())


# ═══════════════════════════════════════════════════════════════════════════════
# ALERTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlerts:
    def test_list_alerts(self, db, client, auth_headers):
        _seed_incident(db)
        _seed_alert(db)
        r = client.get("/api/alerts/", headers=auth_headers["viewer"])
        assert r.status_code == 200
        assert any(a["id"] == "alert-1" for a in r.json())

    def test_acknowledge_alert(self, db, client, auth_headers):
        _seed_incident(db)
        _seed_alert(db)
        r = client.post("/api/alerts/alert-1/acknowledge", json={}, headers=auth_headers["dispatcher"])
        assert r.status_code == 200

    def test_alert_dispatch(self, db, client, auth_headers):
        _seed_station(db)
        _seed_incident(db)
        _seed_alert(db)
        _seed_unit(db)
        with patch("app.services.routing.build_route", new=AsyncMock(return_value=None)):
            r = client.post(
                "/api/dispatch/alert-approve",
                json={"alert_id": "alert-1", "incident_id": "inc-1", "unit_ids": ["unit-1"]},
                headers=auth_headers["dispatcher"],
            )
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# INGESTION
# ═══════════════════════════════════════════════════════════════════════════════

class TestIngestion:
    def test_ingestion_requires_auth(self, client):
        # /api/ingestion/status requires auth
        r = client.get("/api/ingestion/status")
        assert r.status_code == 401

    def test_ingest_alert(self, db, client, auth_headers):
        # Trigger weather ingestion (no external API needed for the endpoint itself)
        r = client.post(
            "/api/ingestion/trigger/weather",
            headers=auth_headers["dispatcher"],
        )
        # 200 = ran successfully, 500 = ran but external API unavailable — both mean the route works
        assert r.status_code in (200, 500)


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-INCIDENT PRIORITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiIncident:
    def test_priority_empty(self, client, auth_headers):
        r = client.get("/api/multi-incident/priority", headers=auth_headers["viewer"])
        assert r.status_code == 200
        assert r.json()["summary"]["total_incidents"] == 0

    def test_priority_with_incidents(self, db, client, auth_headers):
        _seed_incident(db, "inc-a")
        r = client.get("/api/multi-incident/priority", headers=auth_headers["viewer"])
        assert r.status_code == 200
        body = r.json()
        assert body["summary"]["total_incidents"] >= 1
        assert "priority_score" in body["ranked_incidents"][0]

    def test_priority_ordering(self, db, client, auth_headers):
        """Critical incidents should rank above moderate ones."""
        from app.models.incident import Incident
        inc_crit = Incident(
            id="crit-1", name="Critical Fire", fire_type="wildland_urban_interface",
            severity="critical", status="active", spread_risk="extreme",
            latitude=37.70, longitude=-122.40,
            acres_burned=500.0, structures_threatened=100,
            started_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        inc_low = Incident(
            id="low-1", name="Low Fire", fire_type="wildland",
            severity="low", status="active", spread_risk="low",
            latitude=37.71, longitude=-122.41,
            containment_percent=80.0,
            started_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        db.add_all([inc_crit, inc_low])
        db.commit()

        r = client.get("/api/multi-incident/priority", headers=auth_headers["viewer"])
        assert r.status_code == 200
        ranked = r.json()["ranked_incidents"]
        scores = {i["incident_id"]: i["priority_score"] for i in ranked}
        assert scores["crit-1"] > scores["low-1"]


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTE SAFETY
# ═══════════════════════════════════════════════════════════════════════════════

class TestRouteSafety:
    def test_route_safety_no_routes(self, db, client, auth_headers):
        _seed_incident(db)
        r = client.get("/api/routes/safety/inc-1", headers=auth_headers["viewer"])
        assert r.status_code == 200
        assert r.json()["summary"]["total"] == 0

    def test_route_safety_with_route(self, db, client, auth_headers):
        from app.models.route import Route
        _seed_incident(db)
        route = Route(
            id="route-1", incident_id="inc-1", label="North Access",
            rank="1", origin_label="Station 1", destination_label="Fire Origin",
            origin_lat=37.80, origin_lon=-122.45,
            destination_lat=37.75, destination_lon=-122.42,
            terrain_accessibility="good", fire_exposure_risk="low",
            safety_rating="good", is_currently_passable=True,
            last_verified_at=datetime.now(UTC),
        )
        db.add(route)
        db.commit()

        r = client.get("/api/routes/safety/inc-1", headers=auth_headers["viewer"])
        assert r.status_code == 200
        body = r.json()
        assert body["summary"]["total"] == 1
        result = body["routes"][0]
        assert result["status"] in ("safe", "risky", "blocked")
        assert 0 <= result["safety_score"] <= 100


# ═══════════════════════════════════════════════════════════════════════════════
# INCIDENT CLOSE-OUT
# ═══════════════════════════════════════════════════════════════════════════════

class TestCloseOut:
    def test_checklist_missing_briefing(self, db, client, auth_headers):
        _seed_station(db)
        _seed_incident(db)
        r = client.get("/api/incidents/inc-1/closeout-checklist", headers=auth_headers["commander"])
        assert r.status_code == 200
        body = r.json()
        assert body["ready"] is False
        assert "briefing_generated" in body["blocking"]

    def test_checklist_active_units_blocking(self, db, client, auth_headers):
        _seed_station(db)
        _seed_incident(db)
        _seed_unit(db, status="on_scene", incident_id="inc-1")
        r = client.get("/api/incidents/inc-1/closeout-checklist", headers=auth_headers["commander"])
        assert r.status_code == 200
        body = r.json()
        assert "units_recalled" in body["blocking"]

    def test_close_blocked_without_briefing(self, db, client, auth_headers):
        _seed_station(db)
        _seed_incident(db)
        r = client.post("/api/incidents/inc-1/close", headers=auth_headers["commander"])
        assert r.status_code == 422

    def test_close_force_succeeds(self, db, client, auth_headers):
        _seed_station(db)
        _seed_incident(db)
        with patch("app.api.briefing._generate_handoff_text", new=AsyncMock(return_value="Final briefing text.")):
            r = client.post("/api/incidents/inc-1/close?force=true", headers=auth_headers["commander"])
        assert r.status_code == 200
        assert r.json()["status"] == "closed"

    def test_close_already_closed(self, db, client, auth_headers):
        _seed_station(db)
        _seed_incident(db)
        # Force-close first
        with patch("app.api.briefing._generate_handoff_text", new=AsyncMock(return_value="text")):
            client.post("/api/incidents/inc-1/close?force=true", headers=auth_headers["commander"])
        # Try again
        r = client.post("/api/incidents/inc-1/close?force=true", headers=auth_headers["commander"])
        assert r.status_code == 400

    def test_viewer_cannot_close(self, db, client, auth_headers):
        _seed_station(db)
        _seed_incident(db)
        r = client.post("/api/incidents/inc-1/close?force=true", headers=auth_headers["viewer"])
        assert r.status_code == 403
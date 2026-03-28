"""
conftest.py — Integration test fixtures.

Uses an in-memory SQLite database so tests run without Postgres.
All models are created fresh per test session; each test gets a clean DB.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from datetime import datetime, UTC
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")
os.environ.setdefault("ENV", "development")

from app.core.database import Base, get_db
from app.main import app
from app.models.incident import Incident
from app.models.unit import Unit
from app.models.alert import Alert
from app.models.station import Station
from app.models.user import User
from app.core.security import hash_password

# ── Single shared in-memory engine for the whole test session ─────────────────
# Use a named file-based SQLite so all connections share the same data.
# ":memory:" creates a separate DB per connection which breaks fixtures.

TEST_ENGINE = create_engine(
    "sqlite:///./test_runner.db",
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)
    # Clean up the file
    import os as _os
    try:
        _os.remove("./test_runner.db")
    except FileNotFoundError:
        pass


@pytest.fixture()
def db():
    session = TestingSessionLocal()
    yield session
    session.rollback()
    # Clean all tables between tests
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    session.close()


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


# ── Seed helpers ───────────────────────────────────────────────────────────────

def _seed_users(db):
    for username, role in [("commander", "commander"), ("dispatcher", "dispatcher"), ("viewer", "viewer")]:
        if not db.query(User).filter(User.username == username).first():
            db.add(User(id=username, username=username, hashed_password=hash_password("pyra2025"), role=role))
    db.commit()


def _seed_station(db):
    s = Station(id="station-1", name="Station 1", latitude=37.80, longitude=-122.45, station_type="engine")
    db.merge(s)
    db.commit()
    return s


def _seed_incident(db, incident_id="inc-1"):
    inc = Incident(
        id=incident_id, name="Test Fire", fire_type="wildland",
        severity="high", status="active", spread_risk="high",
        spread_direction="NE", latitude=37.75, longitude=-122.42,
        acres_burned=120.0, containment_percent=30.0,
        structures_threatened=10, wind_speed_mph=20.0, humidity_percent=15.0,
        started_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    db.merge(inc)
    db.commit()
    return inc


def _seed_unit(db, unit_id="unit-1", status="available", incident_id=None):
    u = Unit(
        id=unit_id, designation=unit_id.upper(), unit_type="engine",
        status=status, station_id="station-1",
        assigned_incident_id=incident_id,
        latitude=37.80, longitude=-122.45,
        personnel_count=4, water_capacity_gallons=500,
        last_updated=datetime.now(UTC),
    )
    db.merge(u)
    db.commit()
    return u


def _seed_alert(db, alert_id="alert-1", incident_id="inc-1"):
    a = Alert(
        id=alert_id, incident_id=incident_id, alert_type="spread_warning",
        severity="high", title="Spread warning detected",
        description="Fire spread risk elevated", is_acknowledged=False,
        created_at=datetime.now(UTC),
    )
    db.merge(a)
    db.commit()
    return a


@pytest.fixture()
def auth_headers(db, client):
    _seed_users(db)
    from app.core.security import create_access_token

    def _token(username):
        return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}

    return {
        "commander":  _token("commander"),
        "dispatcher": _token("dispatcher"),
        "viewer":     _token("viewer"),
    }
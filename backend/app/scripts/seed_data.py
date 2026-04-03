"""
seed_data.py — Real CAL FIRE facility seed data.

Stations sourced from the official CAL FIRE Facilities for Wildland Fire
Protection GeoJSON dataset (1,568 active facilities).

Ground stations (FSB/FSA/FSL) get a realistic engine/crew/dozer/tender roster.
Air Attack Bases (AAB) get S-2T / VLAT air tankers.
Helibases (HB) get S-70i Firehawk / BK117 helicopters.

CAL FIRE designation conventions:
  Engines:       CDF-{UNIT}-{number}   e.g. CDF-LNU-1050
  Hand Crews:    {UNIT} Crew {n}
  Dozers:        CDF-{UNIT}-D-{n}
  Water Tenders: CDF-{UNIT}-WT-{n}
  Air Tankers:   Tanker {n}
  Helicopters:   Copter {n}
  Command:       {UNIT} Command {n}
  Rescue:        CDF-{UNIT}-RS-{n}
"""

from __future__ import annotations
import math
import uuid
from datetime import datetime, UTC
from app.core.database import SessionLocal
from app.models.incident import Incident
from app.models.station import Station
from app.models.unit import Unit
from app.models.alert import Alert
from app.models.route import Route
from app.models.resource import Resource


# ── Real CAL FIRE station data (from official facilities GeoJSON) ─────────────

STATION_DATA = [
    # id,              name,                              cad_name,             unit_code, station_type, lat,        lon,         city
    ("STA-LNU-040",  "Clearlake Oaks FS 40",            "LNU Clearlake Oaks", "LNU",     "FSB",        39.02371,  -122.71175,  "Clearlake Oaks"),
    ("STA-SHU-043",  "Redding Fire Station 43",         "SHS Redding FS",     "SHU",     "FSB",        40.51978,  -122.29989,  "Redding"),
    ("STA-SCU-016",  "Sunshine Fire Station 16",        "SCU Sunshine FS",    "SCU",     "FSB",        37.89947,  -121.86063,  "Clayton"),
    ("STA-NEU-010",  "Auburn Fire Station 10",          "CDF 10",             "NEU",     "FSB",        38.93499,  -121.05300,  "Auburn"),
    ("STA-AEU-010",  "Dew Drop Fire Station 10",        "AEU Dew Drop FS",    "AEU",     "FSB",        38.51550,  -120.48054,  "Pioneer"),
    ("STA-BDU-CHN",  "Chino Hills Fire Station",        "BDU Chino Hills FS", "BDU",     "FSB",        33.99025,  -117.68819,  "Chino"),
    ("STA-RRU-014",  "Corona Fire Station 14",          "RRU CORONA FS",      "RRU",     "FSB",        33.90355,  -117.56164,  "Norco"),
    ("STA-KRN-026",  "Kern Station 26",                 "KRN Station 26",     "KRN",     "FSB",        35.61797,  -119.68952,  "Lost Hills"),
    ("STA-VNC-CAM",  "Camarillo Fire Station",          "VNC Camarillo",      "VNC",     "FSB",        34.16506,  -119.04519,  "Camarillo"),
    ("STA-LAC-084",  "Fire Station 84",                 "084",                "LAC",     "FSB",        34.64714,  -118.21958,  "Quartz Hill"),
    ("STA-ORC-YL",   "Yorba Linda Station 10",          "ORC YORBA LINDA 10", "ORC",     "FSB",        33.89125,  -117.81268,  "Yorba Linda"),

    # Air Attack Bases (real coords from dataset)
    ("STA-AAB-LNU",  "Sonoma Air Attack Base",          "LNU Sonoma AAB",     "LNU",     "AAB",        38.51369,  -122.80588,  "Santa Rosa"),
    ("STA-AAB-NEU",  "Grass Valley Air Attack Base",    "CDF Grass Valley AAB","NEU",    "AAB",        39.22331,  -120.99930,  "Grass Valley"),
    ("STA-AAB-SHU",  "Redding Air Attack Base",         "SHU Redding AAB",    "SHU",     "AAB",        40.51983,  -122.29805,  "Redding"),
    ("STA-AAB-FKU",  "Fresno Air Attack Base",          "FKU Fresno AAB",     "FKU",     "AAB",        36.77100,  -119.70172,  "Fresno"),
    ("STA-AAB-RRU",  "Hemet Ryan Air Attack Base",      "RRU Hemet Ryan AAB", "RRU",     "AAB",        33.73025,  -117.02195,  "Hemet"),
    ("STA-AAB-SDU",  "Ramona Air Attack Base",          "MVU Ramona AAB",     "SDU",     "AAB",        33.04021,  -116.91178,  "Ramona"),
    ("STA-AAB-ORC",  "Fullerton Air Attack Base",       "ORC FULLERTON",      "ORC",     "AAB",        33.87048,  -117.97685,  "Fullerton"),
    ("STA-AAB-AEU",  "McClellan Reload Base",           "McClellan",          "AEU",     "AAB",        38.66858,  -121.39803,  "McClellan"),

    # Helibases (real coords from dataset)
    ("STA-HB-LNU",   "Boggs Mountain Helibase",         "LNU Boggs Mtn HB",   "LNU",     "HB",         38.83359,  -122.71842,  "Cobb"),
    ("STA-HB-SCU",   "Alma Helitack Base FS 33",        "SCU Alma HB",        "SCU",     "HB",         37.18358,  -121.99058,  "Los Gatos"),
    ("STA-HB-BDU",   "Prado Helibase",                  "H305",               "BDU",     "HB",         33.98889,  -117.68723,  "Chino"),
    ("STA-HB-RRU",   "Hemet Ryan Helibase",             "RRU Hemet Ryan HB",  "RRU",     "HB",         33.73077,  -117.02299,  "Hemet"),
    ("STA-HB-FKU",   "Millerton Helitack Base",         "Millerton Helitack", "FKU",     "HB",         36.99244,  -119.70723,  "Friant"),
    ("STA-HB-KRN",   "Keene Helibase",                  "KCFD Helibase",      "KRN",     "HB",         35.22480,  -118.56647,  "Keene"),
    ("STA-HB-VNC",   "Ventura County Aviation Unit",    "VNC Aviation",       "VNC",     "HB",         34.21019,  -119.09483,  "Camarillo"),
]


def _u(designation, unit_type, station_id, lat, lon,
        personnel=None, water_gal=0, struct=False, air=False):
    return Unit(
        id=str(uuid.uuid4()),
        designation=designation,
        unit_type=unit_type,
        status="available",
        station_id=station_id,
        latitude=lat, longitude=lon,
        personnel_count=personnel,
        water_capacity_gallons=water_gal,
        has_structure_protection=struct,
        has_air_attack=air,
        last_updated=datetime.now(UTC),
        gps_source="simulated",
    )


def _ground_roster(unit_code, sta_id, lat, lon):
    """Standard CAL FIRE ground station roster: 3 engines, 1 crew, 1 dozer, 1 tender."""
    return [
        _u(f"CDF-{unit_code}-1{unit_code[-1]}0",  "engine",       sta_id, lat, lon, 4, 750,  True),
        _u(f"CDF-{unit_code}-1{unit_code[-1]}1",  "engine",       sta_id, lat, lon, 4, 750,  True),
        _u(f"CDF-{unit_code}-3{unit_code[-1]}0",  "engine",       sta_id, lat, lon, 3, 500,  True),
        _u(f"{unit_code} Crew 1",                  "hand_crew",    sta_id, lat, lon, 17, 0,   False),
        _u(f"CDF-{unit_code}-D-1",                 "dozer",        sta_id, lat, lon, 1,  0,   False),
        _u(f"CDF-{unit_code}-WT-1",                "water_tender", sta_id, lat, lon, 2,  3000,False),
    ]


# Tanker numbers by AAB station (real CAL FIRE tanker numbers)
_TANKER_NUMBERS = {
    "STA-AAB-LNU":  ("82",  "83"),
    "STA-AAB-NEU":  ("80",  "81"),
    "STA-AAB-SHU":  ("85",  "86"),
    "STA-AAB-FKU":  ("88",  "89"),
    "STA-AAB-RRU":  ("90",  "91"),
    "STA-AAB-SDU":  ("95",  "96"),
    "STA-AAB-ORC":  ("97",  "98"),
    "STA-AAB-AEU":  ("910", "911"),  # VLAT reload
}

# Copter numbers by HB station (real CAL FIRE copter numbers)
_COPTER_NUMBERS = {
    "STA-HB-LNU":  ("101", "102"),
    "STA-HB-SCU":  ("103", "104"),
    "STA-HB-BDU":  ("305", "306"),
    "STA-HB-RRU":  ("106", "107"),
    "STA-HB-FKU":  ("108", "109"),
    "STA-HB-KRN":  ("110", "111"),
    "STA-HB-VNC":  ("112", "113"),
}


def _dist_km(lat1, lon1, lat2, lon2):
    """Haversine distance in km."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def seed() -> None:
    db = SessionLocal()
    try:
        # Delete in FK-safe order: children before parents
        db.query(Alert).delete()
        db.query(Route).delete()
        db.query(Resource).delete()
        db.query(Unit).delete()
        db.query(Incident).delete()
        db.query(Station).delete()
        db.commit()

        now = datetime.now(UTC)

        # ── Stations ─────────────────────────────────────────────────────────
        stations = [
            Station(
                id=sid, name=name, cad_name=cad, unit_code=uc,
                station_type=stype, latitude=lat, longitude=lon, city=city,
            )
            for sid, name, cad, uc, stype, lat, lon, city in STATION_DATA
        ]
        db.add_all(stations)
        db.commit()

        # ── Incidents ─────────────────────────────────────────────────────────
        incidents = [
            Incident(
                id=str(uuid.uuid4()), name="LNU Lightning Complex",
                fire_type="wildland", severity="high", status="active",
                spread_risk="high", latitude=38.9200, longitude=-122.6500,
                acres_burned=5800, wind_speed_mph=24, humidity_percent=16,
                containment_percent=7, structures_threatened=180,
                spread_direction="NE",
                notes="Multiple ignitions from dry lightning. Merging heads on east flank.",
                started_at=now, updated_at=now,
            ),
            Incident(
                id=str(uuid.uuid4()), name="Shasta River Fire",
                fire_type="wildland", severity="moderate", status="active",
                spread_risk="moderate", latitude=40.5200, longitude=-122.4100,
                acres_burned=1400, wind_speed_mph=11, humidity_percent=28,
                containment_percent=40, structures_threatened=32,
                spread_direction="SW",
                notes="Good line on north and west flanks. Head running into rocky terrain.",
                started_at=now, updated_at=now,
            ),
            Incident(
                id=str(uuid.uuid4()), name="San Jose Structure Fire",
                fire_type="structure", severity="critical", status="active",
                spread_risk="high", latitude=37.3382, longitude=-121.8863,
                acres_burned=0, wind_speed_mph=5, humidity_percent=52,
                containment_percent=0, structures_threatened=6,
                spread_direction="N",
                notes="3-alarm. Commercial structure. Exposure risk to adjacent buildings.",
                started_at=now, updated_at=now,
            ),
        ]
        db.add_all(incidents)
        db.commit()

        # ── Units ─────────────────────────────────────────────────────────────
        units = []

        for sid, name, cad, uc, stype, lat, lon, city in STATION_DATA:
            if stype in ("FSB", "FSA", "FSL"):
                units.extend(_ground_roster(uc, sid, lat, lon))

                # Add a command unit for every other station
                if sid in ("STA-LNU-040","STA-SHU-043","STA-NEU-010","STA-BDU-CHN","STA-LAC-084"):
                    units.append(_u(f"{uc} Command 1", "command_unit", sid, lat, lon, 3, 0, True))

                # Rescue units at stations near urban incidents
                if sid in ("STA-SCU-016","STA-RRU-014","STA-ORC-YL"):
                    units.append(_u(f"CDF-{uc}-RS-1", "rescue", sid, lat, lon, 2, 0, False))

            elif stype == "AAB":
                nums = _TANKER_NUMBERS.get(sid)
                if nums:
                    t1, t2 = nums
                    # VLAT (910s) get higher retardant capacity
                    cap1 = 3000 if t1.startswith("9") else 1200
                    cap2 = 3000 if t2.startswith("9") else 1200
                    units.append(_u(f"Tanker {t1}", "air_tanker", sid, lat, lon, 2, cap1, False, True))
                    units.append(_u(f"Tanker {t2}", "air_tanker", sid, lat, lon, 2, cap2, False, True))

            elif stype == "HB":
                nums = _COPTER_NUMBERS.get(sid)
                if nums:
                    c1, c2 = nums
                    units.append(_u(f"Copter {c1}", "helicopter", sid, lat, lon, 3, 0, False, True))
                    units.append(_u(f"Copter {c2}", "helicopter", sid, lat, lon, 3, 0, False, True))

        db.add_all(units)
        db.commit()

        # ── Pre-dispatch units to active wildland incidents ────────────────────
        # Makes the map kinetic on first load — 2-3 ground units already en route.
        wildland_incidents = [i for i in incidents if i.fire_type == "wildland" and i.status == "active"]
        GROUND_TYPES = {"engine", "hand_crew", "water_tender"}
        dispatched = set()

        for inc in wildland_incidents:
            candidates = sorted(
                [u for u in units if u.unit_type in GROUND_TYPES and u.id not in dispatched],
                key=lambda u: _dist_km(inc.latitude, inc.longitude, u.latitude, u.longitude),
            )
            # LNU gets 3 units (larger, more complex fire); others get 2
            n = 3 if inc.name == "LNU Lightning Complex" else 2
            for unit in candidates[:n]:
                unit.status = "en_route"
                unit.assigned_incident_id = inc.id
                dispatched.add(unit.id)

        db.commit()

        # Count by type
        type_counts = {}
        for unit in units:
            type_counts[unit.unit_type] = type_counts.get(unit.unit_type, 0) + 1

        print(f"✅ Seed complete:")
        print(f"   {len(stations)} stations ({sum(1 for s in stations if s.station_type in ('FSB','FSA','FSL'))} ground, "
              f"{sum(1 for s in stations if s.station_type == 'AAB')} AAB, "
              f"{sum(1 for s in stations if s.station_type == 'HB')} HB)")
        print(f"   {len(incidents)} incidents")
        print(f"   {len(units)} units: {type_counts}")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
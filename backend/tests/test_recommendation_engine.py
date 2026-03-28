"""
Tests for backend/app/intelligence/recommendation_engine.py

Covers:
  - select_loadout_profile: all rule branches
  - assess_confidence: data completeness scoring
  - build_summary: output content
  - generate_recommendation: full output structure + route ranking
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

import pytest
from app.intelligence.recommendation_engine import (
    select_loadout_profile,
    assess_confidence,
    build_summary,
    generate_recommendation,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_incident(**overrides):
    base = {
        "id": "INC-001",
        "name": "Test Fire",
        "severity": "moderate",
        "fire_type": "wildland",
        "spread_risk": "moderate",
        "containment_percent": 20.0,
        "structures_threatened": 0,
        "wind_speed_mph": 15.0,
        "spread_direction": "NE",
        "acres_burned": 500.0,
        "humidity_percent": 18.0,
    }
    return {**base, **overrides}

def make_route(**overrides):
    base = {
        "id": "RTE-001",
        "label": "Highway 1",
        "safety_rating": "safe",
        "estimated_travel_minutes": 25,
        "terrain_accessibility": "paved",
        "fire_exposure_risk": "low",
        "is_currently_passable": True,
        "notes": None,
        "origin_lat": 34.0, "origin_lon": -118.0,
        "destination_lat": 34.1, "destination_lon": -118.1,
    }
    return {**base, **overrides}


# ── select_loadout_profile ────────────────────────────────────────────────────

class TestSelectLoadoutProfile:
    def test_critical_wui_is_structure_protection(self):
        inc = make_incident(severity="critical", fire_type="wildland_urban_interface")
        assert select_loadout_profile(inc) == "structure_protection"

    def test_critical_high_spread_is_extended_suppression(self):
        inc = make_incident(severity="critical", spread_risk="extreme", fire_type="wildland")
        assert select_loadout_profile(inc) == "extended_suppression"

    def test_high_severity_high_spread_is_extended_suppression(self):
        inc = make_incident(severity="high", spread_risk="high", fire_type="wildland")
        assert select_loadout_profile(inc) == "extended_suppression"

    def test_wildland_no_structures_is_aerial(self):
        inc = make_incident(fire_type="wildland", structures_threatened=0, severity="moderate", spread_risk="moderate")
        assert select_loadout_profile(inc) == "aerial_suppression"

    def test_high_containment_is_containment_support(self):
        inc = make_incident(containment_percent=60.0, fire_type="structure", structures_threatened=5)
        assert select_loadout_profile(inc) == "containment_support"

    def test_default_fallback_is_initial_attack(self):
        inc = make_incident(
            severity="low",
            fire_type="structure",
            structures_threatened=3,
            spread_risk="low",
            containment_percent=10.0,
        )
        assert select_loadout_profile(inc) == "initial_attack"

    def test_structure_protection_takes_priority_over_extended(self):
        # critical + WUI should hit structure_protection before extended_suppression
        inc = make_incident(
            severity="critical",
            fire_type="wildland_urban_interface",
            spread_risk="extreme",
        )
        assert select_loadout_profile(inc) == "structure_protection"


# ── assess_confidence ─────────────────────────────────────────────────────────

class TestAssessConfidence:
    def test_all_data_is_high(self):
        # Supply all 7 tracked fields: wind, direction, acres, humidity, slope, elevation, aqi
        inc = make_incident(
            wind_speed_mph=20.0, spread_direction="N", acres_burned=100.0,
            humidity_percent=18.0, slope_percent=15.0, elevation_m=400.0, aqi=45.0,
        )
        assert assess_confidence(inc)[0] == "high"

    def test_two_fields_is_moderate(self):
        # 4 of 7 fields present → 4/7 = 0.57 → moderate
        inc = make_incident(wind_speed_mph=20.0, spread_direction="N", acres_burned=100.0,
                            humidity_percent=18.0, slope_percent=None, elevation_m=None, aqi=None)
        assert assess_confidence(inc)[0] == "moderate"

    def test_one_field_is_low(self):
        # Only wind + humidity (2/7) → low
        inc = make_incident(wind_speed_mph=20.0, spread_direction=None, acres_burned=None,
                            slope_percent=None, elevation_m=None, aqi=None)
        assert assess_confidence(inc)[0] == "low"

    def test_no_data_is_low(self):
        # Only humidity from base (1/7) → low
        inc = make_incident(wind_speed_mph=None, spread_direction=None, acres_burned=None,
                            slope_percent=None, elevation_m=None, aqi=None)
        assert assess_confidence(inc)[0] == "low"


# ── build_summary ─────────────────────────────────────────────────────────────

class TestBuildSummary:
    def test_contains_incident_name(self):
        inc = make_incident(name="Kincade Fire")
        summary = build_summary(inc, "initial_attack")
        assert "Kincade Fire" in summary

    def test_contains_severity(self):
        inc = make_incident(severity="critical")
        summary = build_summary(inc, "initial_attack")
        assert "CRITICAL" in summary

    def test_contains_profile_label(self):
        inc = make_incident()
        summary = build_summary(inc, "aerial_suppression")
        assert "Aerial Suppression" in summary

    def test_mentions_structures_when_threatened(self):
        inc = make_incident(structures_threatened=50)
        summary = build_summary(inc, "structure_protection")
        assert "50" in summary

    def test_no_structure_mention_when_zero(self):
        inc = make_incident(structures_threatened=0)
        summary = build_summary(inc, "initial_attack")
        assert "structures" not in summary.lower() or "0" not in summary


# ── generate_recommendation ───────────────────────────────────────────────────

class TestGenerateRecommendation:
    def test_returns_required_keys(self):
        inc = make_incident()
        result = generate_recommendation(inc, [])
        for key in ["id", "incident_id", "confidence", "loadout_profile",
                    "summary", "unit_recommendations", "route_options", "tactical_notes"]:
            assert key in result, f"Missing key: {key}"

    def test_id_includes_incident_id(self):
        inc = make_incident(id="INC-TEST")
        result = generate_recommendation(inc, [])
        assert "INC-TEST" in result["id"]

    def test_unit_recommendations_not_empty(self):
        inc = make_incident()
        result = generate_recommendation(inc, [])
        assert len(result["unit_recommendations"]) > 0

    def test_unit_recommendations_have_required_fields(self):
        inc = make_incident()
        result = generate_recommendation(inc, [])
        for unit in result["unit_recommendations"]:
            assert "unit_type" in unit
            assert "quantity" in unit
            assert "priority" in unit

    def test_routes_sorted_safe_first(self):
        routes = [
            make_route(id="R1", safety_rating="danger",  estimated_travel_minutes=10),
            make_route(id="R2", safety_rating="safe",    estimated_travel_minutes=30),
            make_route(id="R3", safety_rating="caution", estimated_travel_minutes=20),
        ]
        result = generate_recommendation(make_incident(), routes)
        ratings = [r["safety_rating"] for r in result["route_options"]]
        assert ratings[0] == "safe"
        assert ratings[-1] == "danger"

    def test_routes_same_safety_sorted_by_time(self):
        routes = [
            make_route(id="R1", safety_rating="safe", estimated_travel_minutes=45),
            make_route(id="R2", safety_rating="safe", estimated_travel_minutes=15),
            make_route(id="R3", safety_rating="safe", estimated_travel_minutes=30),
        ]
        result = generate_recommendation(make_incident(), routes)
        times = [r["estimated_travel_minutes"] for r in result["route_options"]]
        assert times == sorted(times)

    def test_empty_routes_ok(self):
        result = generate_recommendation(make_incident(), [])
        assert result["route_options"] == []

    def test_tactical_notes_not_empty(self):
        inc = make_incident()
        result = generate_recommendation(inc, [])
        assert len(result["tactical_notes"]) > 0
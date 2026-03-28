"""
Tests for app/ext/fire_behavior.py

Covers:
  - estimate_rate_of_spread: wind, humidity, slope effects
  - estimate_spotting: FBI thresholds, distance capping
  - estimate_containment_probability: unit/containment effects
  - predict_fire_behavior: full output structure
  - fire_behavior_index: composite score bounds
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app.ext.fire_behavior import (
    estimate_rate_of_spread,
    estimate_spotting,
    estimate_containment_probability,
    predict_fire_behavior,
    fire_behavior_index,
)


# ── estimate_rate_of_spread ───────────────────────────────────────────────────

class TestRateOfSpread:
    def test_returns_positive_value(self):
        ros = estimate_rate_of_spread("wildland", 10.0, 20.0)
        assert ros > 0

    def test_higher_wind_increases_ros(self):
        low  = estimate_rate_of_spread("wildland", 5.0,  20.0)
        high = estimate_rate_of_spread("wildland", 40.0, 20.0)
        assert high > low

    def test_lower_humidity_increases_ros(self):
        wet = estimate_rate_of_spread("wildland", 15.0, 60.0)
        dry = estimate_rate_of_spread("wildland", 15.0, 5.0)
        assert dry > wet

    def test_steeper_slope_increases_ros(self):
        flat  = estimate_rate_of_spread("wildland", 15.0, 20.0, slope_percent=0.0)
        steep = estimate_rate_of_spread("wildland", 15.0, 20.0, slope_percent=50.0)
        assert steep > flat

    def test_ros_clamped_to_max_15(self):
        ros = estimate_rate_of_spread("wildland", 9999.0, 1.0, slope_percent=999.0)
        assert ros <= 15.0

    def test_ros_never_below_min(self):
        ros = estimate_rate_of_spread("wildland", 0.0, 100.0)
        assert ros >= 0.05

    def test_none_inputs_use_defaults(self):
        ros = estimate_rate_of_spread("wildland", None, None)
        assert ros > 0

    def test_wui_lower_than_wildland_same_conditions(self):
        wildland = estimate_rate_of_spread("wildland",                15.0, 20.0)
        wui      = estimate_rate_of_spread("wildland_urban_interface", 15.0, 20.0)
        assert wildland > wui

    def test_structure_lowest_ros(self):
        structure = estimate_rate_of_spread("structure", 15.0, 20.0)
        wildland  = estimate_rate_of_spread("wildland",  15.0, 20.0)
        assert wildland > structure


# ── estimate_spotting ─────────────────────────────────────────────────────────

class TestEstimateSpotting:
    def test_returns_required_keys(self):
        result = estimate_spotting(0.5, 15.0)
        assert "spotting_potential" in result
        assert "spotting_distance_miles" in result

    def test_high_fbi_is_extreme_spotting(self):
        result = estimate_spotting(0.9, 30.0)
        assert result["spotting_potential"] == "extreme"

    def test_low_fbi_is_low_spotting(self):
        result = estimate_spotting(0.1, 5.0)
        assert result["spotting_potential"] == "low"

    def test_spotting_distance_capped_at_8_miles(self):
        result = estimate_spotting(1.0, 9999.0)
        assert result["spotting_distance_miles"] <= 8.0

    def test_no_wind_zero_distance(self):
        result = estimate_spotting(0.8, 0.0)
        assert result["spotting_distance_miles"] == 0.0

    def test_none_wind_treated_as_zero(self):
        result = estimate_spotting(0.8, None)
        assert result["spotting_distance_miles"] == 0.0

    def test_higher_fbi_higher_spotting(self):
        low_fbi  = estimate_spotting(0.2, 20.0)
        high_fbi = estimate_spotting(0.8, 20.0)
        low_cat  = ["low", "moderate", "high", "extreme"].index(low_fbi["spotting_potential"])
        high_cat = ["low", "moderate", "high", "extreme"].index(high_fbi["spotting_potential"])
        assert high_cat >= low_cat


# ── estimate_containment_probability ─────────────────────────────────────────

class TestContainmentProbability:
    def test_returns_float_between_0_and_1(self):
        prob = estimate_containment_probability(0.5, 3, 20.0, 500.0)
        assert 0.0 <= prob <= 1.0

    def test_high_fbi_reduces_probability(self):
        easy = estimate_containment_probability(0.1, 5, 50.0, 100.0)
        hard = estimate_containment_probability(0.9, 5, 50.0, 100.0)
        assert hard < easy

    def test_more_units_increases_probability(self):
        few  = estimate_containment_probability(0.5, 1,  20.0, 500.0)
        many = estimate_containment_probability(0.5, 10, 20.0, 500.0)
        assert many > few

    def test_higher_existing_containment_increases_probability(self):
        low_cont  = estimate_containment_probability(0.5, 3, 10.0,  500.0)
        high_cont = estimate_containment_probability(0.5, 3, 80.0,  500.0)
        assert high_cont > low_cont

    def test_none_inputs_handled(self):
        prob = estimate_containment_probability(0.5, 0, None, None)
        assert 0.0 <= prob <= 1.0


# ── fire_behavior_index ───────────────────────────────────────────────────────

class TestFireBehaviorIndex:
    def test_returns_float_0_to_1(self):
        fbi = fire_behavior_index(15.0, 20.0, "high", 30.0)
        assert 0.0 <= fbi <= 1.0

    def test_extreme_conditions_near_1(self):
        fbi = fire_behavior_index(60.0, 3.0, "extreme", 60.0)
        assert fbi >= 0.7

    def test_calm_conditions_near_0(self):
        fbi = fire_behavior_index(0.0, 80.0, "low", 0.0)
        assert fbi <= 0.4

    def test_none_inputs_handled(self):
        fbi = fire_behavior_index(None, None, "moderate", None)
        assert 0.0 <= fbi <= 1.0


# ── predict_fire_behavior (integration) ──────────────────────────────────────

class TestPredictFireBehavior:
    def test_returns_all_required_keys(self):
        result = predict_fire_behavior(
            fire_type="wildland",
            spread_risk="high",
            wind_speed_mph=20.0,
            humidity_percent=15.0,
            containment_percent=10.0,
            acres_burned=800.0,
            units_on_scene=3,
        )
        expected_keys = [
            "fire_behavior_index",
            "rate_of_spread_mph",
            "spotting_potential",
            "spotting_distance_miles",
            "containment_probability",
            "containment_probability_pct",
            "behavior_description",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_behavior_description_is_string(self):
        result = predict_fire_behavior("wildland", "moderate", 10.0, 25.0, 20.0, 200.0)
        assert isinstance(result["behavior_description"], str)
        assert len(result["behavior_description"]) > 0

    def test_containment_pct_is_rounded_int(self):
        result = predict_fire_behavior("wildland", "moderate", 10.0, 25.0, 20.0, 200.0)
        assert isinstance(result["containment_probability_pct"], int)

    def test_fbi_consistent_with_ros_direction(self):
        calm = predict_fire_behavior("wildland", "low",     0.0,  80.0, 50.0, 100.0)
        wild = predict_fire_behavior("wildland", "extreme", 50.0, 5.0,  0.0,  5000.0)
        assert wild["fire_behavior_index"] > calm["fire_behavior_index"]
        assert wild["rate_of_spread_mph"]  > calm["rate_of_spread_mph"]

    def test_no_units_lower_containment_prob(self):
        no_units   = predict_fire_behavior("wildland", "high", 20.0, 15.0, 10.0, 500.0, units_on_scene=0)
        with_units = predict_fire_behavior("wildland", "high", 20.0, 15.0, 10.0, 500.0, units_on_scene=8)
        assert with_units["containment_probability"] > no_units["containment_probability"]
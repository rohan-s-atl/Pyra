"""
Tests for backend/app/intelligence/spread_risk.py

Covers:
  - compute_terrain_adjusted_risk: slope escalation, wind alignment bonus
  - generate_spread_cone: GeoJSON structure, radius scaling, wind/terrain factors
"""
import math
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

import pytest
from app.intelligence.spread_risk import (
    compute_terrain_adjusted_risk,
    generate_spread_cone,
    SPREAD_RADIUS_KM,
    CONE_HALF_ANGLE,
)


# ── compute_terrain_adjusted_risk ─────────────────────────────────────────────

class TestTerrainAdjustedRisk:
    def test_flat_terrain_no_change(self):
        assert compute_terrain_adjusted_risk("moderate", 5.0, "N", "N") == "moderate"

    def test_none_slope_no_change(self):
        assert compute_terrain_adjusted_risk("moderate", None, "N", "N") == "moderate"

    def test_slope_20_escalates_one_level(self):
        result = compute_terrain_adjusted_risk("low", 25.0, None, None)
        assert result == "moderate"

    def test_slope_40_escalates_two_levels(self):
        result = compute_terrain_adjusted_risk("low", 45.0, None, None)
        assert result == "high"

    def test_cannot_escalate_past_extreme(self):
        result = compute_terrain_adjusted_risk("extreme", 60.0, "N", "N")
        assert result == "extreme"

    def test_wind_aligned_aspect_adds_bonus_step(self):
        # Slope 25% = 1 step normally, aligned wind adds another = 2 steps
        result = compute_terrain_adjusted_risk("low", 25.0, "N", "N")
        assert result == "high"

    def test_wind_misaligned_no_bonus(self):
        # Opposite direction (180° diff) — no alignment bonus
        result = compute_terrain_adjusted_risk("low", 25.0, "N", "S")
        assert result == "moderate"  # only 1 step from slope

    def test_wind_45_deg_diff_still_aligned(self):
        # NE aspect + N wind = 45° diff, still within threshold
        result = compute_terrain_adjusted_risk("low", 25.0, "NE", "N")
        assert result == "high"

    def test_invalid_spread_risk_returned_unchanged(self):
        result = compute_terrain_adjusted_risk("unknown_level", 50.0, None, None)
        assert result == "unknown_level"

    def test_slope_10_to_19_no_escalation(self):
        result = compute_terrain_adjusted_risk("low", 15.0, None, None)
        assert result == "low"


# ── generate_spread_cone ──────────────────────────────────────────────────────

class TestGenerateSpreadCone:
    BASE_KWARGS = dict(
        latitude=34.05,
        longitude=-118.25,
        spread_risk="moderate",
        spread_direction="N",
        wind_speed_mph=None,
        slope_percent=None,
        aspect_cardinal=None,
    )

    def test_returns_geojson_feature(self):
        result = generate_spread_cone(**self.BASE_KWARGS)
        assert result["type"] == "Feature"
        assert result["geometry"]["type"] == "Polygon"

    def test_polygon_is_closed(self):
        result = generate_spread_cone(**self.BASE_KWARGS)
        coords = result["geometry"]["coordinates"][0]
        assert coords[0] == coords[-1], "Polygon must be closed (first == last point)"

    def test_polygon_starts_at_fire_origin(self):
        result = generate_spread_cone(**self.BASE_KWARGS)
        first = result["geometry"]["coordinates"][0][0]
        assert first == pytest.approx([-118.25, 34.05], abs=1e-6)

    def test_base_radius_matches_config(self):
        result = generate_spread_cone(**self.BASE_KWARGS)
        expected = SPREAD_RADIUS_KM["moderate"]
        assert result["properties"]["radius_km"] == pytest.approx(expected, rel=0.01)

    def test_wind_increases_radius(self):
        no_wind = generate_spread_cone(**self.BASE_KWARGS)
        with_wind = generate_spread_cone(**{**self.BASE_KWARGS, "wind_speed_mph": 30.0})
        assert with_wind["properties"]["radius_km"] > no_wind["properties"]["radius_km"]

    def test_wind_radius_capped_at_2x(self):
        # At very high wind speed, factor is capped at 2.0
        result = generate_spread_cone(**{**self.BASE_KWARGS, "wind_speed_mph": 9999.0})
        base_radius = SPREAD_RADIUS_KM["moderate"]
        assert result["properties"]["radius_km"] <= base_radius * 2.0 * 1.01  # small tolerance

    def test_slope_increases_radius(self):
        no_slope = generate_spread_cone(**self.BASE_KWARGS)
        with_slope = generate_spread_cone(**{**self.BASE_KWARGS, "slope_percent": 40.0})
        assert with_slope["properties"]["radius_km"] > no_slope["properties"]["radius_km"]

    def test_extreme_spread_risk_larger_radius(self):
        moderate = generate_spread_cone(**self.BASE_KWARGS)
        extreme = generate_spread_cone(**{**self.BASE_KWARGS, "spread_risk": "extreme"})
        assert extreme["properties"]["radius_km"] > moderate["properties"]["radius_km"]

    def test_terrain_adjusted_flag_set(self):
        # Steep aligned slope should trigger terrain adjustment
        result = generate_spread_cone(**{
            **self.BASE_KWARGS,
            "slope_percent": 45.0,
            "aspect_cardinal": "N",
            "spread_direction": "N",
        })
        assert result["properties"]["terrain_adjusted"] is True

    def test_no_terrain_adjustment_on_flat(self):
        result = generate_spread_cone(**{**self.BASE_KWARGS, "slope_percent": 5.0})
        assert result["properties"]["terrain_adjusted"] is False

    def test_all_cardinal_directions(self):
        for direction in ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]:
            result = generate_spread_cone(**{**self.BASE_KWARGS, "spread_direction": direction})
            assert result["geometry"]["type"] == "Polygon"

    def test_properties_include_required_fields(self):
        result = generate_spread_cone(**self.BASE_KWARGS)
        props = result["properties"]
        for field in ["spread_risk", "terrain_adjusted_risk", "radius_km", "direction_degrees"]:
            assert field in props
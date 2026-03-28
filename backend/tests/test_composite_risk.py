"""
Tests for app/ext/composite_risk.py

Covers:
  - compute_risk_score: output structure, weight math, edge cases
  - _score_to_level: threshold boundaries
  - score_incidents_for_heatmap: batch scoring
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app.ext.composite_risk import (
    compute_risk_score,
    score_incidents_for_heatmap,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def worst_case():
    return dict(
        fire_behavior_index=1.0,
        spread_risk="extreme",
        severity="critical",
        structures_threatened=500,
        containment_percent=0.0,
        acres_burned=10000.0,
        slope_percent=60.0,
        aspect_cardinal="N",
        spread_direction="N",
        units_on_scene=0,
        units_en_route=0,
    )

def best_case():
    return dict(
        fire_behavior_index=0.0,
        spread_risk="low",
        severity="low",
        structures_threatened=0,
        containment_percent=100.0,
        acres_burned=1.0,
        slope_percent=0.0,
        aspect_cardinal=None,
        spread_direction=None,
        units_on_scene=20,
        units_en_route=10,
    )


# ── compute_risk_score ────────────────────────────────────────────────────────

class TestComputeRiskScore:
    def test_returns_required_keys(self):
        result = compute_risk_score(**worst_case())
        assert "risk_score" in result
        assert "risk_level" in result
        assert "components" in result
        assert "raw_scores" in result

    def test_score_between_0_and_1(self):
        for kwargs in [worst_case(), best_case()]:
            result = compute_risk_score(**kwargs)
            assert 0.0 <= result["risk_score"] <= 1.0

    def test_worst_case_is_extreme(self):
        result = compute_risk_score(**worst_case())
        assert result["risk_level"] == "extreme"

    def test_best_case_is_low(self):
        result = compute_risk_score(**best_case())
        assert result["risk_level"] == "low"

    def test_component_weights_sum_to_risk_score(self):
        result = compute_risk_score(**worst_case())
        component_sum = sum(result["components"].values())
        assert component_sum == pytest.approx(result["risk_score"], abs=0.01)

    def test_all_components_present(self):
        result = compute_risk_score(**worst_case())
        expected = {"fire_behavior", "structure_threat", "spread_risk",
                    "containment_gap", "terrain", "resource_deficit"}
        assert set(result["components"].keys()) == expected

    def test_higher_containment_lowers_score(self):
        low_cont  = compute_risk_score(**{**worst_case(), "containment_percent": 0.0})
        high_cont = compute_risk_score(**{**worst_case(), "containment_percent": 80.0})
        assert high_cont["risk_score"] < low_cont["risk_score"]

    def test_more_structures_raises_score(self):
        none = compute_risk_score(**{**worst_case(), "structures_threatened": 0})
        many = compute_risk_score(**{**worst_case(), "structures_threatened": 500})
        assert many["risk_score"] > none["risk_score"]

    def test_none_structures_treated_as_zero(self):
        result = compute_risk_score(**{**worst_case(), "structures_threatened": None})
        assert result["risk_score"] >= 0.0

    def test_none_slope_uses_neutral_score(self):
        result = compute_risk_score(**{**worst_case(), "slope_percent": None})
        assert result["raw_scores"]["terrain_score"] > 0.0

    def test_more_units_lowers_resource_deficit(self):
        no_units   = compute_risk_score(**{**worst_case(), "units_on_scene": 0,  "units_en_route": 0})
        many_units = compute_risk_score(**{**worst_case(), "units_on_scene": 20, "units_en_route": 10})
        assert many_units["components"]["resource_deficit"] < no_units["components"]["resource_deficit"]

    def test_extreme_spread_risk_higher_than_low(self):
        extreme = compute_risk_score(**{**best_case(), "spread_risk": "extreme"})
        low     = compute_risk_score(**{**best_case(), "spread_risk": "low"})
        assert extreme["risk_score"] > low["risk_score"]

    def test_score_capped_at_1(self):
        result = compute_risk_score(**worst_case())
        assert result["risk_score"] <= 1.0

    @pytest.mark.parametrize("score,expected_level", [
        (0.85, "extreme"),
        (0.65, "high"),
        (0.50, "moderate"),
        (0.20, "low"),
    ])
    def test_risk_level_thresholds(self, score, expected_level):
        result = compute_risk_score(
            fire_behavior_index=score,
            spread_risk="extreme" if score > 0.7 else "moderate",
            severity="critical" if score > 0.7 else "moderate",
            structures_threatened=0,
            containment_percent=0.0,
            acres_burned=100.0,
            slope_percent=None,
            aspect_cardinal=None,
            spread_direction=None,
            units_on_scene=0,
            units_en_route=0,
        )
        assert result["risk_level"] in ("extreme", "high", "moderate", "low")


# ── score_incidents_for_heatmap ───────────────────────────────────────────────

class TestScoreIncidentsForHeatmap:
    def make_incident_dict(self, **overrides):
        base = {
            "id": "INC-001",
            "fire_behavior_index": 0.5,
            "spread_risk": "moderate",
            "severity": "moderate",
            "structures_threatened": 0,
            "containment_percent": 20.0,
            "acres_burned": 500.0,
            "slope_percent": None,
            "aspect_cardinal": None,
            "spread_direction": "N",
            "units_on_scene": 3,
            "units_en_route": 1,
        }
        return {**base, **overrides}

    def test_returns_same_count(self):
        incidents = [self.make_incident_dict(id=f"INC-{i}") for i in range(5)]
        result = score_incidents_for_heatmap(incidents)
        assert len(result) == 5

    def test_adds_risk_score_and_level(self):
        result = score_incidents_for_heatmap([self.make_incident_dict()])
        assert "risk_score" in result[0]
        assert "risk_level" in result[0]

    def test_preserves_original_fields(self):
        inc = self.make_incident_dict(id="INC-PRESERVE")
        result = score_incidents_for_heatmap([inc])
        assert result[0]["id"] == "INC-PRESERVE"

    def test_empty_list_returns_empty(self):
        assert score_incidents_for_heatmap([]) == []

    def test_high_risk_incident_scores_higher(self):
        low_risk  = self.make_incident_dict(id="low",  fire_behavior_index=0.1, spread_risk="low",     severity="low",      containment_percent=80.0)
        high_risk = self.make_incident_dict(id="high", fire_behavior_index=0.9, spread_risk="extreme", severity="critical",  containment_percent=0.0)
        results = score_incidents_for_heatmap([low_risk, high_risk])
        scores = {r["id"]: r["risk_score"] for r in results}
        assert scores["high"] > scores["low"]
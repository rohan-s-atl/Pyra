from app.api.loadout import _parse_loadout_response


def test_parse_loadout_response_salvages_complete_items_from_truncated_json():
    raw = """
    {
      "overall_strategy": "Aggressive initial attack with maximum water application.",
      "loadouts": [
        {
          "unit_id": "CDF-NEU-WT-1",
          "unit_type": "water_tender",
          "designation": "Water Tender",
          "water_pct": 100,
          "foam_pct": 0,
          "retardant_pct": 0,
          "equipment": ["Portable tank (3000 gal)", "Portable pump"],
          "rationale": "Primary water supply.",
          "equipment_notes": {
            "Portable tank (3000 gal)": "Supports refill ops."
          }
        },
        {
          "unit_id": "CDF-NEU-ENG-1",
          "unit_type": "engine",
          "designation": "Engine 1",
          "water_pct": 100,
          "foam_pct": 3,
          "retardant_pct": 0,
          "equipment": ["Foam proportioner"],
          "rationale": "Structure protection",
          "equipment_notes": {
            "Foam proportioner": "WUI deployment"
    """

    parsed = _parse_loadout_response(raw)

    assert parsed["overall_strategy"] == "Aggressive initial attack with maximum water application."
    assert len(parsed["loadouts"]) == 1
    assert parsed["loadouts"][0]["unit_id"] == "CDF-NEU-WT-1"
    assert parsed["loadouts"][0]["equipment_notes"]["Portable tank (3000 gal)"] == "Supports refill ops."

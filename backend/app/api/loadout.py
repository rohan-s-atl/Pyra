"""
Loadout configurator API — POST /api/dispatch/loadout-advice

Takes an incident + list of selected unit IDs, calls Claude to recommend
exact loadout values (water %, foam %, retardant %, equipment checklist)
for each unit based on real fire conditions.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import anthropic
import json
import logging

from app.core.database import get_db
from app.core.config import settings
from app.core.security import require_dispatcher_or_above
from app.core.limiter import limiter
from app.models.incident import Incident
from app.models.unit import Unit
from app.models.user import User

from fastapi import Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dispatch/loadout", tags=["Loadout"])

# ── Equipment options per unit type ──────────────────────────────────────────

EQUIPMENT_OPTIONS = {
    "engine": [
        "Chainsaw", "Hand tools (Pulaskis, McLeods)", "Drip torch",
        "Foam proportioner", "Water thief / gated wye", "Salvage covers",
        "Medical kit (ALS)", "Thermal imaging camera", "Portable pump",
        "Extra hose (100ft sections)",
    ],
    "hand_crew": [
        "Chainsaws (2×)", "Hand tools (full set)", "Drip torches (2×)",
        "Fusees / flares", "Medical kit (ALS)", "Portable radio (extra)",
        "Water bladder bags (4×)", "Crew shelter (individual)",
        "Headlamps (night ops)", "GPS units",
    ],
    "dozer": [
        "Dozer blade (standard)", "Brush guard", "Fire shelter (operator)",
        "Medical kit", "GPS / mapping unit", "Portable radio",
        "Extra fuel (jerry cans)", "Tool kit",
    ],
    "water_tender": [
        "Portable tank (3000 gal)", "Foam system", "Extra hose (200ft)",
        "Portable pump", "Nozzles (varied)", "Water thief",
        "Medical kit", "Portable radio",
    ],
    "helicopter": [
        "Helibucket (300 gal)", "Belly tank", "Hoist / rescue equipment",
        "IR / FLIR camera", "Medical kit (flight medic)", "Night vision (NVG)",
        "Cargo net / sling", "Extra fuel (ferry cans)",
    ],
    "air_tanker": [
        "Fire retardant (Phos-Chek)", "Water load", "Foam additive",
        "Air tactical radio package", "GPS / terrain mapping",
    ],
    "command_unit": [
        "Satellite comms", "Radio repeater", "Weather station (portable)",
        "Drone / UAV", "GIS / mapping laptop", "Generator",
        "Medical kit", "Command board / whiteboard",
    ],
    "rescue": [
        "ALS medical kit", "Extrication tools (Jaws of Life)", "Backboard / stretcher",
        "Oxygen / airway kit", "IV supplies", "Burn treatment kit",
        "Portable radio", "GPS unit",
    ],
}

# ── Capacity limits per unit type ─────────────────────────────────────────────

UNIT_CAPACITY = {
    "engine":        {"water_gal": 500,  "foam_pct_max": 6,  "retardant_pct_max": 0},
    "water_tender":  {"water_gal": 4000, "foam_pct_max": 3,  "retardant_pct_max": 0},
    "helicopter":    {"water_gal": 300,  "foam_pct_max": 1,  "retardant_pct_max": 0},
    "air_tanker":    {"water_gal": 0,    "foam_pct_max": 0,  "retardant_pct_max": 100},
    "hand_crew":     {"water_gal": 0,    "foam_pct_max": 0,  "retardant_pct_max": 0},
    "dozer":         {"water_gal": 0,    "foam_pct_max": 0,  "retardant_pct_max": 0},
    "command_unit":  {"water_gal": 0,    "foam_pct_max": 0,  "retardant_pct_max": 0},
    "rescue":        {"water_gal": 0,    "foam_pct_max": 0,  "retardant_pct_max": 0},
}


# ── Schemas ───────────────────────────────────────────────────────────────────

class LoadoutAdviceRequest(BaseModel):
    unit_ids: List[str]


class UnitLoadout(BaseModel):
    unit_id:         str
    unit_type:       str
    designation:     str
    water_pct:       int            # 0–100% of tank capacity
    foam_pct:        int            # 0–6% foam concentrate ratio
    retardant_pct:   int            # 0–100% (air tanker only)
    equipment:       List[str]      # pre-checked equipment items
    equipment_notes: dict          # item -> why included/excluded
    rationale:       str            # why these settings for this unit


class LoadoutAdviceResponse(BaseModel):
    loadouts:        List[UnitLoadout]
    overall_strategy: str


# ── Helper: build Claude prompt ───────────────────────────────────────────────

def _build_prompt(incident: Incident, units: List[Unit]) -> str:
    unit_list = "\n".join([
        f"  - unit_id={u.id} | designation={u.designation} | type={u.unit_type.replace('_', ' ').title()}"
        for u in units
    ])

    equipment_by_type = {}
    for u in units:
        if u.unit_type not in equipment_by_type:
            opts = EQUIPMENT_OPTIONS.get(u.unit_type, [])
            equipment_by_type[u.unit_type] = opts

    equipment_context = "\n".join([
        f"  {utype}: {', '.join(items)}"
        for utype, items in equipment_by_type.items()
    ])

    caps_context = "\n".join([
        f"  {utype}: water_gal={v['water_gal']}, foam_pct_max={v['foam_pct_max']}%, retardant_pct_max={v['retardant_pct_max']}%"
        for utype, v in UNIT_CAPACITY.items()
        if utype in {u.unit_type for u in units}
    ])

    return f"""You are an expert CAL FIRE incident commander configuring unit loadouts for dispatch.

INCIDENT: {incident.name}
- Severity: {incident.severity}
- Fire type: {incident.fire_type.replace('_', ' ')}
- Spread risk: {incident.spread_risk}
- Spread direction: {incident.spread_direction or 'unknown'}
- Wind speed: {incident.wind_speed_mph or 'unknown'} mph
- Humidity: {incident.humidity_percent or 'unknown'}%
- Acres burned: {incident.acres_burned or 'unknown'}
- Containment: {incident.containment_percent or 0}%
- Structures threatened: {incident.structures_threatened or 0}
- Terrain slope: {incident.slope_percent or 'unknown'}%
- AQI: {incident.aqi or 'unknown'}

UNITS TO CONFIGURE:
{unit_list}

UNIT CAPACITIES:
{caps_context}

AVAILABLE EQUIPMENT PER TYPE:
{equipment_context}

For each unit, recommend:
1. water_pct (0-100): percentage of water tank to fill. 100 = full tank.
2. foam_pct (0-6): foam concentrate ratio as percentage. 0 = pure water. Max varies by unit.
3. retardant_pct (0-100): retardant load percentage (air tankers only, 0 for all others).
4. equipment: list of specific equipment items to load from the available options. Pick what's operationally appropriate — not everything, just what makes sense for this specific assignment.
5. rationale: 1-2 sentence tactical justification for these settings.

Also provide an overall_strategy: 1-2 sentences summarizing the loadout philosophy for this deployment.

Consider:
- WUI fires need more foam for structure protection
- High wind + dry conditions = fill water to max, consider foam
- Air tankers get retardant for head/flank drops, water for structure prep
- Mop-up operations need less water, more hand tools
- Night operations need headlamps, NVGs
- High AQI = include medical kit on all units
- Steep terrain = chainsaws, hand tools priority

Be direct and specific. Do NOT say "consider" or "may want" — give a firm recommendation.

Respond ONLY with valid JSON, no markdown, no explanation outside the JSON:
{{
  "overall_strategy": "...",
  "loadouts": [
    {{
      "unit_id": "...",
      "unit_type": "...",
      "designation": "...",
      "water_pct": 0-100,
      "foam_pct": 0-6,
      "retardant_pct": 0-100,
      "equipment": ["item1", "item2"],
      "rationale": "...",
      "equipment_notes": {{
        "item_name": "reason why included or excluded"
      }}
    }}
  ]
}}

For equipment_notes, explain every item in the full list for this unit type — say WHY each item is included or excluded. Example: {{"Chainsaw": "Include — dense brush on approach route", "Medical kit (ALS)": "Include — AQI 180 smoke exposure risk", "Salvage covers": "Skip — no structure threat on this assignment"}}"""


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/{incident_id}",
    response_model=LoadoutAdviceResponse,
    summary="Get AI loadout recommendations for selected units",
)
@limiter.limit("15/minute")
async def get_loadout_advice(
    request: Request,
    incident_id: str,
    body: LoadoutAdviceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dispatcher_or_above),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    units = db.query(Unit).filter(Unit.id.in_(body.unit_ids)).all()
    if not units:
        raise HTTPException(status_code=400, detail="No valid units found")

    if not settings.anthropic_api_key:
        # Fallback: return sensible defaults without Claude
        return _default_loadouts(incident, units)

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        prompt = _build_prompt(incident, units)

        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.split("\n")[:-1])

        data = json.loads(raw)

        # Build lookup maps for robust matching
        units_by_id   = {u.id: u for u in units}
        units_by_desig = {u.designation: u for u in units}

        loadouts = []
        for item in data.get("loadouts", []):
            raw_id = item.get("unit_id", "")
            raw_desig = item.get("designation", "")

            # Match to real unit: try ID first, then designation
            matched_unit = units_by_id.get(raw_id) or units_by_desig.get(raw_desig)
            if not matched_unit:
                logger.warning(f"Could not match Claude unit_id={raw_id!r} desig={raw_desig!r} to any unit — skipping")
                continue

            cap = UNIT_CAPACITY.get(matched_unit.unit_type, {})
            loadouts.append(UnitLoadout(
                unit_id=matched_unit.id,          # always use the real DB id
                unit_type=matched_unit.unit_type,
                designation=matched_unit.designation,
                water_pct=max(0, min(100, int(item.get("water_pct", 100)))),
                foam_pct=max(0, min(cap.get("foam_pct_max", 6), int(item.get("foam_pct", 0)))),
                retardant_pct=max(0, min(100, int(item.get("retardant_pct", 0)))),
                equipment=item.get("equipment", []),
                equipment_notes=item.get("equipment_notes", {}),
                rationale=item.get("rationale", ""),
            ))

        return LoadoutAdviceResponse(
            loadouts=loadouts,
            overall_strategy=data.get("overall_strategy", ""),
        )

    except Exception as e:
        logger.error(f"Loadout advice failed: {e}")
        return _default_loadouts(incident, units)


def _default_loadouts(incident: Incident, units: List[Unit]) -> LoadoutAdviceResponse:
    """Sensible rule-based defaults when Claude is unavailable."""
    is_wui = incident.fire_type == "wildland_urban_interface"
    is_critical = incident.severity == "critical"
    high_wind = (incident.wind_speed_mph or 0) > 20
    dry = (incident.humidity_percent or 50) < 20

    loadouts = []
    for unit in units:
        cap = UNIT_CAPACITY.get(unit.unit_type, {})
        opts = EQUIPMENT_OPTIONS.get(unit.unit_type, [])

        water_pct = 100
        foam_pct = 0
        retardant_pct = 0
        equipment = opts[:4]  # first 4 as safe defaults
        rationale = "Default loadout — configure based on assignment."

        if unit.unit_type == "engine":
            water_pct = 100
            foam_pct = 3 if is_wui else 0
            equipment = ["Hand tools (Pulaskis, McLeods)", "Medical kit (ALS)"]
            if is_wui:
                equipment += ["Foam proportioner", "Salvage covers"]
            if high_wind or dry:
                equipment += ["Thermal imaging camera"]
            rationale = "Full water for sustained ops." + (" Foam added for WUI structure protection." if is_wui else "")

        elif unit.unit_type == "water_tender":
            water_pct = 100
            foam_pct = 1 if is_wui else 0
            equipment = ["Portable tank (3000 gal)", "Extra hose (200ft)", "Portable pump"]
            rationale = "Full load for water shuttle operations."

        elif unit.unit_type == "air_tanker":
            retardant_pct = 100
            equipment = ["Fire retardant (Phos-Chek)", "Air tactical radio package", "GPS / terrain mapping"]
            rationale = "Full retardant load for forward head suppression."

        elif unit.unit_type == "helicopter":
            water_pct = 100
            equipment = ["Helibucket (300 gal)", "Medical kit (flight medic)"]
            if is_critical:
                equipment += ["Hoist / rescue equipment"]
            rationale = "Full water for aerial drops and crew transport."

        elif unit.unit_type == "hand_crew":
            equipment = ["Chainsaws (2×)", "Hand tools (full set)", "Medical kit (ALS)", "Crew shelter (individual)"]
            if high_wind:
                equipment += ["Fusees / flares"]
            rationale = "Standard hand crew loadout for line construction."

        elif unit.unit_type == "dozer":
            equipment = ["Dozer blade (standard)", "Fire shelter (operator)", "Medical kit", "Portable radio"]
            rationale = "Standard dozer configuration for line construction."

        elif unit.unit_type == "command_unit":
            equipment = ["Satellite comms", "Weather station (portable)", "GIS / mapping laptop", "Command board / whiteboard"]
            rationale = "Full command post configuration."

        elif unit.unit_type == "rescue":
            equipment = ["ALS medical kit", "Oxygen / airway kit", "Burn treatment kit", "Backboard / stretcher"]
            rationale = "Full medical loadout for firefighter and civilian support."

        loadouts.append(UnitLoadout(
            unit_id=unit.id,
            unit_type=unit.unit_type,
            designation=unit.designation,
            water_pct=water_pct,
            foam_pct=foam_pct,
            retardant_pct=retardant_pct,
            equipment=equipment,
            equipment_notes={},
            rationale=rationale,
        ))

    strategy = (
        "WUI structure protection posture — foam enabled on engines, full water loads throughout."
        if is_wui else
        "Wildland suppression posture — full water loads, hand line priority."
    )

    return LoadoutAdviceResponse(loadouts=loadouts, overall_strategy=strategy)
from __future__ import annotations

UNIT_PROFILES = {
    'engine': {
        'category': 'ground', 'personnel': 4, 'water_gallons': 750,
        'strengths': ['structure protection', 'hose line operations', 'road access'],
    },
    'hand_crew': {
        'category': 'ground', 'personnel': 20, 'water_gallons': 0,
        'strengths': ['line construction', 'terrain access', 'mop-up'],
    },
    'dozer': {
        'category': 'ground', 'personnel': 2, 'water_gallons': 0,
        'strengths': ['fire line construction', 'access opening'],
    },
    'water_tender': {
        'category': 'ground', 'personnel': 2, 'water_gallons': 1800,
        'strengths': ['water supply', 'support'],
    },
    'command_unit': {
        'category': 'ground', 'personnel': 2, 'water_gallons': 0,
        'strengths': ['coordination', 'incident command'],
    },
    'rescue': {
        'category': 'ground', 'personnel': 2, 'water_gallons': 0,
        'strengths': ['medical', 'extraction'],
    },
    'helicopter': {
        'category': 'air', 'personnel': 2, 'water_gallons': 600,
        'strengths': ['bucket drops', 'reconnaissance', 'crew transport'],
    },
    'air_tanker': {
        'category': 'air', 'personnel': 2, 'water_gallons': 3000,
        'strengths': ['retardant line', 'rapid initial attack'],
    },
}


def get_profile(unit_type: str):
    return UNIT_PROFILES.get((unit_type or '').lower())


def format_capability_summary(unit_type: str) -> str:
    profile = get_profile(unit_type)
    if not profile:
        return 'General wildfire support unit.'
    strengths = ', '.join(profile.get('strengths', []))
    water = profile.get('water_gallons', 0)
    personnel = profile.get('personnel', 0)
    if water:
        return f"{personnel} personnel, {water} gal capacity. Best for {strengths}."
    return f"{personnel} personnel. Best for {strengths}."

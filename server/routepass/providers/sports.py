"""Sport vocabularies. The canonical sport of an Activity is a Strava sport_type."""

from __future__ import annotations

import json
from pathlib import Path

_MAPPINGS = json.loads((Path(__file__).parent / "sport_mappings.json").read_text())

KOMOOT_LABELS: dict[str, str] = _MAPPINGS["labels"]
KOMOOT_TO_STRAVA: dict[str, str] = _MAPPINGS["komoot_to_strava"]
STRAVA_TO_KOMOOT: dict[str, str] = _MAPPINGS["strava_to_komoot"]

FAMILIES: dict[str, tuple[str, ...]] = {
    "ride": (
        "Ride",
        "MountainBikeRide",
        "GravelRide",
        "EBikeRide",
        "EMountainBikeRide",
        "VirtualRide",
        "Velomobile",
        "Handcycle",
    ),
    "run": ("Run", "TrailRun", "VirtualRun"),
    "walk": ("Walk", "Hike"),
    "winter": (
        "AlpineSki",
        "BackcountrySki",
        "NordicSki",
        "Snowboard",
        "Snowshoe",
        "IceSkate",
    ),
    "water": (
        "Swim",
        "Kayaking",
        "Canoeing",
        "Rowing",
        "StandUpPaddling",
        "Surfing",
        "Kitesurf",
        "Windsurf",
        "Sail",
    ),
}
_FAMILY_OF = {sport: fam for fam, sports in FAMILIES.items() for sport in sports}

LABELS: dict[str, str] = {
    "Ride": "Ride",
    "MountainBikeRide": "Mountain Bike",
    "GravelRide": "Gravel",
    "EBikeRide": "E-Bike",
    "EMountainBikeRide": "E-MTB",
    "VirtualRide": "Virtual Ride",
    "Run": "Run",
    "TrailRun": "Trail Run",
    "VirtualRun": "Virtual Run",
    "Walk": "Walk",
    "Hike": "Hike",
    "AlpineSki": "Alpine Ski",
    "BackcountrySki": "Ski Touring",
    "NordicSki": "Nordic Ski",
    "Snowboard": "Snowboard",
    "Snowshoe": "Snowshoe",
    "Swim": "Swim",
    "Kayaking": "Kayak",
    "Canoeing": "Canoe",
    "Rowing": "Rowing",
    "RockClimbing": "Climbing",
    "Workout": "Workout",
    "WeightTraining": "Weights",
    "Yoga": "Yoga",
}


def family(sport: str) -> str:
    return _FAMILY_OF.get(sport, "other")


def label(sport: str) -> str:
    if sport in LABELS:
        return LABELS[sport]
    if sport in KOMOOT_LABELS:
        return KOMOOT_LABELS[sport]
    # CamelCase → words
    out = "".join(" " + c if c.isupper() else c for c in sport).strip()
    return out or "Activity"


def komoot_to_strava(sport: str) -> str:
    return KOMOOT_TO_STRAVA.get(sport, KOMOOT_TO_STRAVA.get("_default", "Workout"))


def strava_to_komoot(sport: str) -> str:
    return STRAVA_TO_KOMOOT.get(sport, "touringbicycle")


def canonical(provider: str, sport: str) -> str:
    return komoot_to_strava(sport) if provider == "komoot" else (sport or "Workout")


def all_strava_sports() -> list[str]:
    seen = dict.fromkeys(LABELS)
    for sport in KOMOOT_TO_STRAVA.values():
        seen.setdefault(sport)
    return list(seen)


def all_komoot_sports() -> list[str]:
    return sorted({k for k in KOMOOT_TO_STRAVA if not k.startswith("_")})

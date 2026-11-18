"""Sport vocabularies and the Strava ⇄ Komoot mapping.

The canonical sport of an Activity is a Strava `sport_type`. Every Strava sport type and every
Komoot sport id has an explicit entry here; tests assert that each maps to a valid id on the
other platform, so uploads never send a sport the target does not know.

Komoot ids come from Komoot's web app (the full recordable list); Strava types from the
API's SportType enum.
"""

from __future__ import annotations

# Strava sport_type → (label, family, Komoot sport for uploads)
STRAVA: dict[str, tuple[str, str, str]] = {
    # cycling
    "Ride": ("Ride", "ride", "touringbicycle"),
    "GravelRide": ("Gravel Ride", "ride", "mtb_easy"),
    "MountainBikeRide": ("Mountain Bike Ride", "ride", "mtb"),
    "EBikeRide": ("E-Bike Ride", "ride", "e_touringbicycle"),
    "EMountainBikeRide": ("E-Mountain Bike Ride", "ride", "e_mtb"),
    "VirtualRide": ("Virtual Ride", "ride", "racebike"),
    "Velomobile": ("Velomobile", "ride", "touringbicycle"),
    "Handcycle": ("Handcycle", "ride", "touringbicycle"),
    # running
    "Run": ("Run", "run", "jogging"),
    "TrailRun": ("Trail Run", "run", "jogging"),
    "VirtualRun": ("Virtual Run", "run", "jogging"),
    # walking
    "Walk": ("Walk", "walk", "hike"),
    "Hike": ("Hike", "walk", "hike"),
    "Wheelchair": ("Wheelchair", "walk", "other"),
    # winter
    "AlpineSki": ("Alpine Ski", "winter", "skialpin"),
    "BackcountrySki": ("Backcountry Ski", "winter", "skitour"),
    "NordicSki": ("Nordic Ski", "winter", "nordic"),
    "Snowboard": ("Snowboard", "winter", "snowboard"),
    "Snowshoe": ("Snowshoe", "winter", "snowshoe"),
    "IceSkate": ("Ice Skate", "winter", "skaten"),
    # water
    "Swim": ("Swim", "water", "other"),
    "Kayaking": ("Kayaking", "water", "other"),
    "Canoeing": ("Canoe", "water", "other"),
    "Rowing": ("Rowing", "water", "other"),
    "VirtualRow": ("Virtual Row", "water", "other"),
    "StandUpPaddling": ("Stand Up Paddling", "water", "other"),
    "Surfing": ("Surfing", "water", "other"),
    "Kitesurf": ("Kitesurf", "water", "other"),
    "Windsurf": ("Windsurf", "water", "other"),
    "Sail": ("Sail", "water", "other"),
    # wheels / skates
    "InlineSkate": ("Inline Skate", "other", "skaten"),
    "RollerSki": ("Roller Ski", "other", "nordic"),
    "Skateboard": ("Skateboard", "other", "skaten"),
    # climbing & mountains
    "RockClimbing": ("Rock Climb", "other", "climbing"),
    # gym & everything else
    "Workout": ("Workout", "other", "other"),
    "WeightTraining": ("Weight Training", "other", "other"),
    "Crossfit": ("Crossfit", "other", "other"),
    "HighIntensityIntervalTraining": ("HIIT", "other", "other"),
    "Elliptical": ("Elliptical", "other", "other"),
    "StairStepper": ("Stair Stepper", "other", "other"),
    "Yoga": ("Yoga", "other", "other"),
    "Pilates": ("Pilates", "other", "other"),
    "Golf": ("Golf", "other", "other"),
    "Soccer": ("Football (Soccer)", "other", "other"),
    "Tennis": ("Tennis", "other", "other"),
    "TableTennis": ("Table Tennis", "other", "other"),
    "Badminton": ("Badminton", "other", "other"),
    "Squash": ("Squash", "other", "other"),
    "Racquetball": ("Racquetball", "other", "other"),
    "Pickleball": ("Pickleball", "other", "other"),
}

# Komoot sport id → (label, Strava sport_type for uploads)
KOMOOT: dict[str, tuple[str, str]] = {
    "hike": ("Hiking", "Hike"),
    "mountaineering": ("Mountaineering", "Hike"),
    "jogging": ("Running", "Run"),
    "touringbicycle": ("Bike Touring", "Ride"),
    "racebike": ("Road Cycling", "Ride"),
    "mtb": ("Mountain Biking", "MountainBikeRide"),
    "mtb_easy": ("Gravel Riding", "GravelRide"),
    "mtb_advanced": ("Enduro Mountain Biking", "MountainBikeRide"),
    "downhillbike": ("Downhill Mountain Biking", "MountainBikeRide"),
    "unicycle": ("Unicycle", "Ride"),
    "e_touringbicycle": ("E-Bike Touring", "EBikeRide"),
    "e_racebike": ("E-Road Cycling", "EBikeRide"),
    "e_mtb": ("E-Mountain Biking", "EMountainBikeRide"),
    "e_mtb_easy": ("E-Gravel Riding", "EBikeRide"),
    "e_mtb_advanced": ("E-Enduro Mountain Biking", "EMountainBikeRide"),
    "climbing": ("Climbing", "RockClimbing"),
    "nordic": ("Cross-Country Skiing", "NordicSki"),
    "nordicwalking": ("Nordic Walking", "Walk"),
    "skaten": ("Inline Skating", "InlineSkate"),
    "skialpin": ("Alpine Skiing", "AlpineSki"),
    "skitour": ("Ski Touring", "BackcountrySki"),
    "sled": ("Sledding", "Workout"),
    "snowboard": ("Snowboarding", "Snowboard"),
    "snowshoe": ("Snowshoeing", "Snowshoe"),
    "other": ("Other", "Workout"),
}

# Older or alternative spellings seen in Komoot data → canonical Komoot id.
KOMOOT_ALIASES: dict[str, str] = {
    "running": "jogging",
    "trail_running": "jogging",
    "touringbike": "touringbicycle",
    "citybike": "touringbicycle",
    "road_cycling": "racebike",
    "gravelbike": "mtb_easy",
    "mountainbike": "mtb",
    "singletrack": "mtb_advanced",
    "mtb_enduro": "mtb_advanced",
    "downhillmtb": "downhillbike",
    "e_touringbike": "e_touringbicycle",
    "e_citybike": "e_touringbicycle",
    "e_road_cycling": "e_racebike",
    "e_gravelbike": "e_mtb_easy",
    "e_mtb_enduro": "e_mtb_advanced",
    "hiking": "hike",
    "walking": "hike",
    "nordic_walking": "nordicwalking",
    "skitouring": "skitour",
    "skicrosscountry": "nordic",
    "crosscountryskiing": "nordic",
    "nordic_ski": "nordic",
    "skating": "skaten",
    "snowshoeing": "snowshoe",
}


def family(sport: str) -> str:
    entry = STRAVA.get(sport)
    return entry[1] if entry else "other"


def label(sport: str) -> str:
    if sport in STRAVA:
        return STRAVA[sport][0]
    k = normalize_komoot(sport)
    if k in KOMOOT:
        return KOMOOT[k][0]
    out = "".join(" " + c if c.isupper() else c for c in sport).strip()
    return out or "Activity"


def normalize_komoot(sport: str) -> str:
    sport = (sport or "").strip()
    return KOMOOT_ALIASES.get(sport, sport)


def komoot_to_strava(sport: str) -> str:
    entry = KOMOOT.get(normalize_komoot(sport))
    return entry[1] if entry else "Workout"


def strava_to_komoot(sport: str) -> str:
    entry = STRAVA.get(sport)
    return entry[2] if entry else "other"


def canonical(provider: str, sport: str) -> str:
    if provider == "komoot":
        return komoot_to_strava(sport)
    return sport if sport in STRAVA else (sport or "Workout")


def all_strava_sports() -> list[str]:
    return list(STRAVA)


def all_komoot_sports() -> list[str]:
    return list(KOMOOT)

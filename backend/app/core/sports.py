import json
from pathlib import Path

# Load shared sport mappings from the monorepo root
_SPORTS_FILE = Path(__file__).parent.parent.parent.parent / "shared" / "sport-mappings.json"

with open(_SPORTS_FILE, "r", encoding="utf-8") as f:
    SPORTS_CONFIG = json.load(f)

SPORT_LABELS: dict[str, str] = SPORTS_CONFIG.get("labels", {})
GPX_SPORT_TYPE_MAP: dict[str, str] = SPORTS_CONFIG.get("gpx_mapping", {})
KOMOOT_TO_STRAVA: dict[str, str] = SPORTS_CONFIG.get("komoot_to_strava", {})
STRAVA_TO_KOMOOT: dict[str, str] = SPORTS_CONFIG.get("strava_to_komoot", {})

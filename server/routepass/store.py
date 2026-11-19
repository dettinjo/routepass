"""Typed access to the key/value settings table (preferences, credentials, watermarks)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from routepass.models import Setting
from routepass.security import decrypt, encrypt

DIRECTIONS = ("strava_to_komoot", "komoot_to_strava")

DEFAULT_PREFERENCES: dict[str, Any] = {
    "sync": {
        "auto": True,  # run the sync engine after every scheduled poll
        "start_date": None,  # ISO date; activities before it are never synced automatically
        # Wait after an activity first appears, so devices uploading to both platforms win the race.
        "delay_minutes": 10,
        "strava_to_komoot": {
            "enabled": False,
            "default_action": "sync",
            "defaults": {"komoot": {"visibility": "private"}},
        },
        "komoot_to_strava": {
            "enabled": False,
            "default_action": "sync",
            "sync_photos": True,
            "defaults": {},
        },
    },
    "matching": {
        "time_tolerance_min": 10,  # start times this close may be the same activity
        "distance_tolerance_pct": 15,
    },
    "profile": {
        "ftp": None,
        "hr_max": None,
        "hr_rest": None,
        "weight_kg": None,
    },
    # Targets for the Goals view (empty = not tracked)
    "goals": {
        "weekly_distance_km": None,
        "weekly_time_hours": None,
        "monthly_distance_km": None,
        "yearly_distance_km": None,
        "yearly_elevation_m": None,
    },
    # Per gear (Strava gear id or name): {"label": "Road bike", "service_km": 3000}
    "gear_targets": {},
    # Named places for geofence rules: [{"name": "Home", "lat": .., "lng": .., "radius_km": 0.5}]
    "places": [],
    # 50k / trail race training target (used by Trail tab & MCP AI Coach)
    "trail_race": {
        "name": "50k Trail Race",
        "date": None,  # YYYY-MM-DD
        "distance_km": 50.0,
        "elevation_gain_m": 2000,
        "weekly_km_target": 60.0,
        "weekly_vert_target": 1800,
        "target_carbs_g_per_h": 70,
    },
    "import": {
        "history_start": None,  # ISO date; older provider records are not imported
    },
    "poll_interval_minutes": None,  # 0 = manual only, else 30/60/120/360; None = ROUTEPASS_POLL_INTERVAL_MINUTES
}

_PREFS_KEY = "preferences"


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def get_value(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(Setting, key)
    return default if row is None else row.value


def set_value(db: Session, key: str, value: Any) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def delete_value(db: Session, key: str) -> None:
    row = db.get(Setting, key)
    if row is not None:
        db.delete(row)
        db.flush()


def get_secret(db: Session, key: str) -> dict | None:
    raw = get_value(db, key)
    if not raw:
        return None
    return json.loads(decrypt(raw))


def set_secret(db: Session, key: str, value: dict) -> None:
    set_value(db, key, encrypt(json.dumps(value)))


def get_preferences(db: Session) -> dict:
    return _deep_merge(DEFAULT_PREFERENCES, get_value(db, _PREFS_KEY) or {})


def update_preferences(db: Session, patch: dict) -> dict:
    current = get_value(db, _PREFS_KEY) or {}
    merged = _deep_merge(current, patch)
    set_value(db, _PREFS_KEY, merged)
    return _deep_merge(DEFAULT_PREFERENCES, merged)

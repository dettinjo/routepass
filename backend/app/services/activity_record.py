"""Platform-agnostic activity representation used by the rule engine.

Every source ingestor converts its native model to `ActivityRecord` before
rules are evaluated, so the rule engine never needs to know about Tour,
Garmin activity dicts, or any other source-specific type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ActivityRecord:
    """Normalised representation of a single fitness activity.

    Field names mirror `SyncedActivity` wherever possible to make mapping
    trivial. The `extra` dict holds anything that doesn't fit the common
    schema (e.g. Strava-mapped sport type for a Komoot tour).
    """

    platform: str  # "komoot" | "strava" | "garmin" | "import" | …
    external_id: str  # platform-native ID (string form)
    name: str
    sport_type: str  # source platform sport label
    started_at: datetime
    description: str = ""
    distance_m: float | None = None
    elevation_gain_m: float | None = None
    duration_s: float | None = None
    # Platform-specific overflow:
    #   komoot → {"strava_sport": "VirtualRide"}
    #   garmin  → {"garmin_activity_id": 123456789}
    extra: dict = field(default_factory=dict)

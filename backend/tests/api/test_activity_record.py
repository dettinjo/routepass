"""Tests for the platform-agnostic ActivityRecord and rule-engine helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.activity_record import ActivityRecord
from app.services.sync import (
    _apply_action,
    _garmin_activity_to_record,
    _komoot_tour_to_record,
    _match_condition,
)

UTC = UTC

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _ride_record() -> ActivityRecord:
    return ActivityRecord(
        platform="komoot",
        external_id="tour_001",
        name="Sunday Ride",
        sport_type="e_road_cycling",
        started_at=datetime.now(UTC),
        distance_m=45_000,
        elevation_gain_m=800,
        extra={"strava_sport": "EBikeRide"},
    )


# ── _match_condition ──────────────────────────────────────────────────────────


def test_match_sport_type_is():
    rec = _ride_record()
    assert _match_condition(rec, {"sport_type": {"is": ["e_road_cycling"]}})
    assert not _match_condition(rec, {"sport_type": {"is": ["run", "hike"]}})


def test_match_sport_type_is_not():
    rec = _ride_record()
    assert not _match_condition(rec, {"sport_type": {"is_not": ["e_road_cycling"]}})
    assert _match_condition(rec, {"sport_type": {"is_not": ["hike"]}})


def test_match_sport_legacy_equality():
    rec = _ride_record()
    assert _match_condition(rec, {"sport": "E_Road_Cycling"})  # case-insensitive
    assert not _match_condition(rec, {"sport": "Running"})


def test_match_sport_type_plain_equality():
    rec = _ride_record()
    assert _match_condition(rec, {"sport_type": "e_road_cycling"})
    assert not _match_condition(rec, {"sport_type": "Run"})


def test_match_distance_km_gt():
    rec = _ride_record()
    assert _match_condition(rec, {"distance_km": {"gt": 40}})
    assert not _match_condition(rec, {"distance_km": {"gt": 50}})


def test_match_distance_km_between():
    rec = _ride_record()
    assert _match_condition(rec, {"distance_km": {"between": [40, 50]}})
    assert not _match_condition(rec, {"distance_km": {"between": [50, 100]}})


def test_match_elevation_m():
    rec = _ride_record()
    assert _match_condition(rec, {"elevation_m": {"gt": 500}})
    assert not _match_condition(rec, {"elevation_m": {"gt": 1000}})


def test_match_name_contains():
    rec = _ride_record()
    assert _match_condition(rec, {"name_contains": "sunday"})
    assert not _match_condition(rec, {"name_contains": "monday"})


def test_match_empty_conditions_always_true():
    rec = _ride_record()
    assert _match_condition(rec, {})


# ── _apply_action ──────────────────────────────────────────────────────────────


def test_apply_action_skip():
    rec = _ride_record()
    skip, out, extras = _apply_action(rec, {"skip": True}, user=None)
    assert skip is True


def test_apply_action_sync_to_none():
    rec = _ride_record()
    skip, out, extras = _apply_action(rec, {"sync_to": "None"}, user=None)
    assert skip is True


def test_apply_action_set_sport_type():
    rec = _ride_record()
    skip, out, extras = _apply_action(rec, {"set_sport_type": "VirtualRide"}, user=None)
    assert skip is False
    assert out.extra["strava_sport"] == "VirtualRide"
    # original record is not mutated
    assert rec.extra["strava_sport"] == "EBikeRide"


def test_apply_action_name_template():
    rec = _ride_record()
    skip, out, extras = _apply_action(
        rec, {"name_template": "{name} — {distance:.0f} km"}, user=None
    )
    assert skip is False
    assert out.name == "Sunday Ride — 45 km"
    assert rec.name == "Sunday Ride"  # original unchanged


def test_apply_action_hide_from_home():
    rec = _ride_record()
    skip, out, extras = _apply_action(rec, {"set_hide_from_home": True}, user=None)
    assert skip is False
    assert extras.get("hide_from_home") is True


# ── Platform converters ───────────────────────────────────────────────────────


def test_komoot_tour_to_record():
    from app.services.komoot import Tour

    tour = Tour(
        id="tour_abc",
        name="Alpine Loop",
        description="Tough one",
        sport="cycling",
        strava_sport="Ride",
        date=datetime(2025, 6, 1, 8, 0, tzinfo=UTC),
        distance_m=80_000,
        elevation_up_m=2500,
    )
    rec = _komoot_tour_to_record(tour)

    assert rec.platform == "komoot"
    assert rec.external_id == "tour_abc"
    assert rec.name == "Alpine Loop"
    assert rec.sport_type == "cycling"
    assert rec.extra["strava_sport"] == "Ride"
    assert rec.distance_m == 80_000
    assert rec.elevation_gain_m == 2500


def test_garmin_activity_to_record_full():
    activity = {
        "activityId": 9876543210,
        "activityName": "Morning Run",
        "activityType": {"typeKey": "running"},
        "startTimeLocal": "2025-06-01T07:30:00",
        "distance": 10_000,
        "elevationGain": 150,
        "duration": 3600,
    }
    rec = _garmin_activity_to_record(activity)

    assert rec.platform == "garmin"
    assert rec.external_id == "9876543210"
    assert rec.name == "Morning Run"
    assert rec.sport_type == "running"
    assert rec.distance_m == 10_000
    assert rec.elevation_gain_m == 150
    assert rec.duration_s == 3600
    assert rec.extra["garmin_activity_id"] == 9876543210


def test_garmin_activity_to_record_minimal():
    """Minimal dict (missing optional fields) must not raise."""
    activity = {"activityId": 111}
    rec = _garmin_activity_to_record(activity)

    assert rec.platform == "garmin"
    assert rec.external_id == "111"
    assert rec.name == ""
    assert rec.sport_type == ""
    assert rec.distance_m is None

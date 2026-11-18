from __future__ import annotations

import gzip
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import func, select

from routepass.analysis import track as trk
from routepass.db import session_scope
from routepass.engine import strava_archive
from routepass.models import Activity, ProviderActivity, Track
from routepass.providers.gpx import track_to_gpx
from tests.conftest import AUTH
from tests.test_track import _fixture

FIX = Path(__file__).parent / "fixtures"
HEADER = (
    "Activity ID,Activity Date,Activity Name,Activity Type,Activity Description,Elapsed Time,Distance,"
    "Max Heart Rate,Relative Effort,Commute,Activity Private Note,Activity Gear,Filename,Athlete Weight,"
    "Bike Weight,Elapsed Time,Moving Time,Distance,Max Speed,Average Speed,Elevation Gain,Elevation Loss,"
    "Elevation Low,Elevation High,Max Grade,Average Grade,Max Cadence,Average Cadence,Max Heart Rate,"
    "Average Heart Rate,Max Watts,Average Watts,Calories,Commute"
)


def _row(aid, date, name, kind, km, filename, moving, gain, avg_hr=""):
    return (
        f'{aid},"{date}",{name},{kind},,{moving + 300},"{km:.2f}",,,false,,,{filename},,,{moving + 300},{moving},'
        f"{km * 1000:.1f},,,{gain},,,,,,,,,{avg_hr},,,,false"
    )


def _archive(tmp_path: Path) -> tuple[Path, datetime]:
    half = _fixture("trail_half_marathon")
    track = trk.from_komoot_coordinates(half["items"])
    run_start = datetime(2026, 5, 8, 9, 11, 50)
    gpx = track_to_gpx(track, "Halbmarathon", "Run", run_start)
    fit = (FIX / "garmin_run.fit").read_bytes()
    fit_start = datetime.fromtimestamp(trk.start_epoch(fit, "fit"), UTC).replace(tzinfo=None)
    tcx = (
        b"""<?xml version="1.0"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"><Activities><Activity>
<Lap><Track>"""
        + b"".join(
            f"<Trackpoint><Time>2024-03-0{1}T10:{i // 60:02d}:{i % 60:02d}Z</Time><Position><LatitudeDegrees>{47 + i * 0.0002}"
            f"</LatitudeDegrees><LongitudeDegrees>8.5</LongitudeDegrees></Position><AltitudeMeters>{400 + i}</AltitudeMeters>"
            f"<HeartRateBpm><Value>{120 + i % 30}</Value></HeartRateBpm></Trackpoint>".encode()
            for i in range(0, 600, 5)
        )
        + b"</Track></Lap></Activity></Activities></TrainingCenterDatabase>"
    )
    rows = [
        HEADER,
        _row(
            1001,
            "May 8, 2026, 9:11:50 AM",
            "Halbmarathon",
            "Run",
            20.3,
            "activities/1001.gpx",
            7900,
            571,
            "151.2",
        ),
        _row(
            1002,
            fit_start.strftime("%b %-d, %Y, %-I:%M:%S %p"),
            "Garmin run",
            "Run",
            4.8,
            "activities/1002.fit.gz",
            1700,
            30,
        ),
        _row(
            1003,
            "Mar 1, 2024, 10:00:00 AM",
            "Morning Ride",
            "E-Bike Ride",
            13.3,
            "activities/1003.tcx.gz",
            600,
            120,
        ),
        _row(1004, "Mar 2, 2024, 6:00:00 PM", "Gym", "Weight Training", 0, "", 3600, 0),
    ]
    path = tmp_path / "export_118153039.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("activities.csv", "\n".join(rows) + "\n")
        zf.writestr("activities/1001.gpx", gpx)
        zf.writestr("activities/1002.fit.gz", gzip.compress(fit))
        zf.writestr(
            "activities/1003.tcx.gz", gzip.compress(b"  \n" + tcx)
        )  # Strava TCX often has leading space
        zf.writestr("media/photo.jpg", b"x" * 100)
    return path, run_start


def test_archive_import_merges_with_komoot(client, connected, mock_apis, tmp_path):
    from routepass.engine import runner
    from tests.conftest import komoot_tour
    from tests.test_flow import _komoot_list

    # Komoot already has the half marathon (start within a minute)
    _komoot_list(
        mock_apis,
        [{**komoot_tour(555, datetime(2026, 5, 8, 9, 12, 30, tzinfo=UTC), km=20.3, sport="jogging")}],
    )
    mock_apis.get("https://www.strava.com/api/v3/athlete/activities").mock(
        return_value=httpx.Response(403, json={"errors": [{"resource": "Application", "code": "Inactive"}]})
    )
    runner.run_cycle("test", tracks=False)

    path, _ = _archive(tmp_path)
    result = strava_archive.import_archive(path)
    assert result["phase"] == "finished", result
    assert result["new"] == 4 and result["tracks"] == 3

    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Activity)) == 4  # 4 Strava + 1 Komoot, one merged
        half = db.scalar(select(ProviderActivity).where(ProviderActivity.external_id == "1001"))
        act = db.get(Activity, half.activity_id)
        assert {s.provider for s in act.sources} == {"strava", "komoot"}
        assert act.sport == "Run" and act.avg_hr == 151.2 and db.get(Track, act.id).provider == "strava"
        ebike = db.scalar(
            select(Activity).join(ProviderActivity).where(ProviderActivity.external_id == "1003")
        )
        assert ebike.sport == "EBikeRide" and ebike.has_track and ebike.avg_hr is not None
        fit_act = db.scalar(
            select(Activity).join(ProviderActivity).where(ProviderActivity.external_id == "1002")
        )
        assert fit_act.has_track and 4000 < fit_act.distance_m < 5600
        gym = db.scalar(select(Activity).join(ProviderActivity).where(ProviderActivity.external_id == "1004"))
        assert gym.sport == "WeightTraining" and not gym.has_track

    # Importing the same archive again updates instead of duplicating
    assert strava_archive.import_archive(path)["updated"] == 4
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Activity)) == 4

    # Status shows the blocked Strava API, and the API lists the archive
    st = client.get("/api/v1/import/strava-archive", headers=AUTH).json()
    assert st["phase"] == "finished"


def test_archive_upload_endpoint_rejects_non_zip(client):
    r = client.post("/api/v1/import/strava-archive", content=b"not a zip", headers=AUTH)
    assert r.status_code == 422


def test_sport_labels():
    assert strava_archive.sport_from_label("E-Mountain Bike Ride") == "EMountainBikeRide"
    assert strava_archive.sport_from_label("Rock Climb") == "RockClimbing"
    assert strava_archive.sport_from_label("Radfahrt") == "Ride"
    assert strava_archive.sport_from_label("Backcountry Ski") == "BackcountrySki"
    assert strava_archive.sport_from_label("Something new") == "Workout"

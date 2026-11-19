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


def test_parse_web_cookies_formats():
    from routepass.providers import strava

    assert strava.parse_web_cookies("abc123session") == {"_strava4_session": "abc123session"}
    assert strava.parse_web_cookies("Cookie: _strava4_session=s1; strava_remember_token=r1; other=2") == {
        "_strava4_session": "s1",
        "strava_remember_token": "r1",
        "other": "2",
    }
    assert strava.parse_web_cookies('{"_strava4_session": "s2"}', remember_token="r2") == {
        "_strava4_session": "s2",
        "strava_remember_token": "r2",
    }
    assert strava.parse_web_cookies(
        "curl 'https://www.strava.com/dashboard' -H 'accept: text/html' -b '_strava4_session=s3; strava_remember_token=r3'"
    ) == {"_strava4_session": "s3", "strava_remember_token": "r3"}
    assert strava.parse_web_cookies(
        "GET /dashboard HTTP/2\nHost: www.strava.com\nCookie: _strava4_session=s4; strava_remember_token=r4\n"
    ) == {"_strava4_session": "s4", "strava_remember_token": "r4"}
    assert strava.parse_web_cookies("_strava4_session\ts5\t.strava.com\t/\t2027-01-01") == {
        "_strava4_session": "s5"
    }


def test_strava_web_session_bidirectional_sync(client, mock_apis):
    import re
    from datetime import timedelta

    from routepass import store
    from routepass.engine import runner
    from routepass.models import SyncJob
    from tests.conftest import T0, coords, komoot_tour, streams
    from tests.test_flow import KOMOOT, _komoot_list

    with session_scope() as db:
        store.set_secret(db, "komoot.credentials", {"email": "e@x", "password": "p", "user_id": "42"})
        store.set_value(db, "komoot.account", {"user_id": "42", "display_name": "Joel"})
        store.update_preferences(
            db,
            {
                "sync": {
                    "delay_minutes": 0,
                    "strava_to_komoot": {"enabled": True, "default_action": "sync"},
                    "komoot_to_strava": {"enabled": True, "default_action": "sync"},
                }
            },
        )

    dashboard_html = """
    <html><head><meta name="csrf-token" content="csrf-tok-999" /></head>
    <body>
      <script>window.currentAthlete = {"id": 118153039, "display_name": "Joel Dettinger"};</script>
      <a href="/athletes/118153039">Profile</a>
    </body></html>
    """
    mock_apis.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(
            200, text=dashboard_html, headers={"Set-Cookie": "_strava4_session=rotated123; Path=/"}
        )
    )

    # 1) Connect Strava via web session endpoint (no OAuth tokens needed)
    res = client.put(
        "/api/v1/connections/strava/session",
        json={"cookie": "_strava4_session=initial123", "remember_token": "rem456"},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    assert res.json()["athlete"]["id"] == 118153039

    st = client.get("/api/v1/status", headers=AUTH).json()
    assert st["connections"]["strava"]["connected"] is True
    assert st["connections"]["strava"]["mode"] == "web"

    # 2) Mock Strava web training log (page 1 has 1 outdoor gravel ride + 1 indoor ride; page 2 empty)
    t_ride = T0 - timedelta(days=2)
    t_hike = T0 - timedelta(days=1)

    def _training_log(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        if page > 1:
            return httpx.Response(200, json={"models": [], "total": 2})
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "id": 7001,
                        "name": "Catalonia Gravel",
                        "display_type": "Gravel Ride",
                        "start_date_local_raw": int(t_ride.timestamp()),
                        "distance_raw": 30000.0,
                        "moving_time_raw": 3600,
                        "elapsed_time_raw": 3750,
                        "elevation_gain_raw": 480.0,
                        "average_heartrate": 148.0,
                        "average_watts": 215.0,
                        "trainer": False,
                        "commute": False,
                    },
                    {
                        "id": 7002,
                        "name": "Indoor Zwift",
                        "display_type": "Virtual Ride",
                        "start_date_local_raw": int((t_ride - timedelta(hours=5)).timestamp()),
                        "distance_raw": 20000.0,
                        "moving_time_raw": 2400,
                        "trainer": True,
                    },
                ],
                "total": 2,
            },
        )

    mock_apis.get("https://www.strava.com/athlete/training_activities").mock(side_effect=_training_log)

    # Strava web streams returns raw arrays per stream type
    raw_streams = {s["type"]: s["data"] for s in streams(600)}
    mock_apis.get(re.compile(r"https://www\.strava\.com/activities/\d+/streams.*")).mock(
        return_value=httpx.Response(200, json=raw_streams)
    )

    # Komoot has 1 hike that is not on Strava yet, and accepts uploads from Strava
    gpx_sample = track_to_gpx(
        trk.from_komoot_coordinates(coords()["items"]), "Mountain Hike", "Hike", t_hike.replace(tzinfo=None)
    )
    _komoot_list(mock_apis, [komoot_tour(8001, t_hike, km=12.5, sport="hike")])
    mock_apis.get(f"{KOMOOT}/tours/8001.gpx").mock(return_value=httpx.Response(200, content=gpx_sample))
    mock_apis.get(f"{KOMOOT}/tours/8001/coordinates").mock(return_value=httpx.Response(200, json=coords()))
    mock_apis.post(f"{KOMOOT}/tours/").mock(return_value=httpx.Response(201, json={"id": 8099}))
    mock_apis.patch(f"{KOMOOT}/tours/8099").mock(return_value=httpx.Response(200, json={"id": 8099}))

    # Strava web upload endpoints for Komoot → Strava
    mock_apis.post("https://www.strava.com/upload/files").mock(
        return_value=httpx.Response(200, json=[{"id": 5001, "workflow": "Queued"}])
    )
    mock_apis.get("https://www.strava.com/upload/progress").mock(
        return_value=httpx.Response(200, json={"progress": [{"id": 5001, "activity_id": 7099}]})
    )
    mock_apis.patch("https://www.strava.com/activities/7099").mock(
        return_value=httpx.Response(200, json={"id": 7099, "name": "Synced Hike"})
    )

    result = runner.run_cycle("test", tracks=True)
    assert result["status"] == "ok", result

    with session_scope() as db:
        jobs = db.scalars(select(SyncJob).order_by(SyncJob.direction)).all()
        by_dir = {j.direction: j for j in jobs}
        assert "strava_to_komoot" in by_dir
        assert by_dir["strava_to_komoot"].status == "done"
        assert by_dir["strava_to_komoot"].target_id == "8099"

        assert "komoot_to_strava" in by_dir
        assert by_dir["komoot_to_strava"].status == "done"
        assert by_dir["komoot_to_strava"].target_id == "7099"


def test_strava_oauth_inactive_falls_back_to_web_session(client, connected, mock_apis):
    from routepass import store
    from routepass.engine import runner
    from tests.conftest import T0
    from tests.test_flow import _komoot_list

    # Both OAuth tokens (from `connected` fixture) AND web session are present
    with session_scope() as db:
        store.set_secret(db, "strava.web_session", {"cookies": {"_strava4_session": "fallback123"}})

    # OAuth v3 API fails with 403 Application Inactive
    mock_apis.get("https://www.strava.com/api/v3/athlete/activities").mock(
        return_value=httpx.Response(403, json={"errors": [{"resource": "Application", "code": "Inactive"}]})
    )
    # Web session succeeds
    mock_apis.get("https://www.strava.com/athlete/training_activities").mock(
        return_value=httpx.Response(
            200,
            json={
                "models": [
                    {
                        "id": 9101,
                        "name": "Fallback Run",
                        "display_type": "Run",
                        "start_date_local_raw": int(T0.timestamp()),
                        "distance_raw": 10000.0,
                        "moving_time_raw": 2500,
                        "elevation_gain_raw": 110.0,
                    }
                ]
            },
        )
    )
    _komoot_list(mock_apis, [])

    res = runner.run_cycle("test", tracks=False)
    assert res["status"] == "ok", res
    assert res["stats"]["import_strava"]["new"] == 1


def test_instant_poll_interval_preference(client) -> None:
    """Option 3: poll_interval_minutes can be lowered to 1 minute and wakes the scheduler."""
    from routepass.engine import runner

    runner._wake.clear()
    r = client.patch(
        "/api/v1/settings",
        json={"poll_interval_minutes": 1, "sync": {"delay_minutes": 0}},
        headers=AUTH,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["poll_interval_minutes"] == 1
    assert body["sync"]["delay_minutes"] == 0
    assert runner._interval_s() == 60.0
    assert runner._wake.is_set()


def test_strava_remember_token_auto_renews_expired_session(mock_apis) -> None:
    """When _strava4_session expires, StravaWebClient uses strava_remember_token to mint a new session cookie."""
    from routepass.providers import strava

    refreshed: list[dict[str, str]] = []
    calls = {"training": 0}

    def training_handler(request: httpx.Request) -> httpx.Response:
        calls["training"] += 1
        cookie_hdr = request.headers.get("cookie", "")
        if "renewed-session-cookie" not in cookie_hdr:
            return httpx.Response(302, headers={"Location": "https://www.strava.com/login"})
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "id": 9901,
                        "name": "Auto Renewed Ride",
                        "sport_type": "Ride",
                        "start_date_local_raw": 1778231510,
                        "distance_raw": 15000.0,
                        "moving_time_raw": 1800,
                        "elevation_gain_raw": 120.0,
                    }
                ]
            },
        )

    mock_apis.get("https://www.strava.com/athlete/training_activities").mock(side_effect=training_handler)
    mock_apis.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(
            200,
            text='<html><head><meta name="csrf-token" content="csrf-renewed" /></head>'
            '<body><a href="/athletes/77777">Jonathan</a></body></html>',
            headers={"Set-Cookie": "_strava4_session=renewed-session-cookie; Path=/; HttpOnly"},
        )
    )

    with strava.StravaWebClient(
        {"_strava4_session": "expired-cookie", "strava_remember_token": "long-lived-remember"},
        on_refresh=lambda c: refreshed.append(c),
    ) as web_client:
        items = web_client.list_activities(page=1, per_page=20)
        assert len(items) == 1
        assert items[0]["id"] == 9901
        assert web_client.cookies["_strava4_session"] == "renewed-session-cookie"

    assert calls["training"] == 2
    assert refreshed and refreshed[-1]["_strava4_session"] == "renewed-session-cookie"


def test_strava_userscript_and_session_handoff(client, mock_apis) -> None:
    """Option 1: 1-click userscript download and scoped HMAC session handoff work end-to-end."""
    import re

    r = client.get("/api/v1/connections/strava/userscript.user.js", headers=AUTH)
    assert r.status_code == 200
    script = r.text
    assert "// ==UserScript==" in script
    assert "GM_cookie" in script
    assert "/api/v1/connections/strava/session/handoff" in script

    m = re.search(r'const HANDOFF_TOKEN = "([^"]+)";', script)
    assert m, "handoff token missing from userscript"
    token = m.group(1)

    # Invalid token is rejected
    bad = client.post(
        "/api/v1/connections/strava/session/handoff",
        json={"token": "invalid.token", "cookies": {"_strava4_session": "abc"}},
    )
    assert bad.status_code == 401

    # Valid scoped token connects Strava without needing the master API token
    mock_apis.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(
            200,
            text='<html><head><meta name="csrf-token" content="csrf-u1" /></head>'
            '<body><a href="/athletes/88888">Jonathan</a></body></html>',
        )
    )
    ok = client.post(
        "/api/v1/connections/strava/session/handoff",
        json={
            "token": token,
            "cookies": {
                "_strava4_session": "userscript-session-val",
                "strava_remember_token": "userscript-remember-val",
            },
        },
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["ok"] is True
    assert body["has_remember_token"] is True
    assert body["athlete"]["id"] == 88888

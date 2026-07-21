from __future__ import annotations

import numpy as np
import pytest

from app.services import metrics as m


def _constant_ride_streams(n=600, speed=5.0, hr=150, power=200, climb=100.0):
    """A synthetic 1 Hz ride: constant speed, HR, power; climbs `climb` m over the
    first half then descends the same amount."""
    t = list(range(n))
    dist = [speed * i for i in range(n)]
    half = n // 2
    ele = [400 + climb * (i / half) for i in range(half)] + [
        400 + climb * (1 - (i - half) / (n - half)) for i in range(half, n)
    ]
    # latlng roughly consistent with the distance (~5 m/point east)
    lat = [47.0 for _ in range(n)]
    lon = [8.0 + i * 5.0 / 111_320 for i in range(n)]
    return {
        "time": {"data": t},
        "distance": {"data": dist},
        "altitude": {"data": ele},
        "heartrate": {"data": [hr] * n},
        "watts": {"data": [power] * n},
        "cadence": {"data": [85] * n},
        "temp": {"data": [20] * n},
        "latlng": {"data": [[la, lo] for la, lo in zip(lat, lon)]},
    }


def test_normalize_strava_streams_channels():
    track = m.normalize_strava_streams(_constant_ride_streams(n=100))
    assert track is not None
    assert track.n == 100
    assert track.hr is not None and track.power is not None
    assert track.distance_m is not None
    assert track.elevation_m is not None


def test_compute_metrics_constant_ride():
    track = m.normalize_strava_streams(_constant_ride_streams(n=600, speed=5.0))
    res = m.compute_metrics(track, sport_type="cycling", ftp=200, hr_max=190)

    s = res.summary
    # distance = 5 m/s * 599 s
    assert s["distance_m"] == pytest.approx(2995, abs=1)
    assert s["moving_time_s"] == pytest.approx(599, abs=2)
    assert s["avg_speed_ms"] == pytest.approx(5.0, abs=0.05)
    assert s["avg_hr"] == pytest.approx(150, abs=0.5)
    assert s["avg_power"] == pytest.approx(200, abs=0.5)
    # constant power → NP ≈ avg power
    assert s["normalized_power"] == pytest.approx(200, abs=2)
    assert s["intensity_factor"] == pytest.approx(1.0, abs=0.02)
    # work = 200 W * 599 s / 1000 ≈ 120 kJ ; calories default to kJ
    assert s["work_kj"] == pytest.approx(119.8, abs=1)
    assert s["calories"] == pytest.approx(120, abs=2)
    # ~100 m up, ~100 m down
    assert s["elevation_gain_m"] == pytest.approx(100, abs=4)
    assert s["elevation_loss_m"] == pytest.approx(100, abs=4)

    assert "distance" in res.available
    assert "power" in res.available
    assert "heartrate" in res.available


def test_hr_and_power_zones_present():
    track = m.normalize_strava_streams(_constant_ride_streams(n=600, hr=150, power=200))
    res = m.compute_metrics(track, ftp=200, hr_max=200)
    hz = res.detail["hr_zones"]
    assert len(hz["seconds"]) == 5  # 4 bounds → 5 zones
    # HR 150 vs max 200 = 75% → falls in Z3 (70-80%)
    assert hz["seconds"][2] > 0
    pz = res.detail["power_zones"]
    assert len(pz["seconds"]) == 7
    # power 200 == FTP → 100% → Z4 (90-105%)
    assert pz["seconds"][3] > 0


def test_splits_per_km():
    track = m.normalize_strava_streams(_constant_ride_streams(n=600, speed=5.0))
    res = m.compute_metrics(track)
    splits = res.detail["splits"]
    # ~2995 m → 2 full km + a partial
    assert len(splits) >= 2
    assert splits[0]["distance_m"] == pytest.approx(1000, abs=10)
    assert splits[0]["duration_s"] == pytest.approx(200, abs=3)  # 1000m / 5 m/s


def test_downsample_preserves_endpoints_and_caps():
    track = m.normalize_strava_streams(_constant_ride_streams(n=5000))
    res = m.compute_metrics(track)
    pts = res.track_points
    assert len(pts) <= m._MAX_TRACK_POINTS
    assert len(pts) >= 3
    assert pts[0]["t"] == 0.0
    assert pts[-1]["t"] == pytest.approx(4999, abs=1)


def test_lttb_returns_all_when_small():
    x = np.arange(10, dtype="float64")
    y = np.arange(10, dtype="float64")
    idx = m._lttb_indices(x, y, 100)
    assert idx.shape[0] == 10


def test_parse_gpx_with_extensions():
    gpx = b"""<?xml version="1.0"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
  <trk><trkseg>
    <trkpt lat="47.0" lon="8.0"><ele>400</ele><time>2026-07-21T10:00:00Z</time>
      <extensions><gpxtpx:TrackPointExtension>
        <gpxtpx:hr>140</gpxtpx:hr><gpxtpx:cad>80</gpxtpx:cad><gpxtpx:atemp>19</gpxtpx:atemp>
      </gpxtpx:TrackPointExtension></extensions>
    </trkpt>
    <trkpt lat="47.001" lon="8.001"><ele>410</ele><time>2026-07-21T10:00:30Z</time>
      <extensions><gpxtpx:TrackPointExtension>
        <gpxtpx:hr>150</gpxtpx:hr><gpxtpx:cad>82</gpxtpx:cad><gpxtpx:atemp>19</gpxtpx:atemp>
      </gpxtpx:TrackPointExtension></extensions>
    </trkpt>
    <trkpt lat="47.002" lon="8.002"><ele>420</ele><time>2026-07-21T10:01:00Z</time>
      <extensions><gpxtpx:TrackPointExtension>
        <gpxtpx:hr>160</gpxtpx:hr>
      </gpxtpx:TrackPointExtension></extensions>
    </trkpt>
  </trkseg></trk>
</gpx>"""
    track = m.parse_gpx(gpx)
    assert track is not None
    assert track.n == 3
    assert track.hr is not None
    assert np.nanmean(track.hr) == pytest.approx(150, abs=1)
    assert track.cadence is not None
    assert track.temp is not None
    assert track.distance_m is not None and track.distance_m[-1] > 0
    # time from ISO timestamps: 0, 30, 60 s
    assert track.time_s[-1] == pytest.approx(60, abs=1)


def test_parse_gpx_invalid_returns_none():
    assert m.parse_gpx(b"not xml at all") is None


def test_empty_track_is_safe():
    track = m.NormalizedTrack(time_s=np.array([0.0]))
    res = m.compute_metrics(track)
    assert res.summary == {}
    assert res.track_points == []


def test_route_without_biometrics_degrades():
    """A Komoot-style route: lat/lon/ele/time only → distance+elevation, no HR/power."""
    n = 200
    streams = {
        "time": {"data": list(range(n))},
        "distance": {"data": [4.0 * i for i in range(n)]},
        "altitude": {"data": [400 + i * 0.5 for i in range(n)]},
        "latlng": {"data": [[47.0, 8.0 + i * 4 / 111_320] for i in range(n)]},
    }
    track = m.normalize_strava_streams(streams)
    res = m.compute_metrics(track)
    assert "distance" in res.available
    assert "elevation" in res.available
    assert "power" not in res.available
    assert "heartrate" not in res.available
    assert "avg_hr" not in res.summary

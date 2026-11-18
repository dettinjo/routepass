from __future__ import annotations

import numpy as np

from routepass.analysis import track as trk
from routepass.engine.rules import template_fields
from routepass.providers.gpx import decode_polyline, encode_polyline, track_to_gpx
from tests.conftest import T0


def _ride(n: int = 3600) -> trk.NormalizedTrack:
    t = np.arange(n, dtype=float)
    lat = 47 + np.arange(n) * 0.00007
    lon = np.full(n, 8.0)
    ele = 400 + 400 * np.sin(np.linspace(0, np.pi, n))
    return trk.NormalizedTrack(
        time_s=t,
        lat=lat,
        lon=lon,
        elevation_m=ele,
        distance_m=trk.haversine_cumulative(lat, lon),
        hr=np.full(n, 150.0),
        power=np.full(n, 200.0),
    )


def test_compute_summary_and_efforts():
    r = trk.compute(_ride(), family="ride", ftp=250, hr_max=190)
    s = r.summary
    assert 27_000 < s["distance_m"] < 29_000
    assert 390 < s["elevation_gain_m"] < 410
    assert s["load_method"] == "power" and 60 < s["load"] < 70  # 1 h at IF 0.8 = 64
    assert r.detail["power_curve"][60] == 200
    assert 5000 in r.detail["best_times"]
    assert r.detail["climbs"] and r.detail["climbs"][0]["gain_m"] >= 390
    assert len(r.points) <= trk.CHART_POINTS


def test_pack_roundtrip_and_gpx():
    tr = _ride(500)
    back = trk.NormalizedTrack.unpack(tr.pack())
    assert back.n == 500 and back.hr is not None
    gpx = track_to_gpx(back, "A & B", "Ride", T0.replace(tzinfo=None))
    parsed = trk.from_gpx(gpx)
    assert parsed.n == 500 and parsed.hr is not None and b"A &amp; B" in gpx


def test_load_fallbacks():
    assert (
        trk.compute_load(
            family="run", moving_s=3600, np_power=None, avg_hr=None, ftp=None, hr_max=None, hr_rest=None
        )[1]
        == "estimate"
    )
    assert (
        trk.compute_load(
            family="run", moving_s=3600, np_power=None, avg_hr=150, ftp=None, hr_max=190, hr_rest=50
        )[1]
        == "heartrate"
    )


def test_polyline_roundtrip():
    pts = [(47.1, 8.2), (47.10005, 8.20012), (46.9, 8.5)]
    back = decode_polyline(encode_polyline(pts))
    assert all(abs(a[0] - b[0]) < 1e-5 and abs(a[1] - b[1]) < 1e-5 for a, b in zip(pts, back, strict=True))


def test_template_fields():
    from routepass.models import Activity

    act = Activity(
        name="Loop",
        sport="Ride",
        family="ride",
        start_time=T0.replace(tzinfo=None),
        distance_m=42195,
        moving_time_s=5400,
        elevation_gain_m=321,
    )
    f = template_fields(act, "strava")
    assert "{name} {distance_km:.1f} km {moving_time}".format_map(f) == "Loop 42.2 km 1:30"


def test_pack_preserves_gaps_and_precision():
    tr = _ride(300)
    tr.hr[10:20] = np.nan
    tr.hr[0] = np.nan
    back = trk.NormalizedTrack.unpack(tr.pack())
    assert np.isnan(back.hr[0]) and np.isnan(back.hr[15]) and back.hr[25] == 150
    assert np.allclose(back.lat, tr.lat, atol=1e-6)
    assert np.allclose(back.elevation_m, tr.elevation_m, atol=0.06)
    pts = trk.compute(tr, family="ride").points
    assert trk.unpack_points(trk.pack_points(pts)) == pts


def _fixture(name: str) -> dict:
    import gzip
    import json
    from pathlib import Path

    with gzip.open(Path(__file__).parent / "fixtures" / f"{name}.json.gz", "rt") as f:
        return json.load(f)


def _close(actual: float, expected: float, pct: float) -> bool:
    return abs(actual - expected) <= expected * pct / 100


def test_real_trail_half_marathon_matches_komoot():
    """Recorded Komoot tour (coordinates anonymised by a longitude shift)."""
    fx = _fixture("trail_half_marathon")
    k = fx["komoot"]
    r = trk.compute(trk.from_komoot_coordinates(fx["items"]), family="run")
    s = r.summary
    assert _close(s["distance_m"], k["distance"], 2)
    assert _close(s["elevation_gain_m"], k["elevation_up"], 6)
    assert _close(s["moving_time_s"], k["time_in_motion"], 5)
    assert abs(s["elapsed_time_s"] - k["duration"]) <= 2
    # best efforts stay physically plausible (no GPS-jump records)
    assert all(d / t <= trk.MAX_EFFORT_SPEED_MS["run"] for d, t in r.detail["best_times"].items())
    assert r.detail["climbs"]


def test_real_ski_tour_counts_slow_climbing_as_moving():
    fx = _fixture("ski_tour")
    k = fx["komoot"]
    r = trk.compute(trk.from_komoot_coordinates(fx["items"]), family="winter")
    s = r.summary
    assert _close(s["elevation_gain_m"], k["elevation_up"], 3)
    assert _close(s["elevation_loss_m"], k["elevation_down"], 3)
    assert _close(s["moving_time_s"], k["time_in_motion"], 12)
    assert r.detail["climbs"][0]["gain_m"] > 450


def test_komoot_sport_mapping():
    from routepass.providers import sports

    assert sports.komoot_to_strava("mountaineering") == "Hike"
    assert sports.komoot_to_strava("skitour") == "BackcountrySki"
    assert sports.komoot_to_strava("mtb_easy") == "GravelRide"
    assert sports.komoot_to_strava("touringbike") == "Ride"  # legacy alias
    assert sports.family(sports.komoot_to_strava("jogging")) == "run"


def test_every_sport_maps_to_a_valid_sport_on_the_other_platform():
    from routepass.providers import sports

    for strava_type, (_, fam, komoot_id) in sports.STRAVA.items():
        assert komoot_id in sports.KOMOOT, strava_type
        assert fam in ("ride", "run", "walk", "winter", "water", "other")
    for komoot_id, (_, strava_type) in sports.KOMOOT.items():
        assert strava_type in sports.STRAVA, komoot_id
    for alias, target in sports.KOMOOT_ALIASES.items():
        assert target in sports.KOMOOT, alias
    # a round trip keeps the family for every Komoot sport that has a real counterpart
    for komoot_id in sports.KOMOOT:
        strava_type = sports.komoot_to_strava(komoot_id)
        back = sports.strava_to_komoot(strava_type)
        if komoot_id not in ("other", "sled", "unicycle"):
            assert sports.family(sports.komoot_to_strava(back)) == sports.family(strava_type), komoot_id
    # Komoot's full recordable list (from its web app, Nov 2026)
    assert set(sports.KOMOOT) == {
        "hike",
        "touringbicycle",
        "mtb",
        "racebike",
        "jogging",
        "mtb_easy",
        "mtb_advanced",
        "mountaineering",
        "e_touringbicycle",
        "e_mtb",
        "e_racebike",
        "e_mtb_easy",
        "e_mtb_advanced",
        "climbing",
        "downhillbike",
        "unicycle",
        "nordic",
        "nordicwalking",
        "skaten",
        "skialpin",
        "skitour",
        "sled",
        "snowboard",
        "snowshoe",
        "other",
    }


def test_malformed_polyline_does_not_raise():
    assert decode_polyline("abc") == []

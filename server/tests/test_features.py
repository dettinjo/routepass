from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

import httpx

from routepass import store
from routepass.db import session_scope
from routepass.engine import rules as rule_engine
from routepass.engine import runner
from routepass.models import Activity, ProviderActivity, Track
from routepass.providers.gpx import encode_polyline
from tests.conftest import AUTH, T0, days, komoot_tour, strava_activity
from tests.test_flow import _komoot_list


def _activity(
    db, start, *, family="ride", sport="Ride", km=30.0, poly=None, hr=None, provider=None, ext=None, **kw
):
    act = Activity(
        start_time=start,
        name=kw.pop("name", "A"),
        sport=sport,
        family=family,
        distance_m=km * 1000,
        moving_time_s=3600,
        polyline=poly,
        avg_hr=hr,
        avg_speed_ms=km * 1000 / 3600,
        **kw,
    )
    db.add(act)
    db.flush()
    if provider:
        db.add(
            ProviderActivity(
                provider=provider,
                external_id=ext or str(act.id),
                activity_id=act.id,
                name=act.name,
                sport=sport,
                start_time=start,
                distance_m=act.distance_m,
            )
        )
    return act


def test_explorer_tiles_square_and_new_by_year(client):
    # a 3x3 grid of zoom-14 tiles around (47.0, 8.0): tile size ≈ 0.022° lon, 0.015° lat
    lines = []
    for row in range(3):
        lat = 47.0 + row * 0.0145
        lines.append([(lat, 8.0 + i * 0.0035) for i in range(20)])  # west→east across 3 tiles
    with session_scope() as db:
        for i, pts in enumerate(lines):
            _activity(db, datetime(2025 + (i == 2), 5, 1 + i), poly=encode_polyline(pts))
    t = client.get("/api/v1/insights/tiles", headers=AUTH).json()
    assert t["total_tiles"] >= 9 and t["max_square"] >= 3
    assert sum(t["new_by_year"].values()) == t["total_tiles"] and set(t["new_by_year"]) == {"2025", "2026"}


def test_zones_efficiency_goals_gear(client):
    with session_scope() as db:
        a = _activity(db, T0.replace(tzinfo=None), hr=140, gear="b1")
        db.add(
            Track(
                activity_id=a.id,
                provider="strava",
                data=b"",
                detail={
                    "hr_zones": {"seconds": [600, 1200, 1200, 400, 200]},
                    "decoupling": {"pct": 3.1},
                },
            )
        )
        _activity(db, T0.replace(tzinfo=None) + days(2), hr=145, gear="b1")
        store.update_preferences(
            db,
            {
                "goals": {"yearly_distance_km": 1000},
                "gear_targets": {"b1": {"label": "Road bike", "service_km": 50}},
            },
        )
    z = client.get("/api/v1/insights/zones", headers=AUTH).json()
    assert z["hr"]["total_s"] == 3600 and z["hr"]["polarization"]["low_pct"] == 50.0
    eff = client.get("/api/v1/insights/efficiency", headers=AUTH).json()
    assert len(eff) == 2 and eff[0]["ef_speed"] > 0 and eff[0]["decoupling_pct"] == 3.1
    goals = client.get("/api/v1/insights/goals", headers=AUTH).json()
    assert goals and goals[0]["key"] == "yearly_distance_km" and goals[0]["target"] == 1000
    gear = client.get("/api/v1/insights/gear", headers=AUTH).json()["gear"][0]
    assert gear["label"] == "Road bike" and gear["count"] == 2 and gear["service_due"] is True


def test_duplicate_candidates_and_dismiss(client):
    with session_scope() as db:
        s = _activity(db, datetime(2026, 6, 1, 8), provider="strava", ext="11", name="Ride (Strava)")
        k = _activity(
            db, datetime(2026, 6, 1, 8, 40), km=31, provider="komoot", ext="22", name="Ride (Komoot)"
        )
        _activity(
            db, datetime(2026, 6, 1, 9), family="run", sport="Run", provider="komoot", ext="33"
        )  # other sport
        ids = (s.id, k.id)
    cands = client.get("/api/v1/activities/duplicates", headers=AUTH).json()
    assert len(cands) == 1 and {cands[0]["activity"]["id"], cands[0]["candidate"]["id"]} == set(ids)
    assert cands[0]["time_diff_min"] == 40.0
    client.post(f"/api/v1/activities/{ids[0]}/dismiss-duplicate", json={"other_id": ids[1]}, headers=AUTH)
    assert client.get("/api/v1/activities/duplicates", headers=AUTH).json() == []


def test_csv_export_contains_every_activity(client, connected, mock_apis):
    acts = [strava_activity(i, T0 + timedelta(hours=i), km=5 + i % 7) for i in range(1, 260)]
    mock_apis.get("https://www.strava.com/api/v3/athlete/activities").mock(
        side_effect=lambda req: httpx.Response(
            200, json=acts[:200] if req.url.params["page"] == "1" else acts[200:]
        )
    )
    _komoot_list(mock_apis, [komoot_tour(9000, T0 + timedelta(hours=1), km=6)])
    runner.run_cycle("test", tracks=False)
    with session_scope() as db:
        for i in range(600):
            _activity(db, datetime(2020, 1, 1) + timedelta(hours=i))
    r = client.get("/api/v1/activities/export.csv", headers=AUTH)
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert r.headers["content-type"].startswith("text/csv") and len(rows) == 859
    both = next(row for row in rows if row["strava_id"] == "1")
    assert both["komoot_id"] == "9000" and both["strava_url"].endswith("/activities/1")


def test_geofence_rule_with_saved_place():
    places = [{"name": "Home", "lat": 47.0, "lng": 8.0, "radius_km": 0.5}]
    home = Activity(
        start_lat=47.001,
        start_lng=8.001,
        end_lat=47.2,
        end_lng=8.2,
        family="ride",
        sport="Ride",
        start_time=datetime(2026, 1, 1),
        distance_m=1000,
    )
    away = Activity(
        start_lat=47.1, start_lng=8.1, family="ride", sport="Ride", start_time=datetime(2026, 1, 1)
    )
    cond = {"start_near": {"place": "home"}}
    assert rule_engine.matches(cond, home, places) and not rule_engine.matches(cond, away, places)
    assert not rule_engine.matches({"start_near": {"place": "Office"}}, home, places)  # unknown place
    assert rule_engine.matches({"end_near": {"lat": 47.2, "lng": 8.2, "radius_km": 1}}, home, places)
    rule_engine.validate("strava_to_komoot", cond, {"skip": True})
    try:
        rule_engine.validate("strava_to_komoot", {"start_near": {"radius_km": 1}}, {})
        raise AssertionError("expected RuleError")
    except rule_engine.RuleError:
        pass

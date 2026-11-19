from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

import httpx
from sqlalchemy import func

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


def test_rule_dry_run_counts_matches_and_earlier_rules(client):
    with session_scope() as db:
        for i, (sport, fam, km) in enumerate(
            [("Ride", "ride", 40), ("Ride", "ride", 5), ("Run", "run", 10), ("VirtualRide", "ride", 30)]
        ):
            _activity(db, datetime(2026, 5, 1 + i, 8), sport=sport, family=fam, km=km, provider="komoot")
    body = {"direction": "komoot_to_strava", "conditions": {"families": ["ride"]}}
    r = client.post("/api/v1/rules/test", json=body, headers=AUTH).json()
    assert (r["considered"], r["matched"], r["effective"]) == (4, 3, 3)
    assert len(r["samples"]) == 3 and r["shadowed_by"] == []

    # An earlier rule that catches indoor rides takes one of them (first match wins).
    first = client.post(
        "/api/v1/rules",
        json={
            "name": "Indoor",
            "direction": "komoot_to_strava",
            "conditions": {"sports": ["VirtualRide"]},
            "actions": {"skip": True},
        },
        headers=AUTH,
    ).json()
    r = client.post("/api/v1/rules/test", json=body, headers=AUTH).json()
    assert r["matched"] == 3 and r["effective"] == 2
    assert r["shadowed_by"] == [{"rule_id": first["id"], "name": "Indoor", "count": 1}]
    # Testing the first rule itself: nothing is ahead of it.
    r = client.post(
        "/api/v1/rules/test",
        json={**body, "conditions": {"sports": ["VirtualRide"]}, "rule_id": first["id"]},
        headers=AUTH,
    ).json()
    assert r["effective"] == 1

    bad = client.post(
        "/api/v1/rules/test", json={"direction": "komoot_to_strava", "conditions": {"nope": 1}}, headers=AUTH
    )
    assert bad.status_code == 422


def test_merged_records_stay_merged_after_the_next_sync(client):
    """Regression: merging left the moved records unlinked, so the next sync split them off again."""
    from sqlalchemy import select

    from routepass.engine import ingest

    with session_scope() as db:
        k = _activity(db, datetime(2026, 5, 13, 16, 17), km=20.0, provider="komoot", ext="k1", name="Garraf")
        s = _activity(db, datetime(2026, 5, 13, 14, 8), km=20.3, provider="strava", ext="s1", name="Garraf")
        kid, sid = k.id, s.id
    assert (
        client.post(f"/api/v1/activities/{kid}/merge", json={"other_id": sid}, headers=AUTH).status_code
        == 200
    )
    with session_scope() as db:
        recs = db.scalars(select(ProviderActivity)).all()
        assert {r.activity_id for r in recs} == {kid}
        ingest.match_unlinked(db)  # what every sync does
        assert db.scalar(select(func.count(Activity.id))) == 1
    dups = client.get("/api/v1/activities/duplicates", headers=AUTH).json()
    assert dups == []


def test_visibility_levels_copies_and_propagation(client, monkeypatch):
    from types import SimpleNamespace

    from routepass.engine import visibility as vis

    with session_scope() as db:
        act = _activity(db, datetime(2026, 6, 1, 9), provider="komoot", ext="k9")
        db.flush()
        komoot_rec = (
            act.sources[0] if act.sources else db.query(ProviderActivity).filter_by(external_id="k9").one()
        )
        komoot_rec.raw = {"status": "friends"}
        db.refresh(act)
        # A copy inherits the original's visibility …
        d = rule_engine.decide(act, "komoot_to_strava", [], {"default_action": "sync"})
        assert d.plan["strava"]["visibility"] == "followers_only"
        # … unless a rule sets one.
        rule = SimpleNamespace(
            id=1,
            priority=1,
            enabled=True,
            direction="komoot_to_strava",
            name="r",
            conditions={},
            actions={"strava": {"visibility": "only_me"}},
        )
        d = rule_engine.decide(act, "komoot_to_strava", [rule], {"default_action": "sync"})
        assert d.plan["strava"]["visibility"] == "only_me"

        copy = ProviderActivity(
            provider="strava",
            external_id="s9",
            activity_id=act.id,
            name="A",
            sport="Ride",
            start_time=act.start_time,
            created_by_sync=True,
            raw={"visibility": "only_me", vis.SYNCED_FROM: "friends"},
        )
        db.add(copy)
        db.flush()
        pushed = []
        monkeypatch.setattr(
            vis,
            "push",
            lambda db, rec, level: (pushed.append((rec.provider, level)), vis._remember(rec, level)),
        )
        assert vis.propagate(db) == 0  # original unchanged since the copy was made: rule choice kept
        komoot_rec.raw = {"status": "public"}  # the user makes the original public
        assert vis.propagate(db) == 1 and pushed == [("strava", "public")]
        assert vis.level_of(copy) == "public"
        assert vis.propagate(db) == 0
        act_id = act.id
    row = client.get(f"/api/v1/activities/{act_id}", headers=AUTH).json()
    assert row["visibility"] == {"by_provider": {"komoot": "public", "strava": "public"}, "mismatch": False}

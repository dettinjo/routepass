"""Route suggestions for training sessions (read-only; nothing is created on Komoot)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from routepass import store
from routepass.analysis import routes_finder, training
from routepass.db import session_scope
from routepass.engine import clients
from routepass.models import Activity, TrainingSession
from routepass.providers import komoot as kmt
from routepass.providers.gpx import encode_polyline
from tests.conftest import AUTH

HOME = (41.3869, 2.1084)


class _FakeKomoot:
    user_id = "u1"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def _act(db, days_ago: int, km: float, elev: float, end_offset: float = 0.0, name: str = "Loop"):
    start = datetime(2026, 11, 1, 8) - timedelta(days=days_ago)
    a = Activity(
        start_time=start,
        name=name,
        sport="TrailRun",
        family="run",
        distance_m=km * 1000,
        elevation_gain_m=elev,
        moving_time_s=km * 360,
        avg_speed_ms=1000 / 360,
        start_lat=HOME[0] + 0.001,
        start_lng=HOME[1],
        end_lat=HOME[0] + 0.001 + end_offset,
        end_lng=HOME[1],
        has_track=True,
        polyline=encode_polyline([(HOME[0], HOME[1]), (HOME[0] + 0.02, HOME[1] + 0.02), (HOME[0], HOME[1])]),
    )
    db.add(a)
    return a


def _plan(db):
    prefs = store.get_preferences(db)
    plan = training.create_plan(
        db,
        prefs,
        {"name": "50k", "plan_type": "trail_run", "event_date": "2027-07-08"},
        use_ai=False,
        today=date(2026, 11, 19),
    )
    s = db.query(TrainingSession).filter_by(plan_id=plan.id).order_by(TrainingSession.scheduled_date).first()
    s.target_distance_km, s.target_elev_m = 10.0, 300.0
    return s


def test_history_groups_repeats_ranks_loops_and_works_without_komoot(client):
    with session_scope() as db:
        store.update_preferences(
            db, {"places": [{"name": "Home", "lat": HOME[0], "lng": HOME[1], "radius_km": 0.5}]}
        )
        for d in (3, 10, 17):
            _act(db, d, 10.2, 310)  # the same loop three times
        _act(db, 5, 10.0, 290, end_offset=0.12, name="One way to the coast")  # ends ~13 km away
        _act(db, 7, 30.0, 900, name="Long")
        s = _plan(db)
        sid = s.id
    r = client.get(f"/api/v1/training/sessions/{sid}/routes", headers=AUTH).json()
    assert r["start"]["label"] == "Home" and r["komoot_connected"] is False
    names = [c["name"] for c in r["candidates"]]
    top = r["candidates"][0]
    assert top["name"] == "Loop" and top["times_done"] == 3 and top["loop"] is True
    assert names.count("Loop") == 1
    oneway = next(c for c in r["candidates"] if c["name"] == "One way to the coast")
    assert oneway["loop"] is False and oneway["match_score"] < top["match_score"]
    assert "One way" in " ".join(oneway["notes"])
    geo = client.get(
        "/api/v1/routes/geometry", params={"source": "history", "ref": top["activity_id"]}, headers=AUTH
    ).json()
    assert geo["polyline"]


def test_komoot_sources_attach_and_detach(client, monkeypatch):
    monkeypatch.setattr(clients, "komoot_client", lambda db: _FakeKomoot())
    monkeypatch.setattr(
        kmt,
        "planned_tours",
        lambda kc: [
            {
                "id": 901,
                "name": "Saved forest loop",
                "sport": "jogging",
                "distance": 10400,
                "elevation_up": 320,
                "start_point": {"lat": HOME[0] + 0.002, "lng": HOME[1]},
                "_image": "https://img/901",
            },
            {
                "id": 902,
                "name": "Saved bike tour",
                "sport": "racebike",
                "distance": 60000,
                "elevation_up": 800,
                "start_point": {"lat": HOME[0], "lng": HOME[1]},
                "_image": None,
            },
        ],
    )
    calls = {}

    def discover(kc, lat, lng, **kw):
        calls.update(kw)
        return [
            {
                "id": "e1",
                "name": "Montjuïc 360",
                "sport": "jogging",
                "distance": 11900,
                "elevation_up": 250,
                "start_point": {"lat": HOME[0] + 0.01, "lng": HOME[1]},
                "smart_tour_type": "EDITORIAL_TOUR",
                "rating_score": 4.38,
                "visitors": 296,
                "share_url": "https://www.komoot.com/smarttour/e1",
                "summary": {"surfaces": [{"type": "sf#asphalt", "amount": 0.8}]},
                "_image": "https://img/e1",
            }
        ]

    monkeypatch.setattr(kmt, "discover_tours", discover)
    routes_finder._cache.clear()
    with session_scope() as db:
        store.update_preferences(
            db, {"places": [{"name": "Home", "lat": HOME[0], "lng": HOME[1], "radius_km": 0.5}]}
        )
        sid = _plan(db).id
    r = client.get(f"/api/v1/training/sessions/{sid}/routes", headers=AUTH).json()
    by_name = {c["name"]: c for c in r["candidates"]}
    assert "Saved bike tour" not in by_name  # wrong sport family
    saved, nearby = by_name["Saved forest loop"], by_name["Montjuïc 360"]
    assert saved["source"] == "komoot_saved" and saved["komoot_url"].endswith("/tour/901")
    assert nearby["rating"] == 4.4 and nearby["surface"] == "mostly paved" and nearby["loop"] is True
    assert calls["min_length_m"] == 6500 and calls["max_length_m"] == 13500  # ±35 % around 10 km

    put = client.put(
        f"/api/v1/training/sessions/{sid}/route",
        json={"route": {**saved, "polyline": encode_polyline([HOME, (HOME[0] + 0.01, HOME[1])])}},
        headers=AUTH,
    )
    assert put.status_code == 200, put.text
    sess = next(x for w in put.json()["plan"]["weeks"] for x in w["sessions"] if x["id"] == sid)
    assert sess["route"]["name"] == "Saved forest loop" and sess["route"]["polyline"]
    out = client.delete(f"/api/v1/training/sessions/{sid}/route", headers=AUTH).json()
    sess = next(x for w in out["plan"]["weeks"] for x in w["sessions"] if x["id"] == sid)
    assert sess["route"] is None


def test_custom_start_and_no_start(client):
    with session_scope() as db:
        sid = _plan(db).id
    r = client.get(f"/api/v1/training/sessions/{sid}/routes", headers=AUTH).json()
    assert r["start"]["lat"] is None and r["candidates"] == []
    r = client.get(
        f"/api/v1/training/sessions/{sid}/routes",
        params={"lat": 47.0, "lng": 8.0, "label": "Lucerne"},
        headers=AUTH,
    ).json()
    assert r["start"] == {"label": "Lucerne", "lat": 47.0, "lng": 8.0, "source": "custom"}
    assert r["planner_url"].startswith("https://www.komoot.com/plan/@47.00000,8.00000")

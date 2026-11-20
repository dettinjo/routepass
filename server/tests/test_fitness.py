"""Fitness estimates (climb power, VDOT, predictions, load outlook) and the AI fitness jobs."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from routepass import store
from routepass.ai import coach, fitness_coach, gemini
from routepass.analysis import fitness
from routepass.db import session_scope
from routepass.models import Activity, Effort, Track


def test_climb_power_physics():
    # 392 m over 8.07 km in 1700 s with 75 kg rider: ~190 W gravity + rolling + air ≈ 235 W
    p = fitness.climb_power({"duration_s": 1700, "length_m": 8071, "gain_m": 392}, 75)
    assert 225 < p < 245
    # an hour at that pace is the threshold; shorter efforts scale down
    assert fitness._to_hour(300, 3600) == 300
    assert 270 < fitness._to_hour(300, 600) < 280  # 10 min → ~91 %
    assert 283 < fitness._to_hour(300, 1200) < 286  # 20 min → ~95 %


def test_vdot_and_predictions_match_daniels_tables():
    v = fitness.vdot(10000, 2800)  # 46:40 10 km
    assert 43 < v < 44
    assert 22 * 60 < fitness.predict_time(v, 5000) < 23 * 60
    assert 3.5 * 3600 < fitness.predict_time(v, 42195) < 3.7 * 3600
    assert 280 < fitness.threshold_pace(v) < 295  # ~4:45/km


def _ride(db, d: date, climbs: list[dict]) -> None:
    a = Activity(
        start_time=datetime(d.year, d.month, d.day, 9),
        name="Ride",
        sport="Ride",
        family="ride",
        distance_m=40000,
        moving_time_s=6000,
        load=80,
    )
    db.add(a)
    db.flush()
    db.add(Track(activity_id=a.id, provider="komoot", data=b"", detail={"climbs": climbs}))


def _run(db, d: date, dist: int, secs: float, name="Run") -> None:
    a = Activity(
        start_time=datetime(d.year, d.month, d.day, 9),
        name=name,
        sport="Run",
        family="run",
        distance_m=dist,
        moving_time_s=secs,
        load=60,
    )
    db.add(a)
    db.flush()
    db.add(Effort(activity_id=a.id, kind="time", key=dist, value=secs))


def test_estimates_from_climbs_and_runs():
    today = date.today()
    climb = {"length_m": 8000, "gain_m": 400, "grade_pct": 5.0, "duration_s": 1700, "vam": 847}
    with session_scope() as db:
        store.update_preferences(db, {"profile": {"weight_kg": 75}})
        for i in range(4):
            _ride(db, today - timedelta(days=10 + i), [climb, {**climb, "grade_pct": 2.0}])
        _run(db, today - timedelta(days=20), 10000, 2800, "10k race")
        _run(db, today - timedelta(days=30), 1609, 330, "sprint in a game")  # must not win over the 10 km
        e = fitness.estimates(db, today)
    c, r = e["cycling"], e["running"]
    assert c["basis"] == "climbs" and c["climbs_used"] == 4  # the 2 % climbs are ignored
    assert 2.7 < c["threshold_wkg"] < 3.2
    assert r["from_effort"]["distance_m"] == 10000 and 43 < r["vo2max"] < 44
    assert any("Max and resting heart rate" in n for n in e["needs"])
    assert e["state"].startswith("Fitness")


def test_cycling_needs_weight():
    with session_scope() as db:
        out = fitness.cycling(db, {}, datetime.now())
    assert "weight" in out["missing"]


def test_fitness_report_with_and_without_ai(monkeypatch):
    with session_scope() as db:
        _run(db, date.today() - timedelta(days=5), 5000, 1400)
    rep = fitness_coach.fitness_report("manual")
    assert rep["model"] == "deterministic" and rep["numbers"]["running_vo2max"]

    with session_scope() as db:
        gemini.save_ai_config(db, api_key="AQ.k")

    def fake(*, feature, user_payload, **_kw):
        assert feature == "fitness_report"
        assert user_payload["previous_report"]["headline"] == rep["headline"]
        assert "trend_by_month" in user_payload and "estimates" in user_payload
        return {
            "headline": "Solid aerobic base.",
            "summary": "S.",
            "strengths": ["a"],
            "limiters": ["b"],
            "changes": "c",
            "focus": ["d"],
        }, "gemini-4-hydrogen"

    monkeypatch.setattr(gemini, "generate_json", fake)
    rep2 = fitness_coach.fitness_report("manual")
    assert rep2["model"] == "gemini-4-hydrogen"
    with session_scope() as db:
        rs = fitness_coach.reports(db)
        assert [r["headline"] for r in rs] == ["Solid aerobic base.", rep["headline"]]
        assert not fitness_coach.report_due(db, date.today())
        assert fitness_coach.report_due(db, date.today() + timedelta(days=31))


def test_activity_analysis_stores_answer_and_keeps_it_on_failure(monkeypatch):
    with session_scope() as db:
        gemini.save_ai_config(db, api_key="AQ.k")
        _ride(
            db,
            date.today() - timedelta(days=1),
            [{"length_m": 3000, "gain_m": 150, "grade_pct": 5.0, "duration_s": 600}],
        )
        aid = db.scalar(select(Activity.id))
    seen = {}

    def ok(*, feature, user_payload, **_kw):
        seen.update(user_payload)
        return {
            "headline": "Steady climbing ride.",
            "points": ["p1", "p2"],
            "compared": "c",
            "next_time": "n",
        }, "gemini-4-hydrogen"

    monkeypatch.setattr(gemini, "generate_json", ok)
    coach.submit("activity_analysis", activity_id=aid)  # no worker in tests: runs inline
    assert seen["activity"]["sport"] == "Ride" and "climbs" in seen
    with session_scope() as db:
        assert db.get(Activity, aid).coach_analysis["headline"] == "Steady climbing ride."

    def busy(**_kw):
        raise gemini.GeminiError("HTTP 503: busy")

    monkeypatch.setattr(gemini, "generate_json", busy)
    coach.submit("activity_analysis", activity_id=aid)
    with session_scope() as db:
        ca = db.get(Activity, aid).coach_analysis
        assert ca["headline"] == "Steady climbing ride." and "503" in ca["error"]


@pytest.mark.usefixtures("client")
def test_fitness_api(client):
    from tests.conftest import AUTH

    r = client.get("/api/v1/insights/fitness?months=6", headers=AUTH)
    assert r.status_code == 200 and len(r.json()["trend"]) == 6 and "state" in r.json()
    r = client.get("/api/v1/insights/fitness-report", headers=AUTH)
    assert r.status_code == 200 and r.json()["latest"] is None

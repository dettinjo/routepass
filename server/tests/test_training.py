"""Tests for multi-sport adaptive Training Plans, predictions, Gemini budget guard, and MCP tools."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from routepass import mcp_server, store
from routepass.ai import gemini
from routepass.analysis import training
from routepass.db import session_scope
from routepass.main import create_app
from routepass.models import Activity, AIUsageLog


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_multi_sport_plan_lifecycle_and_predictions(db):
    today = date(2026, 6, 15)
    with session_scope() as s:
        # Seed a few recent activities so baseline has real CTL & GAP
        for i in range(1, 8):
            d = today - timedelta(days=i * 2)
            s.add(
                Activity(
                    start_time=datetime(d.year, d.month, d.day, 7, 0),
                    start_local=datetime(d.year, d.month, d.day, 9, 0),
                    name=f"Trail Run {i}",
                    sport="TrailRun",
                    family="run",
                    distance_m=14000,
                    moving_time_s=4800,
                    elevation_gain_m=450,
                    load=75.0,
                )
            )
        s.flush()

        prefs = store.get_preferences(s)
        # 1. Create Triathlon 70.3 plan (deterministic, no network)
        tri = training.create_plan(
            s,
            prefs,
            {
                "name": "70.3 Kraichgau",
                "plan_type": "triathlon",
                "start_date": (today - timedelta(days=7)).isoformat(),
                "event_date": (today + timedelta(days=70)).isoformat(),
                "goal_spec": {
                    "targets": {
                        "swim_km": 1.9,
                        "bike_km": 90,
                        "bike_elev_m": 1000,
                        "run_km": 21.1,
                        "run_elev_m": 200,
                    },
                    "target_time_s": 19800,
                },
                "schedule_prefs": {"max_weekly_hours": 10.0, "preferred_slot": "morning", "rest_days": [0]},
            },
            use_ai=False,
            today=today,
        )
        detail = training.serialize_plan_detail(s, tri, prefs, today=today)
        assert detail["plan_type"] == "triathlon"
        assert len(detail["weeks"]) >= 8
        assert "bike" in detail["analytics"]["disciplines"]
        assert "swim" in detail["analytics"]["disciplines"]
        assert "run" in detail["analytics"]["disciplines"]
        traj = detail["analytics"]["trajectory"]
        assert len(traj) == len(detail["weeks"])
        assert traj[-1]["predicted_time_s"] > 0
        assert detail["analytics"]["prediction"]["verdict"] in ("on_track", "catchable", "at_risk")

        # 2. Deterministic adaptation responds to tiredness & missed sessions
        res = training.adapt_plan(
            s,
            tri,
            prefs,
            trigger="manual",
            user_note="Legs very tired and sore today",
            today=today,
            force=True,
        )
        assert res["adapted"] is True
        assert res["model_used"] == "deterministic"
        assert len(res["diff"]) >= 1


def test_gemini_budget_guard_and_endpoint_detection(db):
    urls_vertex = gemini._endpoints_for_key("AQ.testkey", "gemini-4-hydrogen")
    assert "aiplatform.googleapis.com" in urls_vertex[0]
    urls_studio = gemini._endpoints_for_key("AIzaTestKey", "gemini-4-hydrogen")
    assert "generativelanguage.googleapis.com/v1/" in urls_studio[0]

    with session_scope() as s:
        cfg = gemini.save_ai_config(s, api_key="AQ.fake-key", monthly_budget_usd=1.0)
        assert cfg["configured"] is True
        assert cfg["key_source"] == "settings"
        assert cfg["model_fast"] == "gemini-4-hydrogen"
        assert cfg["model_pro"] == "gemini-4-hydrogen"
        assert cfg["monthly_budget_usd"] == 1.0

        s.add(
            AIUsageLog(
                feature="test",
                model="gemini-4-hydrogen",
                input_tokens=100000,
                output_tokens=100000,
                estimated_cost_usd=1.25,
            )
        )
        s.flush()

        try:
            gemini.generate_json(
                s,
                feature="plan_adapt",
                system_prompt="test",
                user_payload={"a": 1},
                tier="fast",
            )
            raise AssertionError("Expected BudgetExceededError")
        except gemini.BudgetExceededError:
            pass


def test_training_rest_api_and_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTEPASS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ROUTEPASS_API_TOKEN", "test-token")
    from routepass.config import get_settings

    get_settings.cache_clear()
    app = create_app(start_scheduler=False)

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/training/plans",
            headers=_auth_headers(),
            json={
                "name": "Alps 50k Trail",
                "plan_type": "trail_run",
                "event_date": (date.today() + timedelta(days=56)).isoformat(),
                "goal_spec": {"targets": {"run_km": 50, "run_elev_m": 2400}, "target_time_s": 25200},
                "schedule_prefs": {"max_weekly_hours": 8.0, "preferred_slot": "evening"},
                "use_ai": False,
            },
        )
        assert r.status_code == 200, r.text
        plan = r.json()
        pid = plan["id"]
        assert plan["analytics"]["alignment"]["overall"] >= 0
        assert len(plan["analytics"]["trajectory"]) >= 6

        # List plans
        r2 = client.get("/api/v1/training/plans", headers=_auth_headers())
        assert r2.status_code == 200
        assert len(r2.json()["plans"]) == 1

        # Adapt plan
        r3 = client.post(
            f"/api/v1/training/plans/{pid}/adapt",
            headers=_auth_headers(),
            json={"user_note": "Feeling tired after travel", "force": True},
        )
        assert r3.status_code == 200
        assert r3.json()["result"]["adapted"] is True

        # Update a session manually
        first_sid = plan["weeks"][0]["sessions"][0]["id"]
        r4 = client.patch(
            f"/api/v1/training/sessions/{first_sid}",
            headers=_auth_headers(),
            json={"status": "completed"},
        )
        assert r4.status_code == 200
        assert r4.json()["status"] == "completed"

        # AI config endpoint
        r5 = client.put(
            "/api/v1/training/ai-config",
            headers=_auth_headers(),
            json={"monthly_budget_usd": 7.5},
        )
        assert r5.status_code == 200
        assert r5.json()["monthly_budget_usd"] == 7.5

    # Verify MCP tools
    mcp_plan = mcp_server.get_training_plan()
    assert mcp_plan["id"] == pid
    mcp_adapt = mcp_server.adapt_training_plan(plan_id=pid, user_note="Slightly sore calves")
    assert mcp_adapt["adapted"] is True
    with session_scope() as db:
        assert db.query(Activity).count() == 0


def test_skip_adapt_recovery_and_simulated_race_activity(db, monkeypatch):
    monkeypatch.setenv("ROUTEPASS_API_TOKEN", "test-token")

    from routepass.providers import gcal

    # Ensure Google Calendar reuses the registered Google Sign-In redirect URI
    assert gcal.GCAL_CALLBACK_PATH == "/api/v1/auth/google/callback"

    app = create_app()
    event_date = (date.today() + timedelta(days=56)).isoformat()
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/training/plans",
            headers=_auth_headers(),
            json={
                "name": "Dolomites 50k",
                "plan_type": "trail_run",
                "event_date": event_date,
                "goal_spec": {"targets": {"run_km": 50, "run_elev_m": 2400}, "target_time_s": 25200},
                "schedule_prefs": {"max_weekly_hours": 8, "preferred_slot": "evening"},
                "use_ai": False,
            },
        )
        assert r.status_code == 200
        plan = r.json()

        # Verify simulated completed race activity & gamification & recency baseline
        sim = plan["analytics"]["prediction"]["simulated_activity"]
        assert sim["name"] == "Dolomites 50k"
        assert sim["sport"] == "TrailRun"
        assert sim["predicted_time_s"] > 0
        assert len(sim["splits"]) == 4
        assert "confidence_pct" in sim

        gam = plan["analytics"]["gamification"]
        assert gam["level"] >= 1
        assert "xp_progress_pct" in gam

        base = plan["analytics"]["baseline"]
        assert "detraining_factor" in base
        assert "readiness_label" in base

        # Find an upcoming session (>= today) to test muscle_pain conversion to recovery
        all_sessions = [s for w in plan["weeks"] for s in w["sessions"]]
        today_iso = date.today().isoformat()
        upcoming = [s for s in all_sessions if s["scheduled_date"] >= today_iso]
        assert len(upcoming) >= 3

        s_pain = upcoming[0]
        r_pain = client.post(
            f"/api/v1/training/sessions/{s_pain['id']}/skip-adapt",
            headers=_auth_headers(),
            json={"reason": "muscle_pain", "severity": "moderate", "note": "Tight calves"},
        )
        assert r_pain.status_code == 200
        body_pain = r_pain.json()
        assert body_pain["result"]["recovery_planned"] is True
        updated_s = next(
            s for w in body_pain["plan"]["weeks"] for s in w["sessions"] if s["id"] == s_pain["id"]
        )
        assert updated_s["session_type"] == "recovery"
        assert "Recovery" in updated_s["title"]

        # Test sickness skip & protection
        s_sick = upcoming[2]
        r_sick = client.post(
            f"/api/v1/training/sessions/{s_sick['id']}/skip-adapt",
            headers=_auth_headers(),
            json={"reason": "sickness", "severity": "moderate", "note": "Mild fever"},
        )
        assert r_sick.status_code == 200
        body_sick = r_sick.json()
        assert body_sick["result"]["reason"] == "sickness"
        sick_s = next(s for w in body_sick["plan"]["weeks"] for s in w["sessions"] if s["id"] == s_sick["id"])
        assert sick_s["status"] == "skipped"


def test_plan_created_midweek_schedules_nothing_before_today(db):
    thursday = date(2026, 11, 19)
    with session_scope() as s:
        prefs = store.get_preferences(s)
        plan = training.create_plan(
            s,
            prefs,
            {"name": "50k", "plan_type": "trail_run", "event_date": "2027-07-08"},
            use_ai=False,
            today=thursday,
        )
        assert plan.start_date == "2026-11-19"
        detail = training.serialize_plan_detail(s, plan, prefs, today=thursday)
        first_week = detail["weeks"][0]
        assert first_week["start_date"] == "2026-11-16"  # the week grid still starts on Monday
        dates = [x["scheduled_date"] for x in first_week["sessions"]]
        assert dates and min(dates) >= "2026-11-19"
        assert all(x["status"] != "missed" for w in detail["weeks"] for x in w["sessions"])
        a = detail["analytics"]
        assert a["alignment"]["enough_data"] is False
        assert a["prediction"]["verdict"] == "early"
        assert (
            a["prediction"]["range_low_s"]
            < a["prediction"]["race_day_trend_s"]
            < a["prediction"]["range_high_s"]
        )
        assert a["data_quality"]["level"] == "low"


def test_legacy_plan_drops_sessions_before_creation(db):
    from routepass.models import TrainingSession

    monday = date(2027, 2, 1)
    with session_scope() as s:
        prefs = store.get_preferences(s)
        plan = training.create_plan(
            s,
            prefs,
            {"name": "Old", "plan_type": "trail_run", "event_date": "2027-06-01"},
            use_ai=False,
            today=monday,
        )
        before = s.query(TrainingSession).filter(TrainingSession.plan_id == plan.id).all()
        assert any(x.scheduled_date < "2027-02-04" for x in before)
        plan.created_at = datetime(2027, 2, 4, 12, 24)  # created on Thursday, stored Monday as start
        s.flush()
        training.match_activities_to_plan(s, plan, today=date(2027, 2, 5))
        left = s.query(TrainingSession).filter(TrainingSession.plan_id == plan.id).all()
        assert left and all(x.scheduled_date >= "2027-02-04" for x in left)


def test_data_quality_suggests_profile_values(db):
    from routepass.analysis import insights

    today = date(2026, 11, 19)
    with session_scope() as s:
        for i, hr in enumerate([171, 176, 182, 188, 240, 190]):  # 240 = strap glitch, ignored
            d = today - timedelta(days=i + 1)
            s.add(
                Activity(
                    start_time=datetime(d.year, d.month, d.day, 8),
                    name="Run",
                    sport="Run",
                    family="run",
                    moving_time_s=3600,
                    load=60.0,
                    load_method="estimate",
                    max_hr=hr,
                )
            )
        s.flush()
        q = insights.data_quality(s, today)
        assert q["level"] == "low"
        assert q["suggestions"]["hr_max"] == 188  # second-highest plausible value
        assert any(m["field"] == "hr_max" for m in q["missing"])


def test_session_feedback_variants_and_rpe_load(client):
    from routepass.models import TrainingSession

    today = date(2026, 11, 19)
    with session_scope() as s:
        prefs = store.get_preferences(s)
        plan = training.create_plan(
            s,
            prefs,
            {"name": "50k", "plan_type": "trail_run", "event_date": "2027-07-08"},
            use_ai=False,
            today=today,
        )
        sessions = (
            s.query(TrainingSession).filter_by(plan_id=plan.id).order_by(TrainingSession.scheduled_date).all()
        )
        first, second, third = sessions[0].id, sessions[1].id, sessions[2].id
        act = Activity(
            start_time=datetime(2026, 11, 19, 18),
            name="Run",
            sport="TrailRun",
            family="run",
            moving_time_s=3600,
            distance_m=10000,
            load=50.0,
            load_method="estimate",
        )
        s.add(act)
        s.flush()
        sessions[0].matched_activity_id = act.id
        act_id, plan_id = act.id, plan.id
    h = _auth_headers()

    # Effort replaces the duration estimate: RPE 7 for 1 h = 0.85² × 100 ≈ 72.
    r = client.post(f"/api/v1/training/sessions/{first}/feedback", json={"rpe": 7, "feel": "hard"}, headers=h)
    assert r.status_code == 200, r.text
    with session_scope() as s:
        a = s.get(Activity, act_id)
        assert a.load_method == "rpe" and round(a.load) == 72

    # Shorter, then undo.
    full = client.get(f"/api/v1/training/plans/{plan_id}", headers=h).json()
    target = next(x for w in full["weeks"] for x in w["sessions"] if x["id"] == second)
    assert target["why"] and target["compliance_level"] == "planned" and "zone" in target
    r = client.post(
        f"/api/v1/training/sessions/{second}/variant", json={"kind": "shorter", "minutes": 30}, headers=h
    ).json()
    short = next(x for w in r["plan"]["weeks"] for x in w["sessions"] if x["id"] == second)
    assert short["target_duration_s"] == 1800 and short["changed"] and short["status"] == "moved"
    r = client.post(
        f"/api/v1/training/sessions/{second}/variant", json={"kind": "original"}, headers=h
    ).json()
    back = next(x for w in r["plan"]["weeks"] for x in w["sessions"] if x["id"] == second)
    assert back["target_duration_s"] == target["target_duration_s"] and not back["changed"]

    # Swap exchanges the dates of the two next sessions.
    r = client.post(f"/api/v1/training/sessions/{second}/variant", json={"kind": "swap"}, headers=h).json()
    by_id = {x["id"]: x for w in r["plan"]["weeks"] for x in w["sessions"]}
    assert by_id[second]["scheduled_date"] > by_id[third]["scheduled_date"]

    # A second session that felt too hard eases the next sessions.
    r = client.post(
        f"/api/v1/training/sessions/{third}/feedback", json={"rpe": 9, "feel": "hard"}, headers=h
    ).json()
    assert r["result"]["adjusted"]
    assert "zones" in r["plan"]

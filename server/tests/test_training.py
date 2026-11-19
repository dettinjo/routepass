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
                    "targets": {"swim_km": 1.9, "bike_km": 90, "bike_elev_m": 1000, "run_km": 21.1, "run_elev_m": 200},
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
            s, tri, prefs, trigger="manual", user_note="Legs very tired and sore today", today=today, force=True
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

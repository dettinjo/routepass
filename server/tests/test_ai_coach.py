"""The AI coach: Gemini client (endpoints, retries, spend), checks on proposed changes, and the
background jobs (adapt, write weeks, workout feedback, weekly review)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from routepass import store
from routepass.ai import coach, gemini
from routepass.analysis import training
from routepass.db import session_scope
from routepass.models import Activity, AIUsageLog, PlanAdaptation, TrainingPlan, TrainingSession, TrainingWeek

STUDIO = "https://generativelanguage.googleapis.com/v1beta/models/gemini-4-hydrogen:generateContent"
VERTEX = "https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-4-hydrogen:generateContent"


def _answer(text: str, thoughts: int = 0) -> dict:
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
        "usageMetadata": {
            "promptTokenCount": 1000,
            "candidatesTokenCount": 100,
            "thoughtsTokenCount": thoughts,
        },
    }


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(gemini, "RETRY_WAITS_S", (0.0, 0.0))
    gemini._working_endpoint.clear()
    with session_scope() as db:
        gemini.save_ai_config(db, api_key="AQ.test-key-123456789")


def _plan(today: date | None = None, *, ai: bool = True) -> int:
    today = today or date.today()
    with session_scope() as db:
        plan = training.create_plan(
            db,
            store.get_preferences(db),
            {
                "name": "Test 50k",
                "plan_type": "trail_run",
                "start_date": today.isoformat(),
                "event_date": (today + timedelta(days=70)).isoformat(),
                "schedule_prefs": {"max_weekly_hours": 8, "rest_days": [0]},
            },
            use_ai=ai,
            today=today,
        )
        return plan.id


# ── Gemini client ────────────────────────────────────────────────────────────


@respx.mock
def test_key_in_header_retry_on_overload_and_thinking_tokens_billed(key):
    route = respx.post(STUDIO).mock(
        side_effect=[
            httpx.Response(503, json={"error": {"code": 503, "message": "high demand"}}),
            httpx.Response(200, json=_answer('{"ok": true}', thoughts=400)),
        ]
    )
    res, model = gemini.generate_json(feature="test", system_prompt="s", user_payload={})
    assert res == {"ok": True} and model == "gemini-4-hydrogen"
    assert route.call_count == 2
    req = route.calls[-1].request
    assert req.headers["x-goog-api-key"] == "AQ.test-key-123456789"
    assert "key=" not in str(req.url)
    with session_scope() as db:
        log = db.scalar(select(AIUsageLog))
        assert log.output_tokens == 500  # 100 answer + 400 thinking
        status = gemini.get_ai_config(db)["status"]
        assert status["last_ok"] is True and status["last_feature"] == "test"


@respx.mock
def test_falls_through_to_vertex_when_studio_refuses_the_key(key):
    respx.post(STUDIO).mock(return_value=httpx.Response(403, json={"error": {"message": "no"}}))
    respx.post(STUDIO.replace("v1beta", "v1")).mock(return_value=httpx.Response(404, text="nope"))
    vertex = respx.post(VERTEX).mock(return_value=httpx.Response(200, json=_answer('{"ok": 1}')))
    gemini.generate_json(feature="test", system_prompt="s", user_payload={})
    assert vertex.called
    assert gemini._endpoint_order("AQ.test-key-123456789")[0] == "vertex"  # remembered


@respx.mock
def test_failure_is_recorded_for_the_ui(key):
    respx.post(STUDIO).mock(
        return_value=httpx.Response(503, json={"error": {"code": 503, "message": "busy"}})
    )
    with pytest.raises(gemini.GeminiError, match="busy"):
        gemini.generate_json(feature="plan_adapt", system_prompt="s", user_payload={})
    with session_scope() as db:
        status = gemini.get_ai_config(db)["status"]
        assert status["last_ok"] is False and "busy" in status["last_error"]
        assert db.scalar(select(AIUsageLog)) is None  # nothing billed


# ── checks on proposed changes ───────────────────────────────────────────────


def test_proposed_changes_are_checked():
    today = date.today()
    pid = _plan(today, ai=False)
    with session_scope() as db:
        plan = db.get(TrainingPlan, pid)
        sessions = list(db.scalars(select(TrainingSession).where(TrainingSession.plan_id == pid)))
        open_ = [
            s
            for s in sessions
            if s.sport != "rest"
            and today.isoformat() <= s.scheduled_date <= (today + timedelta(days=14)).isoformat()
        ]
        easy = next(s for s in open_ if s.session_type == "easy")
        key = next((s for s in open_ if s.priority == "key"), None)
        far = next(s for s in sessions if s.scheduled_date > (today + timedelta(days=20)).isoformat())
        race = next(s for s in sessions if s.session_type == "race")
        # make a hard session the day after `easy` so turning `easy` into intervals clashes
        neighbour = next((s for s in open_ if s.id != easy.id), None)
        neighbour.scheduled_date = (date.fromisoformat(easy.scheduled_date) + timedelta(days=1)).isoformat()
        neighbour.session_type = "intervals"
        db.flush()
        allowed = {s.id for s in open_}
        muts = [
            {"session_id": str(easy.id), "action": "adjust_load", "duration_scale": 0.8, "note": "ok"},
            {"session_id": easy.id, "action": "swap_type", "new_session_type": "intervals"},
            {"session_id": easy.id, "action": "swap_type", "new_session_type": "yoga"},
            {"session_id": far.id, "action": "adjust_load", "duration_scale": 0.8},
            {"session_id": race.id, "action": "skip"},
            {
                "session_id": easy.id,
                "action": "reschedule",
                "new_date": (today + timedelta(days=30)).isoformat(),
            },
        ]
        if key is not None:
            muts.append({"session_id": key.id, "action": "skip"})
        before = easy.target_duration_s
        diff, rejected = training._apply_mutations(db, plan, sessions, muts, today, allowed_ids=allowed)
        assert [d["session_id"] for d in diff] == [easy.id]
        assert easy.target_duration_s == round(before * 0.8)
        assert easy.original_target is not None  # the change can be undone
        reasons = " | ".join(r["reason"] for r in rejected)
        assert "back to back" in reasons
        assert "unknown session type" in reasons
        assert "not an open session" in reasons
        assert "outside the next 14 days" in reasons
        if key is not None:
            assert "not skipped" in reasons


# ── jobs ─────────────────────────────────────────────────────────────────────


def _fake(answers: dict, calls: list | None = None):
    def fake(*, feature, system_prompt, user_payload, tier="fast", **_kw):
        if calls is not None:
            calls.append((feature, tier, user_payload))
        ans = answers[feature]
        if isinstance(ans, Exception):
            raise ans
        return (ans(user_payload) if callable(ans) else ans), "gemini-4-hydrogen"

    return fake


def test_adapt_applies_checked_ai_proposal(key, monkeypatch):
    pid = _plan()
    with session_scope() as db:
        s = db.scalars(
            select(TrainingSession)
            .where(
                TrainingSession.plan_id == pid,
                TrainingSession.sport != "rest",
                TrainingSession.scheduled_date >= date.today().isoformat(),
            )
            .order_by(TrainingSession.scheduled_date)
        ).first()
        sid, minutes = s.id, s.target_duration_s
    monkeypatch.setattr(
        gemini,
        "generate_json",
        _fake(
            {
                "plan_adapt": {
                    "summary": "Trimmed tomorrow after a hard week.",
                    "mutations": [
                        {"session_id": sid, "action": "adjust_load", "duration_scale": 0.7, "note": "tired"},
                        {"session_id": sid, "action": "skip_everything"},
                    ],
                }
            }
        ),
    )
    res = coach.adapt(pid, trigger="manual", user_note="tired", force=True)
    assert res["model_used"] == "gemini-4-hydrogen" and len(res["diff"]) == 1
    with session_scope() as db:
        assert db.get(TrainingSession, sid).target_duration_s == round(minutes * 0.7)
        row = db.scalars(select(PlanAdaptation).where(PlanAdaptation.trigger == "manual")).one()
        assert row.summary.startswith("Trimmed") and row.details["rejected"][0]["reason"].startswith(
            "unknown"
        )


def test_adapt_falls_back_to_rules_and_says_why(key, monkeypatch):
    pid = _plan()
    monkeypatch.setattr(gemini, "generate_json", _fake({"plan_adapt": gemini.GeminiError("HTTP 503: busy")}))
    res = coach.adapt(pid, trigger="manual", user_note="legs tired and sore", force=True)
    assert res["model_used"] == "deterministic" and "503" in res["ai_error"]
    with session_scope() as db:
        assert (
            "503"
            in db.scalars(select(PlanAdaptation).where(PlanAdaptation.trigger == "manual")).one().ai_error
        )


def test_write_weeks_writes_text_only_and_marks_weeks(key, monkeypatch):
    pid = _plan()
    calls: list = []

    def answer(payload):
        return {
            "coach_summary": "Ten weeks to a strong 50k.",
            "week_focus": {str(w["week_index"]): f"Focus {w['week_index']}" for w in payload["weeks"]},
            "sessions": [
                {
                    "id": s["id"],
                    "title": f"Written {s['id']}",
                    "description": "Why.",
                    "workout_steps": ["10 min warm-up", "Main set", "Cool-down"],
                }
                for s in payload["sessions"]
            ],
        }

    monkeypatch.setattr(gemini, "generate_json", _fake({"plan_write": answer}, calls))
    with session_scope() as db:
        before = {
            s.id: s.target_duration_s
            for s in db.scalars(select(TrainingSession).where(TrainingSession.plan_id == pid))
        }
    res = coach.write_weeks(pid, intro=True)
    assert res["ok"] and res["written"] > 0
    assert calls[0][1] == "pro" and "zones" in calls[0][2]
    with session_scope() as db:
        plan = db.get(TrainingPlan, pid)
        assert plan.coach_summary == "Ten weeks to a strong 50k."
        written = [w for w in plan.weeks if w.ai_written_at is not None]
        assert 1 <= len(written) <= coach.WEEKS_PER_CALL and written[0].coach_focus.startswith("Focus")
        for s in db.scalars(select(TrainingSession).where(TrainingSession.plan_id == pid)):
            assert s.target_duration_s == before[s.id]  # numbers untouched
    assert coach.write_weeks(pid) is None or calls[-1][2]["weeks"][0]["week_index"] > written[-1].week_index


def test_feedback_and_weekly_review(key, monkeypatch):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    pid = _plan(monday - timedelta(days=7))
    with session_scope() as db:
        s = db.scalars(
            select(TrainingSession)
            .where(
                TrainingSession.plan_id == pid,
                TrainingSession.sport != "rest",
                TrainingSession.scheduled_date >= (monday - timedelta(days=7)).isoformat(),
                TrainingSession.scheduled_date < monday.isoformat(),
            )
            .order_by(TrainingSession.scheduled_date)
        ).first()
        d = date.fromisoformat(s.scheduled_date)
        db.add(
            Activity(
                start_time=datetime(d.year, d.month, d.day, 7),
                start_local=datetime(d.year, d.month, d.day, 8),
                name="Run",
                sport="TrailRun",
                family="run",
                distance_m=10000,
                moving_time_s=s.target_duration_s or 3600,
                avg_hr=150,
                load=60,
            )
        )
        db.flush()
        training.match_activities_to_plan(db, db.get(TrainingPlan, pid))
        sid = s.id
    monkeypatch.setattr(
        gemini,
        "generate_json",
        _fake(
            {
                "session_feedback": {"feedback": "Steady and controlled — exactly what an easy day is for."},
                "weekly_review": {
                    "headline": "A solid first week.",
                    "went_well": ["Consistent"],
                    "watch": [],
                    "next_week": "More of the same.",
                },
            }
        ),
    )
    sent: list = []
    from routepass import push

    monkeypatch.setattr(push, "send_notification", lambda db, **kw: sent.append(kw) or {})
    coach.feedback(sid)
    with session_scope() as db:
        assert db.get(TrainingSession, sid).coach_feedback.startswith("Steady")
    assert sent[-1]["title"].startswith("Coach:")

    week = (monday - timedelta(days=7)).isoformat()
    review = coach.weekly_review(pid, week)
    assert review["headline"] == "A solid first week."
    assert coach.weekly_review(pid, week) is None  # once per week
    with session_scope() as db:
        detail = training.serialize_plan_detail(db, db.get(TrainingPlan, pid), store.get_preferences(db))
        assert detail["weekly_review"]["headline"] == "A solid first week."
        assert detail["weekly_review"]["stats"]["done"] >= 1
        assert all(a["trigger"] != "weekly_review" for a in detail["adaptations"])
        assert detail["ai"]["coach"]["running"] is False


def test_weekly_review_without_ai_uses_the_numbers():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    pid = _plan(monday - timedelta(days=7), ai=False)
    review = coach.weekly_review(pid, (monday - timedelta(days=7)).isoformat())
    assert review is not None and "sessions done" in review["headline"]
    with session_scope() as db:
        assert (
            db.scalar(select(PlanAdaptation).where(PlanAdaptation.trigger == "weekly_review")).model_used
            == "deterministic"
        )


def test_api_create_plan_hands_writing_to_the_coach(monkeypatch, client):
    from tests.conftest import AUTH

    assert client.put("/api/v1/training/ai-config", headers=AUTH, json={"api_key": "AQ.k"}).json()[
        "configured"
    ]
    jobs: list = []
    monkeypatch.setattr(coach, "submit", lambda kind, **kw: jobs.append((kind, kw)) or {"queued": True})
    r = client.post(
        "/api/v1/training/plans",
        headers=AUTH,
        json={
            "name": "API 50k",
            "plan_type": "trail_run",
            "event_date": (date.today() + timedelta(days=60)).isoformat(),
            "use_ai": True,
        },
    )
    assert r.status_code == 200, r.text
    assert jobs == [("write_weeks", {"plan_id": r.json()["id"], "intro": True})]
    r = client.post(
        f"/api/v1/training/plans/{r.json()['id']}/adapt", headers=AUTH, json={"user_note": "busy week"}
    )
    assert r.json()["result"]["queued"] is True and jobs[-1][0] == "adapt"
    with session_scope() as db:
        assert db.scalar(select(TrainingWeek).where(TrainingWeek.ai_written_at.is_not(None))) is None

"""The AI coach: Gemini writes and adapts plan sessions in the background.

The code does every number (load, zones, matching, compliance) and checks every change the model
proposes; the model only writes text and proposes changes. Four jobs:

- adapt         adjust the next 14 days after training, skips or an athlete note
- write_weeks   write the sessions of weeks as they come within 14 days (titles, steps, purpose)
- feedback      a short note on each matched workout, target vs what happened
- weekly_review a look back at the finished week and ahead at the next one

Jobs run one at a time on a worker thread, so a slow model (a minute is normal for gemini-4 under
load) never holds a request or a database transaction. Each job reads in one short session, calls
Gemini with none open, and writes in another. When Gemini is unavailable the built-in rules adapt
the plan and the weekly review is written from the numbers alone; the reason is shown in the UI.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from routepass import store
from routepass.ai import gemini
from routepass.db import session_scope
from routepass.models import Activity, PlanAdaptation, Track, TrainingPlan, TrainingSession, TrainingWeek
from routepass.timeutil import utcnow

logger = logging.getLogger(__name__)

SWEEP_EVERY_S = 3600
WRITE_AHEAD_DAYS = 14
WEEKS_PER_CALL = 2
FEEDBACK_DAYS = 4  # matched workouts this recent get a note; older ones are left alone
FEEDBACK_PER_SWEEP = 3
RETRY_AFTER_FAILURE_S = 3600  # Gemini overload usually passes within the hour

ADAPT_PROMPT = (
    "You are an endurance coach adapting an athlete's next 14 days. You get recent sessions (with "
    "status, compliance, how they felt and their notes), current load (CTL fitness, ATL fatigue, TSB "
    "form, ACWR), an optional note from the athlete and the upcoming sessions. Propose the smallest set "
    "of changes that keeps the plan's intent. Missed key session: move or trim it onto a free or easy "
    "day. High fatigue (TSB below -20 or ACWR above 1.35), illness, pain or an athlete who feels "
    "drained: reduce load. Never put two hard sessions (tempo, intervals, hills) on consecutive days, "
    "never change race sessions, never skip key sessions, keep rest days free. Changes that break "
    'these rules are rejected by the app. Reply with JSON: {"summary": one or two plain sentences '
    'for the athlete saying what changed and why, "mutations": [{"session_id": int, "action": '
    '"reschedule"|"adjust_load"|"swap_type"|"skip", "new_date": "YYYY-MM-DD" (optional), '
    '"duration_scale": 0.5-1.25 (optional), "new_session_type": easy|long|tempo|intervals|hills|'
    'recovery|strides|strength (optional), "new_title" (optional), "new_description" (optional), '
    '"note": short reason}]}. An empty mutations list is a good answer when the plan already fits.'
)

WRITE_PROMPT = (
    "You are an endurance coach writing the sessions of the coming weeks of a training plan. Each "
    "session's sport, type, date, duration, distance and load are fixed by the plan; do not change "
    "them. For every session write a specific title (max 60 characters), a description of 1-3 "
    "sentences saying what it is for and how it should feel, and 2-6 workout steps (warm-up, main "
    "set, cool-down). Use the athlete's personal zones (heart rate in bpm, pace in seconds per km, "
    "power in watts) given in the input, written as e.g. '142-155 bpm' or '5:20-5:40/km'; when a "
    "zone is missing describe effort instead (talk test, RPE). Steps must add up to roughly the "
    'session\'s duration. Reply with JSON: {"week_focus": {"<week_index>": one sentence}, '
    '"sessions": [{"id": int, "title": str, "description": str, "workout_steps": [str]}]'
    "{intro}}."
)
WRITE_INTRO = (
    ', "coach_summary": 2-3 sentences introducing the whole plan: the goal, how the phases build '
    "and what matters most for this athlete"
)

FEEDBACK_PROMPT = (
    "You are an endurance coach giving brief feedback on one workout. You get the planned session "
    "(type, target zone, duration, distance, load, steps), what was recorded (duration, distance, "
    "climbing, heart rate, power, load, time in each zone when known) and how the athlete rated it. "
    "Write 1-3 short sentences: whether the session did its job, one concrete observation from the "
    "numbers (e.g. too much time above the target zone on an easy day, a strong steady effort) and, "
    "only when useful, one tip for the next similar session. Plain, encouraging, specific; no "
    'greetings, no emoji, no invented numbers. Reply with JSON: {"feedback": str}.'
)

REVIEW_PROMPT = (
    "You are an endurance coach writing a weekly review. You get the finished week's numbers "
    "(sessions planned/done/missed, planned vs actual load and time, compliance, how sessions felt "
    "and the athlete's notes), current fitness, fatigue and form, and next week's plan. Every number "
    'is computed already; use them, do not invent others. Reply with JSON: {"headline": one '
    'sentence verdict, "went_well": up to 3 short points, "watch": up to 3 short points (empty '
    'when nothing needs attention), "next_week": 1-2 sentences on what next week is about and the '
    "session that matters most}."
)

# ── worker ───────────────────────────────────────────────────────────────────

_queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
_pending: set[str] = set()
_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_current: dict[str, Any] | None = None
_recent: deque[dict[str, Any]] = deque(maxlen=8)
_failed_at: dict[str, float] = {}

LABELS = {
    "adapt": "Reviewing your plan",
    "write_weeks": "Writing the coming sessions",
    "feedback": "Reviewing a workout",
    "weekly_review": "Writing the weekly review",
    "sweep": "Checking what to do",
    "fitness_report": "Writing your fitness report",
    "activity_analysis": "Analysing an activity",
}


def _key(kind: str, kw: dict[str, Any]) -> str:
    return kind + json.dumps(kw, sort_keys=True, default=str)


def submit(kind: str, **kw: Any) -> dict[str, Any]:
    """Queue a job (deduplicated). Without a running worker (tests, CLI) it runs right away."""
    if kind not in JOBS and kind not in FITNESS_JOBS:
        raise ValueError(f"unknown AI coach job {kind}")
    if _thread is None:
        _run(kind, kw)
        return {"queued": False, "kind": kind}
    k = _key(kind, kw)
    with _lock:
        if k in _pending:
            return {"queued": True, "kind": kind, "duplicate": True}
        _pending.add(k)
    _queue.put((kind, kw))
    return {"queued": True, "kind": kind}


def pending() -> list[str]:
    with _lock:
        return list(_pending)


def status() -> dict[str, Any]:
    with _lock:
        queued = [k for k in _pending if not k.startswith("sweep")]  # the hourly check is bookkeeping
    current = _current if _current and _current["kind"] != "sweep" else None
    return {
        "running": _thread is not None,
        "busy": current is not None or bool(queued),
        "current": current,
        "queued": len(queued),
        "recent": list(_recent),
    }


def _run(kind: str, kw: dict[str, Any]) -> None:
    global _current
    _current = {
        "activity_id": kw.get("activity_id"),
        "kind": kind,
        "label": LABELS.get(kind, kind),
        "plan_id": kw.get("plan_id"),
        "started_at": utcnow().isoformat() + "Z",
    }
    started = time.monotonic()
    ok, error = True, ""
    try:
        _job(kind)(**kw)
    except Exception as exc:  # noqa: BLE001
        ok, error = False, str(exc)[:300]
        logger.exception("AI coach job %s failed", kind)
    finally:
        if kind != "sweep":
            _recent.appendleft(
                {**_current, "ok": ok, "error": error, "seconds": round(time.monotonic() - started, 1)}
            )
        _current = None


def _loop() -> None:
    _stop.wait(60)  # let the app and the first sync settle
    if not _stop.is_set():
        submit("sweep")
    while not _stop.is_set():
        try:
            kind, kw = _queue.get(timeout=SWEEP_EVERY_S)
        except queue.Empty:
            submit("sweep")
            continue
        with _lock:
            _pending.discard(_key(kind, kw))
        if kind == "stop":
            break
        _run(kind, kw)


def start() -> None:
    global _thread
    from routepass.config import get_settings

    if _thread is not None or not get_settings().scheduler_enabled:
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="routepass-ai-coach", daemon=True)
    _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    if _thread is not None:
        _queue.put(("stop", {}))
    _thread = None


def _backing_off(key: str) -> bool:
    at = _failed_at.get(key)
    return at is not None and time.monotonic() - at < RETRY_AFTER_FAILURE_S


def _ask(
    feature: str,
    prompt: str,
    payload: dict[str, Any],
    *,
    tier: str = "fast",
    max_tokens: int = 2048,
    impatient: bool = False,
) -> tuple[dict[str, Any] | None, str, str | None]:
    """(answer, model, error). Never raises for Gemini problems."""
    try:
        res, model = gemini.generate_json(
            feature=feature,
            system_prompt=prompt,
            user_payload=payload,
            tier=tier,
            max_output_tokens=max_tokens,
        )
        return res, model, None
    except gemini.GeminiError as exc:
        return None, "", str(exc)


def _notify(db, *, title: str, body: str, kind: str, dedup: str | None = None) -> None:
    from routepass import push

    prefs = push.get_prefs(db)
    if kind == "completed" and not prefs.get("notify_completed", True):
        return
    if kind in ("adapted", "review") and not prefs.get("notify_adapted", True):
        return
    try:
        push.send_notification(db, title=title, body=body[:240], url="/training", kind=kind, dedup_key=dedup)
    except Exception:  # noqa: BLE001
        logger.exception("push failed")


def _clean(text: Any, limit: int) -> str:
    return str(text or "").strip()[:limit] if isinstance(text, str) else ""


# ── adapt ────────────────────────────────────────────────────────────────────


def adapt(
    plan_id: int, trigger: str = "manual", user_note: str = "", force: bool = False
) -> dict[str, Any] | None:
    from routepass.analysis import training

    with session_scope() as db:
        plan = db.get(TrainingPlan, plan_id)
        if plan is None:
            return None
        ctx = training.prepare_adaptation(
            db, plan, store.get_preferences(db), user_note=user_note, force=force
        )
        use_ai = training.ai_enabled(db, plan)
    if not ctx["changed"]:
        return None
    ai, err = None, None
    if use_ai:
        res, model, err = _ask(
            "plan_adapt",
            ADAPT_PROMPT,
            ctx["payload"],
            impatient=trigger == "manual" or trigger.startswith("skip_"),
        )
        if res is not None:
            ai = {"summary": res.get("summary"), "mutations": res.get("mutations"), "model": model}
    with session_scope() as db:
        plan = db.get(TrainingPlan, plan_id)
        if plan is None:
            return None
        result = training.finish_adaptation(db, plan, ctx, trigger=trigger, ai=ai, ai_error=err)
        if result["diff"]:
            _notify(db, title=f"{plan.name}: plan adapted", body=result["summary"], kind="adapted")
    return result


# ── write the coming weeks ───────────────────────────────────────────────────


def _due_weeks(db, plan: TrainingPlan, today: date) -> list[TrainingWeek]:
    horizon = (today + timedelta(days=WRITE_AHEAD_DAYS)).isoformat()
    first_open = (today - timedelta(days=6)).isoformat()  # this week counts while it lasts
    return list(
        db.scalars(
            select(TrainingWeek)
            .where(
                TrainingWeek.plan_id == plan.id,
                TrainingWeek.ai_written_at.is_(None),
                TrainingWeek.start_date <= horizon,
                TrainingWeek.start_date >= first_open,
            )
            .order_by(TrainingWeek.week_index)
            .limit(WEEKS_PER_CALL)
        )
    )


def write_weeks(plan_id: int, intro: bool = False) -> dict[str, Any] | None:
    from routepass.analysis import training
    from routepass.analysis import training_extras as tx

    today = date.today()
    with session_scope() as db:
        plan = db.get(TrainingPlan, plan_id)
        if plan is None or not training.ai_enabled(db, plan):
            return None
        weeks = _due_weeks(db, plan, today)
        if not weeks:
            return None
        week_ids = [w.id for w in weeks]
        sessions = list(
            db.scalars(
                select(TrainingSession)
                .where(
                    TrainingSession.week_id.in_(week_ids),
                    TrainingSession.status.in_(("planned", "moved")),
                    TrainingSession.sport != "rest",
                    TrainingSession.scheduled_date >= today.isoformat(),
                )
                .order_by(TrainingSession.scheduled_date)
            )
        )
        prefs = store.get_preferences(db)
        baseline = training.athlete_baseline(db, prefs, today)
        zones = tx.personal_zones(prefs.get("profile") or {}, baseline)
        payload = {
            "plan": {
                "name": plan.name,
                "type": plan.plan_type,
                "event_date": plan.event_date,
                "goal": plan.goal_spec,
                "weeks_total": len(plan.weeks),
            },
            "athlete": {
                k: baseline.get(k)
                for k in (
                    "ctl",
                    "total_weekly_hours",
                    "longest_run_28d_km",
                    "longest_bike_28d_km",
                    "median_climb_vam_mh",
                )
            },
            "zones": {k: zones.get(k) for k in ("hr", "pace", "power")},
            "weeks": [
                {
                    "week_index": w.week_index,
                    "phase": w.phase,
                    "start": w.start_date,
                    "target_hours": round(w.target_duration_s / 3600, 1),
                    "target_tss": w.target_tss,
                }
                for w in weeks
            ],
            "sessions": [
                {
                    "id": s.id,
                    "week_index": next(w.week_index for w in weeks if w.id == s.week_id),
                    "date": s.scheduled_date,
                    "sport": s.sport,
                    "type": s.session_type,
                    "priority": s.priority,
                    "zone": tx.SESSION_ZONE.get(s.session_type),
                    "minutes": round(s.target_duration_s / 60),
                    "km": s.target_distance_km,
                    "climb_m": s.target_elev_m,
                    "tss": s.target_tss,
                    "current_title": s.title,
                }
                for s in sessions
            ],
        }
        span = f"week {weeks[0].week_index}" + (f"–{weeks[-1].week_index}" if len(weeks) > 1 else "")
    key = f"write:{plan_id}"
    if not intro and _backing_off(key):
        return None
    prompt = WRITE_PROMPT.replace("{intro}", WRITE_INTRO if intro else "")
    res, model, err = _ask("plan_write", prompt, payload, tier="pro", max_tokens=8192)
    with session_scope() as db:
        plan = db.get(TrainingPlan, plan_id)
        if plan is None:
            return None
        if res is None:
            _failed_at[key] = time.monotonic()
            if intro:
                db.add(
                    PlanAdaptation(
                        plan_id=plan_id,
                        trigger="ai_write",
                        model_used="deterministic",
                        summary=f"The AI coach could not write {span} yet; it tries again later.",
                        diff=[],
                        ai_error=(err or "")[:300],
                    )
                )
            return {"ok": False, "error": err}
        _failed_at.pop(key, None)
        by_id = {
            s.id: s for s in db.scalars(select(TrainingSession).where(TrainingSession.week_id.in_(week_ids)))
        }
        written = 0
        for item in res.get("sessions") or []:
            if not isinstance(item, dict):
                continue
            s = by_id.get(training._as_int(item.get("id")))
            if s is None or s.status not in ("planned", "moved"):
                continue
            if title := _clean(item.get("title"), 120):
                s.title = title
            if desc := _clean(item.get("description"), 800):
                s.description = desc
            steps = item.get("workout_steps")
            if isinstance(steps, list) and steps:
                s.workout_steps = [str(x).strip()[:160] for x in steps[:8] if str(x).strip()]
            written += 1
        focus = res.get("week_focus") or {}
        for w in db.scalars(select(TrainingWeek).where(TrainingWeek.id.in_(week_ids))):
            if isinstance(focus, dict) and (f := _clean(focus.get(str(w.week_index)), 300)):
                w.coach_focus = f
            w.ai_written_at = utcnow()
        if intro and (cs := _clean(res.get("coach_summary"), 900)):
            plan.coach_summary = cs
        db.add(
            PlanAdaptation(
                plan_id=plan_id,
                trigger="ai_write",
                model_used=model,
                summary=f"Wrote {written} session{'s' if written != 1 else ''} for {span}.",
                diff=[],
            )
        )
        db.flush()
        training._maybe_sync_calendar(db, plan)
    return {"ok": True, "written": written}


# ── feedback on a workout ────────────────────────────────────────────────────


def feedback(session_id: int) -> dict[str, Any] | None:
    from routepass.analysis import training
    from routepass.analysis import training_extras as tx

    key = f"feedback:{session_id}"
    if _backing_off(key):
        return None
    with session_scope() as db:
        s = db.get(TrainingSession, session_id)
        if s is None or s.matched_activity_id is None or s.coach_feedback:
            return None
        a = db.get(Activity, s.matched_activity_id)
        if a is None:
            return None
        prefs = store.get_preferences(db)
        zones = tx.personal_zones(prefs.get("profile") or {}, training.athlete_baseline(db, prefs))
        track = db.scalar(select(Track).where(Track.activity_id == a.id).limit(1))
        detail = (track.detail if track else None) or {}

        def zone_minutes(z: dict[str, Any] | None) -> dict[str, float] | None:
            if not z or not z.get("seconds"):
                return None
            return {f"Z{i + 1}": round(sec / 60, 1) for i, sec in enumerate(z["seconds"])}

        payload = {
            "planned": {
                "sport": s.sport,
                "type": s.session_type,
                "priority": s.priority,
                "title": s.title,
                "target_zone": tx.SESSION_ZONE.get(s.session_type),
                "minutes": round(s.target_duration_s / 60),
                "km": s.target_distance_km,
                "climb_m": s.target_elev_m,
                "tss": s.target_tss,
                "steps": s.workout_steps or [],
            },
            "recorded": {
                "sport": a.sport,
                "minutes": round((a.moving_time_s or 0) / 60),
                "km": round((a.distance_m or 0) / 1000, 1),
                "climb_m": a.elevation_gain_m,
                "avg_hr": a.avg_hr,
                "max_hr": a.max_hr,
                "avg_power": a.avg_power,
                "normalized_power": a.normalized_power,
                "load": a.load,
                "load_method": a.load_method,
                "minutes_in_hr_zones": zone_minutes(detail.get("hr_zones")),
                "minutes_in_power_zones": zone_minutes(detail.get("power_zones")),
            },
            "compliance_percent": s.compliance_score,
            "athlete": {"rpe": s.rpe, "felt": s.feel, "note": s.feedback_note},
            "personal_zones": {k: zones.get(k) for k in ("hr", "pace", "power")},
        }
        title = s.title
    res, _model, err = _ask("session_feedback", FEEDBACK_PROMPT, payload, max_tokens=1024)
    with session_scope() as db:
        s = db.get(TrainingSession, session_id)
        text = _clean((res or {}).get("feedback"), 600)
        if s is None:
            return None
        if not text:
            _failed_at[key] = time.monotonic()
            _notify(
                db,
                title=f"Workout synced: {title}",
                body="Matched to your training plan.",
                kind="completed",
                dedup=f"done-{session_id}",
            )
            return {"ok": False, "error": err}
        s.coach_feedback = text
        _notify(db, title=f"Coach: {title}", body=text, kind="completed", dedup=f"done-{session_id}")
    return {"ok": True}


# ── weekly review ────────────────────────────────────────────────────────────


def _review_week_due(plan: TrainingPlan, now: datetime) -> date | None:
    """Monday of the week to review: the current one from Sunday 18:00, otherwise last week."""
    from routepass.analysis import training

    today = now.date()
    monday = today - timedelta(days=today.weekday())
    week = monday if (today.weekday() == 6 and now.hour >= 18) else monday - timedelta(days=7)
    if week + timedelta(days=6) < training.plan_first_day(plan):
        return None
    if week.isoformat() > plan.event_date:
        return None
    return week


def _week_numbers(db, plan: TrainingPlan, monday: date) -> dict[str, Any]:
    end = monday + timedelta(days=7)
    sessions = list(
        db.scalars(
            select(TrainingSession).where(
                TrainingSession.plan_id == plan.id,
                TrainingSession.scheduled_date >= monday.isoformat(),
                TrainingSession.scheduled_date < end.isoformat(),
                TrainingSession.sport != "rest",
            )
        )
    )
    acts = list(
        db.scalars(
            select(Activity).where(
                Activity.start_time >= datetime.combine(monday, datetime.min.time()),
                Activity.start_time < datetime.combine(end, datetime.min.time()),
            )
        )
    )
    done = [s for s in sessions if s.status in ("completed", "partial") or s.matched_activity_id]
    comp = [s.compliance_score for s in done if s.compliance_score is not None]
    return {
        "week_start": monday.isoformat(),
        "planned": len(sessions),
        "done": len(done),
        "missed": sum(1 for s in sessions if s.status == "missed"),
        "skipped": sum(1 for s in sessions if s.status == "skipped"),
        "planned_load": round(sum(s.target_tss or 0 for s in sessions)),
        "actual_load": round(sum(a.load or 0 for a in acts)),
        "planned_hours": round(sum(s.target_duration_s or 0 for s in sessions) / 3600, 1),
        "actual_hours": round(sum(a.moving_time_s or 0 for a in acts) / 3600, 1),
        "avg_compliance": round(sum(comp) / len(comp)) if comp else None,
        "activities": len(acts),
        "sessions": [
            {
                "date": s.scheduled_date,
                "title": s.title,
                "type": s.session_type,
                "priority": s.priority,
                "status": s.status,
                "compliance": s.compliance_score,
                "felt": s.feel,
                "rpe": s.rpe,
                "note": s.feedback_note,
            }
            for s in sorted(sessions, key=lambda x: x.scheduled_date)
        ],
    }


def _plain_review(n: dict[str, Any]) -> dict[str, Any]:
    pct = round(n["actual_load"] / n["planned_load"] * 100) if n["planned_load"] else None
    headline = f"{n['done']} of {n['planned']} sessions done" + (
        f", {pct}% of the planned load." if pct is not None else "."
    )
    went, watch = [], []
    if n["planned"] and n["done"] == n["planned"]:
        went.append("Every planned session done.")
    if n["avg_compliance"] and n["avg_compliance"] >= 85:
        went.append(f"Sessions matched their targets well ({n['avg_compliance']}% on average).")
    if n["missed"]:
        watch.append(f"{n['missed']} session{'s' if n['missed'] > 1 else ''} missed.")
    if pct is not None and pct > 125:
        watch.append("Load well above plan — keep easy days easy.")
    hard = sum(1 for s in n["sessions"] if s["felt"] == "hard")
    if hard >= 2:
        watch.append(f"{hard} sessions felt too hard.")
    return {"headline": headline, "went_well": went, "watch": watch, "next_week": ""}


def weekly_review(plan_id: int, week_start: str) -> dict[str, Any] | None:
    from routepass.analysis import training

    monday = date.fromisoformat(week_start)
    with session_scope() as db:
        plan = db.get(TrainingPlan, plan_id)
        if plan is None or _has_review(db, plan_id, week_start):
            return None
        numbers = _week_numbers(db, plan, monday)
        if not numbers["planned"] and not numbers["activities"]:
            return None
        nxt = db.scalar(
            select(TrainingWeek).where(
                TrainingWeek.plan_id == plan_id,
                TrainingWeek.start_date == (monday + timedelta(days=7)).isoformat(),
            )
        )
        next_week = None
        if nxt is not None:
            next_week = {
                "phase": nxt.phase,
                "target_hours": round(nxt.target_duration_s / 3600, 1),
                "target_tss": nxt.target_tss,
                "focus": nxt.coach_focus,
                "key_sessions": [s.title for s in nxt.sessions if s.priority == "key"],
            }
        load = training.athlete_baseline(db, store.get_preferences(db))
        payload = {
            "plan": plan.name,
            "event_date": plan.event_date,
            "week": numbers,
            "now": {k: load.get(k) for k in ("ctl", "atl", "tsb", "acwr")},
            "next_week": next_week,
        }
        use_ai = training.ai_enabled(db, plan)
    review, model, err = _plain_review(numbers), "deterministic", None
    if use_ai:
        res, m, err = _ask("weekly_review", REVIEW_PROMPT, payload, max_tokens=1536)
        if res is not None and _clean(res.get("headline"), 300):
            review = {
                "headline": _clean(res.get("headline"), 300),
                "went_well": [_clean(x, 200) for x in (res.get("went_well") or [])[:3] if _clean(x, 200)],
                "watch": [_clean(x, 200) for x in (res.get("watch") or [])[:3] if _clean(x, 200)],
                "next_week": _clean(res.get("next_week"), 400),
            }
            model = m
    with session_scope() as db:
        if _has_review(db, plan_id, week_start):
            return None
        stats = {k: v for k, v in numbers.items() if k != "sessions"}
        db.add(
            PlanAdaptation(
                plan_id=plan_id,
                trigger="weekly_review",
                model_used=model,
                summary=review["headline"],
                diff=[],
                details={**review, "week_start": week_start, "stats": stats},
                ai_error=(err or None) and err[:300],
            )
        )
        plan = db.get(TrainingPlan, plan_id)
        _notify(
            db,
            title=f"Weekly review: {plan.name if plan else 'training'}",
            body=review["headline"],
            kind="review",
            dedup=f"review-{plan_id}-{week_start}",
        )
    return review


def _has_review(db, plan_id: int, week_start: str) -> bool:
    for d in db.scalars(
        select(PlanAdaptation.details).where(
            PlanAdaptation.plan_id == plan_id, PlanAdaptation.trigger == "weekly_review"
        )
    ):
        if (d or {}).get("week_start") == week_start:
            return True
    return False


# ── sweep: decide what is due ────────────────────────────────────────────────


def sweep() -> None:
    """Hourly and after each sync: the weekly review, weeks to write and workouts to comment on."""
    from routepass.analysis import training

    now = datetime.now()
    with session_scope() as db:
        plans = list(db.scalars(select(TrainingPlan).where(TrainingPlan.status == "active")))
        todo: list[tuple[str, dict[str, Any]]] = []
        for plan in plans:
            week = _review_week_due(plan, now)
            if week is not None and not _has_review(db, plan.id, week.isoformat()):
                todo.append(("weekly_review", {"plan_id": plan.id, "week_start": week.isoformat()}))
            if not training.ai_enabled(db, plan):
                continue
            if _due_weeks(db, plan, now.date()):
                todo.append(("write_weeks", {"plan_id": plan.id}))
            since = (now.date() - timedelta(days=FEEDBACK_DAYS)).isoformat()
            for sid in db.scalars(
                select(TrainingSession.id)
                .where(
                    TrainingSession.plan_id == plan.id,
                    TrainingSession.matched_activity_id.is_not(None),
                    TrainingSession.coach_feedback.is_(None),
                    TrainingSession.scheduled_date >= since,
                )
                .order_by(TrainingSession.scheduled_date.desc())
                .limit(FEEDBACK_PER_SWEEP)
            ):
                if not _backing_off(f"feedback:{sid}"):
                    todo.append(("feedback", {"session_id": sid}))
    with session_scope() as db:
        from routepass.ai import fitness_coach

        if fitness_coach.report_due(db, now.date()) and not _backing_off("fitness_report"):
            todo.append(("fitness_report", {"trigger": "monthly"}))
    for kind, kw in todo:
        submit(kind, **kw)


JOBS = {
    "adapt": adapt,
    "write_weeks": write_weeks,
    "feedback": feedback,
    "weekly_review": weekly_review,
    "sweep": sweep,
}

# Fitness jobs live in fitness_coach, which imports this module: looked up when they run.
FITNESS_JOBS = ("fitness_report", "activity_analysis")


def _job(kind: str):
    if kind in FITNESS_JOBS:
        from routepass.ai import fitness_coach

        return getattr(fitness_coach, kind)
    return JOBS[kind]

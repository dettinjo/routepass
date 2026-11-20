"""AI coach jobs about fitness: the fitness report and the analysis of one activity.

As with the plan jobs, every number comes from routepass.analysis (fitness estimates, load, volume,
track metrics); the model explains them. Reports are kept in the settings store (newest first);
an activity's analysis in activities.coach_analysis.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from routepass import store
from routepass.ai.coach import _ask, _clean, _notify
from routepass.analysis import fitness, insights
from routepass.db import session_scope
from routepass.models import Activity, Track, TrainingPlan, TrainingSession, TrainingWeek
from routepass.timeutil import utcnow

REPORTS_KEY = "coach.fitness_reports"
KEEP_REPORTS = 12
REPORT_EVERY_DAYS = 30

REPORT_PROMPT = (
    "You are an endurance coach writing a fitness report for one athlete. You get estimates computed "
    "from their recordings (cycling threshold power and VO2max estimated from climbs or measured "
    "power, running VO2max and race predictions from best efforts, durability from heart-rate drift), "
    "training load (fitness CTL, fatigue ATL, form TSB, six weeks ago, a year ago, six weeks ahead at "
    "the current load), month-by-month trends, volume per sport for the last 90 days against the 90 "
    "before, data quality, the active training plan if any, and the previous report. Each estimate "
    "has a basis and a confidence; say so when a number is a rough estimate, and never invent numbers "
    'or precision. Reply with JSON: {"headline": one sentence, "summary": 2-3 sentences on the '
    'current fitness level in plain words, "strengths": up to 3 short points, "limiters": up to 3 '
    'short points, "changes": 1-2 sentences on what changed since the previous report or over the '
    'last months, "focus": up to 3 concrete things for the next 4 weeks}.'
)

ACTIVITY_PROMPT = (
    "You are an endurance coach analysing one recorded activity. You get its numbers (distance, time, "
    "climbing, speed, heart rate and power when recorded, load), the climbs with estimated or measured "
    "power, the splits, heart-rate drift and time in zones when known, how it compares with the "
    "athlete's similar activities of the last year, their current fitness estimates and, if it was "
    "a planned session, what was planned. Write for the athlete: what kind of session it was, how it "
    "was paced, what stands out and how it compares. Use only the numbers given. Reply with JSON: "
    '{"headline": one sentence, "points": 3-5 short observations, "compared": one sentence on '
    'how it compares with similar activities, "next_time": one concrete tip}.'
)


# ── fitness report ───────────────────────────────────────────────────────────


def reports(db) -> list[dict[str, Any]]:
    return list(store.get_value(db, REPORTS_KEY) or [])


def report_due(db, today: date) -> bool:
    rs = reports(db)
    if not rs:
        return db.scalar(select(Activity.id).limit(1)) is not None
    last = date.fromisoformat(rs[0]["created_at"][:10])
    if rs[0].get("ai_error") and (today - last).days >= 1:
        return True  # the AI was unavailable last time: try again the next day
    return (today - last).days >= REPORT_EVERY_DAYS


def _volume(db, start: date, end: date) -> dict[str, Any]:
    t = insights.totals(db, insights.Filters(start=start, end=end))
    return {
        fam: {
            "count": v.get("count"),
            "hours": round((v.get("moving_time_s") or 0) / 3600, 1),
            "km": round((v.get("distance_m") or 0) / 1000),
            "climb_m": round(v.get("elevation_gain_m") or 0),
        }
        for fam, v in t["by_family"].items()
    }


def _plan_context(db, today: date) -> dict[str, Any] | None:
    plan = db.scalar(
        select(TrainingPlan).where(TrainingPlan.status == "active").order_by(TrainingPlan.id.desc())
    )
    if plan is None:
        return None
    monday = (today - timedelta(days=today.weekday())).isoformat()
    week = db.scalar(
        select(TrainingWeek).where(TrainingWeek.plan_id == plan.id, TrainingWeek.start_date == monday)
    )
    return {
        "name": plan.name,
        "type": plan.plan_type,
        "event_date": plan.event_date,
        "days_to_go": (date.fromisoformat(plan.event_date) - today).days,
        "phase_now": week.phase if week else None,
        "goal": plan.goal_spec,
    }


def _snapshot(est: dict[str, Any]) -> dict[str, Any]:
    """The few numbers a later report compares against."""
    c, r, ld = est.get("cycling") or {}, est.get("running") or {}, est.get("load") or {}
    return {
        "ctl": ld.get("ctl"),
        "tsb": ld.get("tsb"),
        "cycling_threshold_wkg": c.get("threshold_wkg"),
        "cycling_vo2max": c.get("vo2max"),
        "running_vo2max": r.get("vo2max"),
        "running_threshold_pace_s_per_km": r.get("threshold_pace_s_per_km"),
    }


def _plain_report(est: dict[str, Any], prev: dict[str, Any] | None) -> dict[str, Any]:
    c, r, ld = est.get("cycling") or {}, est.get("running") or {}, est.get("load") or {}
    strengths, limiters, focus = [], [], []
    if c.get("threshold_wkg"):
        strengths.append(
            f"Cycling threshold about {c['threshold_wkg']} W/kg ({'measured' if c.get('basis') == 'power' else 'estimated from climbs'})."
        )
    if r.get("vo2max"):
        strengths.append(
            f"Running VO2max about {r['vo2max']} from your best {r['from_effort']['distance_m'] / 1000:g} km."
        )
    ch = ld.get("change_6w_pct")
    if ch is not None and ch <= -10:
        limiters.append(f"Fitness down {-ch} % over six weeks.")
        focus.append("Rebuild consistency: three to four sessions a week before adding intensity.")
    if (est.get("durability") or {}).get("missing"):
        limiters.append("No heart rate on long sessions, so durability and load are estimated.")
    changes = ""
    if prev:
        p = prev.get("numbers") or {}
        if p.get("ctl") is not None and ld.get("ctl") is not None:
            changes = f"Fitness {p['ctl']:.0f} → {ld['ctl']:.0f} since {prev['created_at'][:10]}."
    return {
        "headline": est.get("state") or "Fitness report",
        "summary": est.get("state") or "",
        "strengths": strengths[:3],
        "limiters": limiters[:3],
        "changes": changes,
        "focus": focus[:3],
    }


def fitness_report(trigger: str = "monthly") -> dict[str, Any] | None:
    from routepass.analysis import training

    today = date.today()
    with session_scope() as db:
        est = fitness.estimates(db, today)
        prev = (reports(db) or [None])[0]
        payload = {
            "today": today.isoformat(),
            "estimates": {k: v for k, v in est.items() if k not in ("date",)},
            "trend_by_month": fitness.trend(db, 12, today),
            "volume_last_90d": _volume(db, today - timedelta(days=90), today),
            "volume_previous_90d": _volume(db, today - timedelta(days=180), today - timedelta(days=91)),
            "data_quality": {k: v for k, v in insights.data_quality(db, today).items() if k != "suggestions"},
            "plan": _plan_context(db, today),
            "previous_report": (
                {
                    "date": prev["created_at"][:10],
                    "headline": prev.get("headline"),
                    "numbers": prev.get("numbers"),
                }
                if prev
                else None
            ),
        }
        use_ai = training.ai_enabled(db)
    report, model, err = _plain_report(est, prev), "deterministic", None
    if use_ai:
        res, m, err = _ask(
            "fitness_report", REPORT_PROMPT, payload, max_tokens=3072, impatient=trigger == "manual"
        )
        if res is not None and _clean(res.get("headline"), 300):
            report = {
                "headline": _clean(res.get("headline"), 300),
                "summary": _clean(res.get("summary"), 900),
                "strengths": [x for x in (_clean(i, 220) for i in (res.get("strengths") or [])[:3]) if x],
                "limiters": [x for x in (_clean(i, 220) for i in (res.get("limiters") or [])[:3]) if x],
                "changes": _clean(res.get("changes"), 500),
                "focus": [x for x in (_clean(i, 220) for i in (res.get("focus") or [])[:3]) if x],
            }
            model = m
    entry = {
        **report,
        "created_at": utcnow().isoformat() + "Z",
        "trigger": trigger,
        "model": model,
        "ai_error": (err or None) and err[:300],
        "numbers": _snapshot(est),
    }
    with session_scope() as db:
        store.set_value(db, REPORTS_KEY, [entry, *reports(db)][:KEEP_REPORTS])
        if trigger == "monthly":
            _notify(
                db,
                title="Your fitness report",
                body=entry["headline"],
                kind="review",
                dedup=f"fitness-{today:%Y-%m}",
            )
    return entry


# ── one activity ─────────────────────────────────────────────────────────────


def _similar(db, a: Activity) -> dict[str, Any] | None:
    if not a.distance_m:
        return None
    since = a.start_time - timedelta(days=365)
    rows = list(
        db.execute(
            select(
                Activity.avg_speed_ms, Activity.elevation_gain_m, Activity.avg_hr, Activity.distance_m
            ).where(
                Activity.family == a.family,
                Activity.id != a.id,
                Activity.start_time >= since,
                Activity.start_time <= a.start_time + timedelta(days=1),
                Activity.distance_m.between(a.distance_m * 0.75, a.distance_m * 1.25),
            )
        )
    )
    speeds = [r.avg_speed_ms for r in rows if r.avg_speed_ms]
    if len(speeds) < 3 or not a.avg_speed_ms:
        return {"count": len(rows)}
    faster = sum(1 for v in speeds if v > a.avg_speed_ms)
    return {
        "count": len(rows),
        "median_speed_kmh": round(statistics.median(speeds) * 3.6, 1),
        "this_speed_kmh": round(a.avg_speed_ms * 3.6, 1),
        "rank": f"{faster + 1} of {len(speeds) + 1} by average speed",
        "median_climb_m": round(statistics.median([r.elevation_gain_m or 0 for r in rows])),
        "median_avg_hr": round(statistics.median([r.avg_hr for r in rows if r.avg_hr]))
        if any(r.avg_hr for r in rows)
        else None,
    }


def activity_analysis(activity_id: int) -> dict[str, Any] | None:
    from routepass.analysis import training_extras as tx

    with session_scope() as db:
        a = db.get(Activity, activity_id)
        if a is None:
            return None
        prefs = store.get_preferences(db)
        profile = prefs.get("profile") or {}
        kg = profile.get("weight_kg")
        track = db.scalar(select(Track).where(Track.activity_id == a.id).limit(1))
        detail = (track.detail if track else None) or {}
        climbs = sorted(detail.get("climbs") or [], key=lambda c: -(c.get("gain_m") or 0))[:5]
        if a.family == "ride" and kg and not a.avg_power:
            for c in climbs:
                if (c.get("grade_pct") or 0) >= 3 and (c.get("duration_s") or 0) >= 120:
                    p = fitness.climb_power(c, kg)
                    c["estimated_power_w"] = round(p) if p else None
        splits = detail.get("splits") or []
        if len(splits) > 24:
            step = len(splits) / 24
            splits = [splits[int(i * step)] for i in range(24)]

        def minutes(z: dict[str, Any] | None) -> dict[str, float] | None:
            return (
                {f"Z{i + 1}": round(s / 60, 1) for i, s in enumerate(z["seconds"])}
                if z and z.get("seconds")
                else None
            )

        est = fitness.estimates(db)
        session = db.scalar(select(TrainingSession).where(TrainingSession.matched_activity_id == a.id))
        payload = {
            "activity": {
                "name": a.name,
                "sport": a.sport,
                "date": (a.start_local or a.start_time).isoformat(),
                "km": round((a.distance_m or 0) / 1000, 2),
                "moving_min": round((a.moving_time_s or 0) / 60),
                "elapsed_min": round((a.elapsed_time_s or 0) / 60),
                "climb_m": a.elevation_gain_m,
                "avg_kmh": round((a.avg_speed_ms or 0) * 3.6, 1),
                "max_kmh": round((a.max_speed_ms or 0) * 3.6, 1),
                "avg_hr": a.avg_hr,
                "max_hr": a.max_hr,
                "avg_power": a.avg_power,
                "normalized_power": a.normalized_power,
                "load": a.load,
                "load_method": a.load_method,
                "effort_rating": a.rpe,
                "indoor": a.trainer,
                "description": (a.description or "")[:300],
            },
            "climbs": climbs,
            "splits": splits,
            "split_m": detail.get("split_m"),
            "hr_drift": detail.get("decoupling"),
            "minutes_in_hr_zones": minutes(detail.get("hr_zones")),
            "minutes_in_power_zones": minutes(detail.get("power_zones")),
            "best_times_in_activity": detail.get("best_times"),
            "similar_last_year": _similar(db, a),
            "athlete": {
                "weight_kg": kg,
                "cycling": {
                    k: (est["cycling"] or {}).get(k)
                    for k in ("threshold_w", "threshold_wkg", "basis", "confidence")
                },
                "running": {k: (est["running"] or {}).get(k) for k in ("vo2max", "threshold_pace_s_per_km")},
                "zones": tx.personal_zones(profile, {}),
            },
            "planned_session": (
                {
                    "type": session.session_type,
                    "title": session.title,
                    "minutes": round(session.target_duration_s / 60),
                    "km": session.target_distance_km,
                    "tss": session.target_tss,
                }
                if session
                else None
            ),
        }
    res, model, err = _ask("activity_analysis", ACTIVITY_PROMPT, payload, max_tokens=2048, impatient=True)
    now = utcnow().isoformat() + "Z"
    if res is not None and _clean(res.get("headline"), 300):
        out = {
            "headline": _clean(res.get("headline"), 300),
            "points": [x for x in (_clean(i, 260) for i in (res.get("points") or [])[:5]) if x],
            "compared": _clean(res.get("compared"), 300),
            "next_time": _clean(res.get("next_time"), 300),
            "model": model,
            "created_at": now,
        }
    else:
        out = {"error": err or "The AI coach gave no usable answer", "created_at": now}
    with session_scope() as db:
        a = db.get(Activity, activity_id)
        if a is not None:
            prev = a.coach_analysis or {}
            # a failed retry keeps the earlier analysis and only notes the error
            a.coach_analysis = (
                {**prev, "error": out["error"], "error_at": now}
                if "error" in out and prev.get("headline")
                else out
            )
    return out

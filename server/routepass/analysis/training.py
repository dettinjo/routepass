"""Multi-sport adaptive Training Plan engine (Running, Trail, Cycling, Triathlon).

Hybrid deterministic + Gemini architecture:
- Deterministic Python handles all sports-science math: periodization skeleton,
  activity-to-session matching, alignment scoring, Banister CTL trajectory
  simulation, and multi-sport race finish-time predictions (0 tokens).
- Gemini (`gemini-2.5-pro` for initial plan enrichment, `gemini-2.5-flash` for
  ongoing micro-adaptations) provides coaching judgment within strict JSON
  schemas, state-hash deduplication, and monthly USD budget guardrails.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from routepass.ai import gemini
from routepass.analysis import insights, trail
from routepass.models import (
    Activity,
    Effort,
    PlanAdaptation,
    TrainingPlan,
    TrainingSession,
    TrainingWeek,
)

logger = logging.getLogger(__name__)

PLAN_TYPES = ("trail_run", "road_run", "cycling", "triathlon", "duathlon", "base_build")

_SPORT_FAMILY_MATCH: dict[str, set[str]] = {
    "run": {"run"},
    "trail_run": {"run"},
    "bike": {"ride"},
    "swim": {"water"},
    "brick": {"ride", "run"},
    "strength": {"other", "walk"},
}

_DEFAULT_DISCIPLINES: dict[str, list[str]] = {
    "trail_run": ["trail_run"],
    "road_run": ["run"],
    "cycling": ["bike"],
    "triathlon": ["swim", "bike", "run"],
    "duathlon": ["run", "bike"],
    "base_build": ["run", "bike"],
}

_PLAN_SYSTEM_PROMPT = (
    "You are an elite endurance sports scientist and coach specializing in trail running, "
    "road running, cycling, and triathlon. Given an athlete's baseline metrics, target race, "
    "and an initial 4-week schedule skeleton, refine the upcoming sessions with specific, "
    "practical workout titles, concise descriptions, and structured workout_steps "
    "(warmup, main set, cooldown with HR/GAP/FTP/CSS zones). Keep total weekly TSS within "
    "+/-10% of the skeleton. Return strictly valid JSON with keys: "
    "'coach_summary' (string, 2-3 sentences), 'week_focuses' (object mapping week_index string "
    "to short focus string), and 'sessions' (array of objects with 'temp_id', 'title', "
    "'description', 'workout_steps' (array of short strings))."
)

_ADAPT_SYSTEM_PROMPT = (
    "You are an adaptive endurance coach. Review the athlete's recent completed/missed sessions, "
    "current fatigue (CTL/ATL/TSB/ACWR), optional athlete feedback, and upcoming 14-day schedule. "
    "Propose minimal, smart adjustments: if a key session was missed, reschedule or trim it onto "
    "an open/easy day without stacking two high-intensity sessions back-to-back (except trail "
    "back-to-back aerobic weekends). If fatigue is high (TSB < -20 or ACWR > 1.35) or athlete "
    "reports tiredness, scale down intensity/duration. Return strictly valid JSON: "
    "{'summary': string (1-2 sentences), 'mutations': [{'session_id': int, "
    "'action': 'reschedule'|'adjust_load'|'swap_type'|'skip', 'new_date': 'YYYY-MM-DD' (optional), "
    "'duration_scale': float 0.5-1.25 (optional), 'new_title': string (optional), "
    "'new_description': string (optional), 'new_session_type': string (optional), "
    "'note': string}]}. Return empty mutations array if the current plan is already optimal."
)


def _iso(d: date) -> str:
    return d.isoformat()


def _parse_date(s: str | None, fallback: date) -> date:
    if not s:
        return fallback
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return fallback


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _activity_matches_sport(act: Activity, session_sport: str) -> bool:
    if session_sport == "rest":
        return False
    if session_sport == "swim":
        return act.family == "water" or "swim" in (act.sport or "").lower()
    allowed = _SPORT_FAMILY_MATCH.get(session_sport, {act.family})
    return act.family in allowed


def athlete_baseline(db: Session, prefs: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Compute current multi-sport fitness & threshold snapshot from recorded activities."""
    today = today or date.today()
    load = insights.training_load(db, today)
    cur = load.get("current") or {}
    ctl = float(cur.get("ctl") or 0.0)
    atl = float(cur.get("atl") or 0.0)
    tsb = float(cur.get("tsb") or 0.0)
    acwr = round(atl / ctl, 2) if ctl >= 5 else None

    since = today - timedelta(days=28)
    acts = list(
        db.scalars(
            select(Activity).where(Activity.start_time >= since.isoformat())
        )
    )
    disc_stats: dict[str, dict[str, float]] = {
        "run": {"hours": 0.0, "km": 0.0, "elev_m": 0.0, "count": 0},
        "bike": {"hours": 0.0, "km": 0.0, "elev_m": 0.0, "count": 0},
        "swim": {"hours": 0.0, "km": 0.0, "elev_m": 0.0, "count": 0},
    }
    longest_run_km = 0.0
    longest_bike_km = 0.0
    for a in acts:
        hrs = float(a.moving_time_s or 0.0) / 3600.0
        km = float(a.distance_m or 0.0) / 1000.0
        elev = float(a.elevation_gain_m or 0.0)
        if a.family == "run":
            d = disc_stats["run"]
            longest_run_km = max(longest_run_km, km)
        elif a.family == "ride":
            d = disc_stats["bike"]
            longest_bike_km = max(longest_bike_km, km)
        elif a.family == "water" or "swim" in (a.sport or "").lower():
            d = disc_stats["swim"]
        else:
            continue
        d["hours"] += hrs
        d["km"] += km
        d["elev_m"] += elev
        d["count"] += 1

    weekly_avg = {
        k: {
            "hours": round(v["hours"] / 4.0, 2),
            "km": round(v["km"] / 4.0, 1),
            "elev_m": round(v["elev_m"] / 4.0, 0),
            "sessions": round(v["count"] / 4.0, 1),
        }
        for k, v in disc_stats.items()
    }

    tb = trail._athlete_trail_baseline(db)
    gap_ms = tb.get("median_gap_ms")
    vam = tb.get("median_climb_vam_mh")
    profile = prefs.get("profile") or {}
    ftp = profile.get("ftp")
    if not ftp:
        best_20m = db.scalar(
            select(Effort.value)
            .where(Effort.kind == "power", Effort.key == 1200)
            .order_by(Effort.value.desc())
            .limit(1)
        )
        if best_20m:
            ftp = round(float(best_20m) * 0.95)

    weight_kg = float(profile.get("weight_kg") or 72.0)
    return {
        "as_of": _iso(today),
        "ctl": round(ctl, 1),
        "atl": round(atl, 1),
        "tsb": round(tsb, 1),
        "acwr": acwr,
        "weekly_avg": weekly_avg,
        "total_weekly_hours": round(sum(v["hours"] for v in weekly_avg.values()), 2),
        "median_gap_ms": round(gap_ms, 3) if gap_ms else None,
        "median_climb_vam_mh": round(vam, 0) if vam else None,
        "ftp_w": float(ftp) if ftp else None,
        "weight_kg": weight_kg,
        "swim_css_s_per_100m": 125.0,
        "longest_run_28d_km": round(longest_run_km, 1),
        "longest_bike_28d_km": round(longest_bike_km, 1),
    }


def _phase_schedule(num_weeks: int) -> list[str]:
    """Assign periodized training phases across `num_weeks` ending on race week."""
    if num_weeks <= 1:
        return ["race_week"]
    phases: list[str] = []
    taper_weeks = 2 if num_weeks >= 8 else (1 if num_weeks >= 4 else 0)
    peak_weeks = 2 if num_weeks >= 10 else (1 if num_weeks >= 5 else 0)
    pre_weeks = max(0, num_weeks - 1 - taper_weeks - peak_weeks)
    base_weeks = max(1, pre_weeks // 2) if pre_weeks >= 2 else pre_weeks
    build_weeks = max(0, pre_weeks - base_weeks)

    for i in range(base_weeks):
        phases.append("recovery" if (i + 1) % 4 == 0 and i < base_weeks - 1 else "base")
    for i in range(build_weeks):
        phases.append("recovery" if (base_weeks + i + 1) % 4 == 0 and i < build_weeks - 1 else "build")
    phases.extend(["peak"] * peak_weeks)
    phases.extend(["taper"] * taper_weeks)
    phases.append("race_week")
    return phases[:num_weeks]


def _phase_load_multiplier(phase: str, idx: int, total: int) -> float:
    prog = idx / max(1, total - 1)
    if phase == "base":
        return 0.72 + 0.16 * prog
    if phase == "recovery":
        return 0.68
    if phase == "build":
        return 0.85 + 0.18 * prog
    if phase == "peak":
        return 1.05
    if phase == "taper":
        return 0.62
    return 0.42  # race_week


def _build_skeleton(
    *,
    plan_type: str,
    name: str,
    start_date: date,
    event_date: date,
    goal_spec: dict[str, Any],
    schedule_prefs: dict[str, Any],
    baseline: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build deterministic periodized weeks and sessions."""
    w1 = _monday_of(start_date)
    ev_mon = _monday_of(event_date)
    num_weeks = max(2, min(28, ((ev_mon - w1).days // 7) + 1))
    phases = _phase_schedule(num_weeks)

    max_hours = float(schedule_prefs.get("max_weekly_hours") or max(5.0, baseline["total_weekly_hours"] * 1.25))
    max_hours = max(3.5, min(22.0, max_hours))
    pref_slot = str(schedule_prefs.get("preferred_slot") or "evening")
    rest_days = set(int(x) for x in (schedule_prefs.get("rest_days") or [0]))  # 0=Mon..6=Sun
    if len(rest_days) >= 5:
        rest_days = {0, 4}

    targets = goal_spec.get("targets") or {}
    run_km_goal = float(targets.get("run_km") or (50.0 if plan_type == "trail_run" else 21.1))
    run_elev_goal = float(targets.get("run_elev_m") or (2000.0 if plan_type == "trail_run" else 150.0))
    bike_km_goal = float(targets.get("bike_km") or (120.0 if plan_type == "cycling" else 90.0))
    bike_elev_goal = float(targets.get("bike_elev_m") or 1200.0)
    swim_km_goal = float(targets.get("swim_km") or 1.9)

    weeks_out: list[dict[str, Any]] = []
    sessions_out: list[dict[str, Any]] = []
    temp_id = 1

    # Typical weekly session templates per plan_type: (weekday_offset, sport, session_type, priority, share, title, desc)
    for w_idx in range(1, num_weeks + 1):
        w_start = w1 + timedelta(days=(w_idx - 1) * 7)
        phase = phases[w_idx - 1]
        mult = _phase_load_multiplier(phase, w_idx - 1, num_weeks)
        week_hours = round(max_hours * mult, 2)
        week_tss = round(week_hours * 58.0, 0)

        templates = _weekly_templates(plan_type, phase, run_km_goal, run_elev_goal, bike_km_goal, bike_elev_goal, swim_km_goal)
        # Filter / shift sessions off rest_days (except race day)
        used_days: set[int] = set()
        week_sessions: list[dict[str, Any]] = []

        for day_pref, sport, stype, prio, share, title, desc, steps in templates:
            if phase == "race_week" and stype == "race":
                s_date = event_date
            else:
                d_off = day_pref
                if d_off in rest_days or d_off in used_days:
                    for cand in range(7):
                        if cand not in rest_days and cand not in used_days:
                            d_off = cand
                            break
                s_date = w_start + timedelta(days=d_off)
                if phase == "race_week" and s_date >= event_date:
                    continue
                used_days.add(d_off)

            dur_s = round(max(1200.0, week_hours * 3600.0 * share))
            tss = round(max(18.0, week_tss * share * (1.15 if stype in ("intervals", "tempo", "hills", "race") else 0.92)), 0)
            dist_km, elev_m = _estimate_session_volume(
                sport, stype, dur_s, phase, run_km_goal, run_elev_goal, bike_km_goal, bike_elev_goal, swim_km_goal, baseline
            )
            if stype == "race":
                if plan_type in ("trail_run", "road_run"):
                    dist_km, elev_m = run_km_goal, run_elev_goal
                elif plan_type == "cycling":
                    dist_km, elev_m = bike_km_goal, bike_elev_goal
                elif plan_type == "triathlon":
                    dist_km, elev_m = round(swim_km_goal + bike_km_goal + run_km_goal, 1), bike_elev_goal + run_elev_goal

            slot = "morning" if s_date.weekday() >= 5 else pref_slot
            week_sessions.append(
                {
                    "temp_id": temp_id,
                    "week_index": w_idx,
                    "scheduled_date": _iso(s_date),
                    "scheduled_slot": slot,
                    "sport": sport,
                    "session_type": stype,
                    "priority": prio,
                    "title": title,
                    "description": desc,
                    "workout_steps": steps,
                    "target_duration_s": dur_s,
                    "target_distance_km": round(dist_km, 1),
                    "target_elev_m": round(elev_m, 0),
                    "target_tss": tss,
                }
            )
            temp_id += 1

        disc_split: dict[str, float] = {}
        for s in week_sessions:
            k = "run" if s["sport"] in ("run", "trail_run") else s["sport"]
            disc_split[k] = round(disc_split.get(k, 0.0) + s["target_duration_s"] / 3600.0, 2)

        weeks_out.append(
            {
                "week_index": w_idx,
                "start_date": _iso(w_start),
                "phase": phase,
                "target_tss": round(sum(s["target_tss"] for s in week_sessions), 0),
                "target_duration_s": round(sum(s["target_duration_s"] for s in week_sessions), 0),
                "target_distance_km": round(sum(s["target_distance_km"] for s in week_sessions), 1),
                "target_elev_m": round(sum(s["target_elev_m"] for s in week_sessions), 0),
                "discipline_split": disc_split,
                "coach_focus": _default_phase_focus(plan_type, phase),
            }
        )
        sessions_out.extend(week_sessions)

    return weeks_out, sessions_out


def _weekly_templates(
    plan_type: str,
    phase: str,
    run_km: float,
    run_elev: float,
    bike_km: float,
    bike_elev: float,
    swim_km: float,
) -> list[tuple[int, str, str, str, float, str, str, list[str]]]:
    if phase == "race_week":
        main_sport = "trail_run" if plan_type == "trail_run" else ("bike" if plan_type == "cycling" else ("brick" if plan_type in ("triathlon", "duathlon") else "run"))
        return [
            (1, "run" if main_sport != "bike" else "bike", "easy", "supporting", 0.30, "Shakeout & Strides", "Short aerobic opener with 4×20s light strides.", ["15m easy Z1-Z2", "4×20s relaxed strides", "10m easy"]),
            (3, "run" if main_sport != "bike" else "bike", "recovery", "optional", 0.20, "Pre-Race Mobility & Spin", "Keep legs fresh, hydrate and carb-load.", ["25m very easy Z1"]),
            (6, main_sport, "race", "key", 0.50, "Race Day Execution", "Execute pacing & fueling plan cleanly.", ["Controlled start first 25%", "Steady fueling every 30-40m", "Strong finish"]),
        ]

    if plan_type == "trail_run":
        if phase in ("build", "peak"):
            return [
                (1, "trail_run", "easy", "supporting", 0.16, "Aerobic Trail Run", "Easy conversational Z2 on rolling terrain.", ["10m warmup", "Z2 aerobic trail", "5m cooldown"]),
                (2, "trail_run", "hills", "key", 0.18, "Climb Power Repeats", "Sustained uphill efforts at Z3-Z4 focusing on hiking/running efficiency.", ["15m easy", "6×4m uphill Z4 (jog down)", "10m easy"]),
                (3, "trail_run", "recovery", "optional", 0.12, "Recovery Jog & Mobility", "Very easy Z1 flush to absorb vertical load.", ["35-45m easy Z1"]),
                (5, "trail_run", "long", "key", 0.34, "Long Mountain Trail Run", "Practice race nutrition (60-80g carbs/h) and steady climbing VAM.", ["20m settle in Z2", "Steady mountain Z2 + climbs", "Fuel every 35m"]),
                (6, "trail_run", "long", "key", 0.20, "Back-to-Back Fatigue Run", "Steady Z2 on tired legs to build ultra durability.", ["10m gentle start", "Steady Z2 trail", "Walk steep pitches"]),
            ]
        return [
            (1, "trail_run", "easy", "supporting", 0.20, "Easy Aerobic Run", "Relaxed Z2 effort; keep HR controlled.", ["Easy Z2 throughout"]),
            (2, "trail_run", "tempo", "key", 0.20, "Rolling Tempo / Threshold", "Sustained Z3-Z4 rhythm on undulating trails.", ["15m warmup", "2×12m Z3-Z4 (3m easy)", "10m cooldown"]),
            (4, "trail_run", "easy", "supporting", 0.18, "Trail Cadence & Strides", "Easy run finishing with 6×20s hill strides.", ["Easy Z2", "6×20s uphill strides"]),
            (6, "trail_run", "long", "key", 0.42, "Weekend Long Trail Run", "Build time on feet and vertical gain progressively.", ["Steady Z2 effort", "Practice race hydration"]),
        ]

    if plan_type == "cycling":
        return [
            (1, "bike", "intervals", "key", 0.20, "Sweet-Spot / Threshold Intervals", "Build sustainable climbing & flat power at 88-96% FTP.", ["15m warmup", "3×12m @ 90% FTP (4m Z1)", "10m spin"]),
            (2, "bike", "easy", "supporting", 0.18, "Endurance Z2 Spin", "High-cadence aerobic base ride at 65-75% FTP.", ["Steady Z2 endurance"]),
            (4, "bike", "hills", "key", 0.22, "Climb Tempo & Torque", "Sustained climbs at 80-88% FTP with low-cadence seated work.", ["15m warmup", "3×10m climb tempo", "15m easy"]),
            (6, "bike", "long", "key", 0.40, "Weekend Endurance Ride", "Long aerobic ride targeting race elevation & fueling.", ["Steady Z2", "60-80g carbs/h", "Controlled climbs"]),
        ]

    if plan_type == "triathlon":
        return [
            (1, "swim", "intervals", "supporting", 0.14, "CSS Swim Threshold", "Aerobic efficiency & pacing near Critical Swim Speed.", ["300m warmup", "8×100m @ CSS (15s rest)", "200m cooldown"]),
            (2, "bike", "tempo", "key", 0.22, "Aero Bike Tempo", "Sustained race-position riding at 78-85% FTP.", ["15m warmup", "2×20m aero tempo", "10m easy"]),
            (3, "run", "tempo", "key", 0.16, "Threshold Run", "Controlled Z3-Z4 cruise intervals.", ["15m warmup", "4×6m @ threshold GAP (2m jog)", "10m easy"]),
            (4, "swim", "easy", "optional", 0.12, "Endurance Swim & Drills", "Continuous aerobic swim with catch-up & sighting drills.", ["200m drills", "Continuous Z2 swim", "100m easy"]),
            (5, "brick", "brick", "key", 0.24, "Race-Sim Brick (Bike → Run)", "Longer bike followed immediately by off-the-bike transition run.", ["Main bike Z2-Z3", "Quick T2 (<3m)", "15-30m run at goal pace"]),
            (6, "run", "long", "key", 0.12, "Steady Aerobic Long Run", "Relaxed Z2 run to build run durability.", ["Steady Z2 aerobic"]),
        ]

    if plan_type == "duathlon":
        return [
            (1, "run", "intervals", "key", 0.20, "Run Threshold Repeats", "Z4 intervals to sharpen leg speed.", ["15m warmup", "5×5m Z4 (2m jog)", "10m easy"]),
            (2, "bike", "tempo", "key", 0.25, "Bike Sweet-Spot", "Sustained 85-92% FTP blocks.", ["15m warmup", "2×20m sweet-spot", "10m spin"]),
            (4, "run", "easy", "supporting", 0.18, "Aerobic Run", "Easy Z2 recovery & cadence.", ["Steady Z2 run"]),
            (6, "brick", "brick", "key", 0.37, "Long Bike-to-Run Brick", "Race-specific bike endurance into fast-settling run legs.", ["Long bike Z2", "Quick transition", "20-35m steady run"]),
        ]

    # road_run or base_build
    return [
        (1, "run", "easy", "supporting", 0.22, "Easy Aerobic Run", "Conversational Z2 run.", ["Steady Z2"]),
        (2, "run", "intervals", "key", 0.22, "Threshold / Cruise Intervals", "Build lactate threshold pace cleanly.", ["15m warmup", "4×8m @ threshold (2m jog)", "10m cooldown"]),
        (4, "run" if plan_type == "road_run" else "bike", "easy", "supporting", 0.20, "Aerobic Volume", "Easy Z2 cross-training or aerobic run.", ["Steady Z2"]),
        (6, "run", "long", "key", 0.36, "Weekend Long Run", "Progressive aerobic endurance run.", ["Steady Z2", "Last 15% steady Z3"]),
    ]


def _estimate_session_volume(
    sport: str,
    stype: str,
    dur_s: float,
    phase: str,
    run_km_goal: float,
    run_elev_goal: float,
    bike_km_goal: float,
    bike_elev_goal: float,
    swim_km_goal: float,
    baseline: dict[str, Any],
) -> tuple[float, float]:
    hrs = dur_s / 3600.0
    if sport in ("run", "trail_run"):
        gap_ms = baseline.get("median_gap_ms") or 2.85  # ~5:50/km fallback
        speed_ms = gap_ms * (0.86 if sport == "trail_run" else 0.94)
        km = (dur_s * speed_ms) / 1000.0
        elev_per_km = (run_elev_goal / max(1.0, run_km_goal)) if sport == "trail_run" else 8.0
        elev_mult = 1.25 if stype == "hills" else (1.0 if stype == "long" else 0.7)
        return km, km * elev_per_km * elev_mult
    if sport == "bike":
        km = hrs * 27.0
        elev_per_km = bike_elev_goal / max(1.0, bike_km_goal)
        return km, km * elev_per_km * (1.2 if stype == "hills" else 0.85)
    if sport == "swim":
        css = baseline.get("swim_css_s_per_100m") or 125.0
        return (dur_s / css) * 0.1, 0.0
    if sport == "brick":
        bike_km = hrs * 0.75 * 28.0
        run_km = hrs * 0.25 * 10.5
        return bike_km + run_km, bike_km * 8.0
    return 0.0, 0.0


def _default_phase_focus(plan_type: str, phase: str) -> str:
    labels = {
        "base": "Build aerobic volume & durable connective tissue at conversational Z2.",
        "build": "Increase race-specific intensity, vertical/threshold work, and fueling practice.",
        "peak": "Highest race-specific load (key long sessions / bricks) before tapering.",
        "recovery": "Absorb recent training load; keep frequency but cut volume by ~25-30%.",
        "taper": "Shed fatigue while keeping short sharp neuromuscular touches.",
        "race_week": "Rest, hydrate, carb-load, and execute your pacing strategy.",
    }
    return labels.get(phase, f"Focused {plan_type.replace('_', ' ')} progression.")


def create_plan(
    db: Session,
    prefs: dict[str, Any],
    payload: dict[str, Any],
    *,
    use_ai: bool = True,
    today: date | None = None,
) -> TrainingPlan:
    """Create a new multi-sport training plan, optionally enriched by Gemini Pro."""
    today = today or date.today()
    plan_type = str(payload.get("plan_type") or "trail_run")
    if plan_type not in PLAN_TYPES:
        plan_type = "trail_run"
    name = str(payload.get("name") or f"{plan_type.replace('_', ' ').title()} Plan").strip()
    start_date = _parse_date(payload.get("start_date"), today)
    event_date = _parse_date(payload.get("event_date"), today + timedelta(days=84))
    if event_date <= start_date + timedelta(days=6):
        event_date = start_date + timedelta(days=28)

    goal_spec = dict(payload.get("goal_spec") or {})
    goal_spec.setdefault("disciplines", _DEFAULT_DISCIPLINES[plan_type])
    goal_spec.setdefault("targets", {})
    schedule_prefs = dict(payload.get("schedule_prefs") or {})
    schedule_prefs.setdefault("preferred_slot", "evening")
    schedule_prefs.setdefault("rest_days", [0])

    baseline = athlete_baseline(db, prefs, today)
    weeks_data, sessions_data = _build_skeleton(
        plan_type=plan_type,
        name=name,
        start_date=start_date,
        event_date=event_date,
        goal_spec=goal_spec,
        schedule_prefs=schedule_prefs,
        baseline=baseline,
    )

    coach_summary = (
        f"{len(weeks_data)}-week {plan_type.replace('_', ' ')} plan targeting {name} on {_iso(event_date)}."
    )
    model_used = "deterministic"

    # Optional Gemini Pro enrichment for the first 4 weeks (compact prompt = < $0.05)
    if use_ai:
        first_4w = [s for s in sessions_data if s["week_index"] <= 4]
        ai_payload = {
            "plan_name": name,
            "plan_type": plan_type,
            "event_date": _iso(event_date),
            "goal_spec": goal_spec,
            "schedule_prefs": schedule_prefs,
            "athlete_baseline": baseline,
            "upcoming_sessions": [
                {
                    "temp_id": s["temp_id"],
                    "week_index": s["week_index"],
                    "date": s["scheduled_date"],
                    "sport": s["sport"],
                    "type": s["session_type"],
                    "priority": s["priority"],
                    "dur_min": round(s["target_duration_s"] / 60),
                    "km": s["target_distance_km"],
                    "elev_m": s["target_elev_m"],
                    "tss": s["target_tss"],
                    "title": s["title"],
                }
                for s in first_4w
            ],
        }
        try:
            res, model_used = gemini.generate_json(
                db,
                feature="plan_generate",
                system_prompt=_PLAN_SYSTEM_PROMPT,
                user_payload=ai_payload,
                tier="pro",
                max_output_tokens=3500,
            )
            if isinstance(res.get("coach_summary"), str) and res["coach_summary"].strip():
                coach_summary = res["coach_summary"].strip()
            w_focuses = res.get("week_focuses") or {}
            if isinstance(w_focuses, dict):
                for w in weeks_data:
                    wf = w_focuses.get(str(w["week_index"]))
                    if isinstance(wf, str) and wf.strip():
                        w["coach_focus"] = wf.strip()
            by_tid = {s["temp_id"]: s for s in sessions_data}
            for item in res.get("sessions") or []:
                if not isinstance(item, dict):
                    continue
                target = by_tid.get(item.get("temp_id"))
                if not target:
                    continue
                if isinstance(item.get("title"), str) and item["title"].strip():
                    target["title"] = item["title"].strip()[:180]
                if isinstance(item.get("description"), str) and item["description"].strip():
                    target["description"] = item["description"].strip()[:800]
                if isinstance(item.get("workout_steps"), list):
                    target["workout_steps"] = [str(x)[:160] for x in item["workout_steps"][:8]]
        except (gemini.GeminiNotConfiguredError, gemini.BudgetExceededError, gemini.GeminiError) as exc:
            logger.info("Plan generation falling back to deterministic skeleton: %s", exc)
            model_used = "deterministic"

    # Archive any previous active plan if requested (default: keep one active plan)
    if payload.get("set_active", True):
        for prev in db.scalars(select(TrainingPlan).where(TrainingPlan.status == "active")):
            prev.status = "archived"

    plan = TrainingPlan(
        name=name,
        status="active",
        plan_type=plan_type,
        start_date=weeks_data[0]["start_date"],
        event_date=_iso(event_date),
        goal_spec=goal_spec,
        schedule_prefs=schedule_prefs,
        baseline=baseline,
        coach_summary=coach_summary,
    )
    db.add(plan)
    db.flush()

    week_id_by_idx: dict[int, int] = {}
    for w in weeks_data:
        row = TrainingWeek(plan_id=plan.id, **w)
        db.add(row)
        db.flush()
        week_id_by_idx[w["week_index"]] = row.id

    for s in sessions_data:
        s_copy = {k: v for k, v in s.items() if k not in ("temp_id", "week_index")}
        db.add(
            TrainingSession(
                plan_id=plan.id,
                week_id=week_id_by_idx[s["week_index"]],
                **s_copy,
            )
        )

    db.add(
        PlanAdaptation(
            plan_id=plan.id,
            trigger="plan_created",
            model_used=model_used,
            summary=coach_summary,
            diff=[],
        )
    )
    db.flush()
    match_activities_to_plan(db, plan, today=today)
    return plan


def match_activities_to_plan(
    db: Session, plan: TrainingPlan, *, today: date | None = None
) -> dict[str, int]:
    """Pair recorded activities with planned sessions and mark missed past sessions."""
    today = today or date.today()
    start_d = _parse_date(plan.start_date, today) - timedelta(days=1)
    acts = list(
        db.scalars(
            select(Activity)
            .where(Activity.start_time >= start_d.isoformat())
            .order_by(Activity.start_time.asc())
        )
    )
    sessions = list(
        db.scalars(
            select(TrainingSession)
            .where(TrainingSession.plan_id == plan.id)
            .order_by(TrainingSession.scheduled_date.asc(), TrainingSession.id.asc())
        )
    )
    used_act_ids = {s.matched_activity_id for s in sessions if s.matched_activity_id}
    matched_count = 0
    missed_count = 0

    for s in sessions:
        if s.sport == "rest" or s.status in ("skipped", "completed"):
            continue
        s_date = _parse_date(s.scheduled_date, today)
        if s.matched_activity_id is None:
            best_act: Activity | None = None
            best_score = -1.0
            for a in acts:
                if a.id in used_act_ids:
                    continue
                if not _activity_matches_sport(a, s.sport):
                    continue
                a_date = (a.start_local or a.start_time).date()
                day_diff = abs((a_date - s_date).days)
                if day_diff > 1:
                    continue
                dur_ratio = (float(a.moving_time_s or 0.0) / max(1.0, s.target_duration_s)) if s.target_duration_s else 1.0
                fit = max(0.0, 1.0 - abs(1.0 - dur_ratio)) - 0.15 * day_diff
                if fit > best_score:
                    best_score = fit
                    best_act = a
            if best_act is not None:
                s.matched_activity_id = best_act.id
                used_act_ids.add(best_act.id)
                comp = _session_compliance(s, best_act)
                s.compliance_score = comp
                s.status = "completed" if comp >= 70.0 else "partial"
                matched_count += 1
                continue

        if s_date < today and s.status in ("planned", "moved") and s.matched_activity_id is None:
            s.status = "missed"
            s.compliance_score = 0.0
            missed_count += 1

    db.flush()
    return {"matched": matched_count, "missed": missed_count}


def _session_compliance(s: TrainingSession, a: Activity) -> float:
    ratios: list[float] = []
    if s.target_duration_s and a.moving_time_s:
        ratios.append(float(a.moving_time_s) / float(s.target_duration_s))
    if s.target_distance_km and a.distance_m:
        ratios.append((float(a.distance_m) / 1000.0) / float(s.target_distance_km))
    if s.target_tss and a.load:
        ratios.append(float(a.load) / float(s.target_tss))
    if not ratios:
        return 85.0
    avg_r = sum(ratios) / len(ratios)
    # 0.85..1.15 -> 100, penalize under-completion more strongly than slight over-delivery
    if 0.85 <= avg_r <= 1.2:
        return 100.0
    if avg_r < 0.85:
        return round(max(10.0, min(100.0, (avg_r / 0.85) * 100.0)), 1)
    # > 1.2: mild penalty for excessive load spike
    return round(max(60.0, 100.0 - (avg_r - 1.2) * 40.0), 1)


def _predict_race_time_s(
    plan: TrainingPlan,
    baseline: dict[str, Any],
    ctl_value: float,
    durability_factor: float = 1.0,
) -> dict[str, Any]:
    """Estimate race finish time in seconds for the given CTL & baseline."""
    targets = (plan.goal_spec or {}).get("targets") or {}
    # Fitness scaling relative to current CTL (gentle Banister-style curve)
    cur_ctl = max(15.0, float(baseline.get("ctl") or 25.0))
    ctl_ratio = max(0.75, min(1.30, (ctl_value + 25.0) / (cur_ctl + 25.0)))
    speed_gain = math.pow(ctl_ratio, 0.18) * durability_factor

    if plan.plan_type in ("trail_run", "road_run"):
        dist_km = float(targets.get("run_km") or (50.0 if plan.plan_type == "trail_run" else 21.1))
        elev_m = float(targets.get("run_elev_m") or (2000.0 if plan.plan_type == "trail_run" else 150.0))
        gap_ms = float(baseline.get("median_gap_ms") or 2.85) * speed_gain
        vam = float(baseline.get("median_climb_vam_mh") or 650.0) * speed_gain
        # Riegel distance fatigue for > 10km
        riegel = math.pow(max(1.0, dist_km / 10.0), 0.075 if plan.plan_type == "trail_run" else 0.06)
        flat_s = (dist_km * 1000.0) / max(1.2, gap_ms) * riegel
        climb_s = (elev_m / max(300.0, vam)) * 3600.0 * 0.55 if elev_m > 0 else 0.0
        total_s = round(flat_s + climb_s)
        return {"total_s": total_s, "splits": {"run_s": total_s}}

    if plan.plan_type == "cycling":
        dist_km = float(targets.get("bike_km") or 120.0)
        elev_m = float(targets.get("bike_elev_m") or 1500.0)
        ftp = float(baseline.get("ftp_w") or 210.0) * speed_gain
        weight = float(baseline.get("weight_kg") or 72.0) + 9.0
        w_per_kg = ftp / max(45.0, weight)
        flat_kmh = max(20.0, min(42.0, 18.0 + w_per_kg * 4.6))
        climb_vam = max(450.0, w_per_kg * 290.0)
        flat_s = (dist_km / flat_kmh) * 3600.0
        climb_s = (elev_m / climb_vam) * 3600.0 * 0.65
        total_s = round(flat_s + climb_s)
        return {"total_s": total_s, "splits": {"bike_s": total_s}}

    # Triathlon or Duathlon
    swim_km = float(targets.get("swim_km") or (1.9 if plan.plan_type == "triathlon" else 0.0))
    bike_km = float(targets.get("bike_km") or 90.0)
    bike_elev = float(targets.get("bike_elev_m") or 700.0)
    run_km = float(targets.get("run_km") or 21.1)
    run_elev = float(targets.get("run_elev_m") or 100.0)

    css = float(baseline.get("swim_css_s_per_100m") or 125.0) / speed_gain
    swim_s = round(swim_km * 10.0 * css) if swim_km > 0 else 0

    ftp = float(baseline.get("ftp_w") or 210.0) * speed_gain
    weight = float(baseline.get("weight_kg") or 72.0) + 9.0
    bike_kmh = max(21.0, min(40.0, 17.5 + (ftp / weight) * 4.4))
    bike_s = round((bike_km / bike_kmh) * 3600.0 + (bike_elev / 700.0) * 3600.0 * 0.5)

    gap_ms = float(baseline.get("median_gap_ms") or 2.85) * speed_gain
    # Brick fatigue penalty (~7% slower run off the bike)
    run_s = round(((run_km * 1000.0) / max(1.2, gap_ms)) * 1.07 + (run_elev / 650.0) * 3600.0 * 0.5)
    transitions_s = 360 if plan.plan_type == "triathlon" else 240
    total_s = swim_s + bike_s + run_s + transitions_s
    return {
        "total_s": total_s,
        "splits": {"swim_s": swim_s, "bike_s": bike_s, "run_s": run_s, "transitions_s": transitions_s},
    }


def compute_plan_analytics(
    db: Session, plan: TrainingPlan, prefs: dict[str, Any], *, today: date | None = None
) -> dict[str, Any]:
    """Compute alignment score, discipline progress, race prediction, and trajectory graph."""
    today = today or date.today()
    baseline = athlete_baseline(db, prefs, today)
    weeks = list(
        db.scalars(
            select(TrainingWeek)
            .where(TrainingWeek.plan_id == plan.id)
            .order_by(TrainingWeek.week_index.asc())
        )
    )
    sessions = list(
        db.scalars(
            select(TrainingSession)
            .where(TrainingSession.plan_id == plan.id)
            .order_by(TrainingSession.scheduled_date.asc(), TrainingSession.id.asc())
        )
    )

    act_ids = [s.matched_activity_id for s in sessions if s.matched_activity_id]
    acts_by_id = (
        {a.id: a for a in db.scalars(select(Activity).where(Activity.id.in_(act_ids)))}
        if act_ids
        else {}
    )

    # Alignment score over sessions up to today
    due = [s for s in sessions if s.sport != "rest" and _parse_date(s.scheduled_date, today) <= today]
    completed_weight = 0.0
    planned_tss_due = 0.0
    actual_tss_due = 0.0
    key_due = 0
    key_hit = 0
    intensity_scores: list[float] = []

    disc_progress: dict[str, dict[str, float]] = {}

    for s in due:
        planned_tss_due += float(s.target_tss or 0.0)
        act = acts_by_id.get(s.matched_activity_id) if s.matched_activity_id else None
        if s.status == "completed":
            completed_weight += 1.0
        elif s.status == "partial":
            completed_weight += 0.6
        if act:
            actual_tss_due += float(act.load or s.target_tss or 0.0)
            intensity_scores.append(float(s.compliance_score or 85.0))
        if s.priority == "key":
            key_due += 1
            if s.status in ("completed", "partial"):
                key_hit += 1

    for s in sessions:
        if s.sport == "rest":
            continue
        dk = "run" if s.sport in ("run", "trail_run") else s.sport
        d = disc_progress.setdefault(
            dk, {"planned_hours": 0.0, "actual_hours": 0.0, "planned_km": 0.0, "actual_km": 0.0, "planned_sessions": 0, "completed_sessions": 0}
        )
        d["planned_hours"] += float(s.target_duration_s or 0.0) / 3600.0
        d["planned_km"] += float(s.target_distance_km or 0.0)
        d["planned_sessions"] += 1
        act = acts_by_id.get(s.matched_activity_id) if s.matched_activity_id else None
        if act:
            d["actual_hours"] += float(act.moving_time_s or 0.0) / 3600.0
            d["actual_km"] += float(act.distance_m or 0.0) / 1000.0
        if s.status in ("completed", "partial"):
            d["completed_sessions"] += 1

    for d in disc_progress.values():
        d["planned_hours"] = round(d["planned_hours"], 1)
        d["actual_hours"] = round(d["actual_hours"], 1)
        d["planned_km"] = round(d["planned_km"], 1)
        d["actual_km"] = round(d["actual_km"], 1)

    if due:
        s_comp = round((completed_weight / len(due)) * 100.0, 1)
        load_ratio = actual_tss_due / max(1.0, planned_tss_due)
        s_load = round(max(0.0, 100.0 - abs(1.0 - load_ratio) * 100.0), 1)
        s_int = round(sum(intensity_scores) / len(intensity_scores), 1) if intensity_scores else 0.0
        s_key = round((key_hit / key_due) * 100.0, 1) if key_due else s_comp
        alignment_overall = round(0.35 * s_comp + 0.30 * s_load + 0.20 * s_int + 0.15 * s_key, 1)
    else:
        s_comp = s_load = s_int = s_key = alignment_overall = 100.0

    # Simulate Banister CTL trajectory from plan start -> today -> race day
    load_series = (insights.training_load(db, today).get("series") or [])
    ctl_by_day = {pt["date"]: float(pt["ctl"]) for pt in load_series}

    start_ctl = float((plan.baseline or {}).get("ctl") or baseline["ctl"] or 25.0)
    cur_ctl = float(baseline["ctl"] or start_ctl)
    adherence_factor = max(0.45, min(1.05, alignment_overall / 100.0)) if due else 0.92

    planned_ctl = start_ctl
    proj_opt_ctl = cur_ctl
    proj_trend_ctl = cur_ctl
    decay = 1.0 - math.exp(-7.0 / 42.0)  # weekly CTL EWMA step

    trajectory: list[dict[str, Any]] = []
    for w in weeks:
        w_start = _parse_date(w.start_date, today)
        w_end = w_start + timedelta(days=6)
        daily_tss = float(w.target_tss or 0.0) / 7.0
        planned_ctl = planned_ctl + (daily_tss - planned_ctl) * decay

        is_future = w_start > today
        actual_ctl_val: float | None = None
        if not is_future:
            lookup_d = min(w_end, today)
            actual_ctl_val = ctl_by_day.get(_iso(lookup_d), cur_ctl)
            proj_opt_ctl = actual_ctl_val
            proj_trend_ctl = actual_ctl_val
        else:
            proj_opt_ctl = proj_opt_ctl + (daily_tss - proj_opt_ctl) * decay
            proj_trend_ctl = proj_trend_ctl + (daily_tss * adherence_factor - proj_trend_ctl) * decay

        ref_ctl = actual_ctl_val if actual_ctl_val is not None else proj_trend_ctl
        pred = _predict_race_time_s(plan, baseline, ref_ctl)
        trajectory.append(
            {
                "week_index": w.week_index,
                "date": w.start_date,
                "phase": w.phase,
                "is_future": is_future,
                "target_tss": round(float(w.target_tss or 0.0), 0),
                "actual_ctl": round(actual_ctl_val, 1) if actual_ctl_val is not None else None,
                "planned_ctl": round(planned_ctl, 1),
                "projected_ctl_optimal": round(proj_opt_ctl, 1),
                "projected_ctl_trend": round(proj_trend_ctl, 1),
                "predicted_time_s": pred["total_s"],
            }
        )

    race_ctl_optimal = trajectory[-1]["projected_ctl_optimal"] if trajectory else cur_ctl
    race_ctl_trend = trajectory[-1]["projected_ctl_trend"] if trajectory else cur_ctl
    race_ctl_planned = trajectory[-1]["planned_ctl"] if trajectory else cur_ctl

    pred_now = _predict_race_time_s(plan, baseline, cur_ctl)
    pred_race_optimal = _predict_race_time_s(plan, baseline, race_ctl_optimal)
    pred_race_trend = _predict_race_time_s(plan, baseline, race_ctl_trend)
    target_time_s = (plan.goal_spec or {}).get("target_time_s")

    # Determine on-track verdict & limiting factors
    limiting_factors: list[str] = []
    if target_time_s:
        gap_pct = (pred_race_trend["total_s"] - float(target_time_s)) / max(1.0, float(target_time_s)) * 100.0
        if gap_pct <= 2.5:
            verdict = "on_track"
        elif gap_pct <= 8.0:
            verdict = "catchable"
            limiting_factors.append(f"Projected finish is {gap_pct:.1f}% slower than goal time at current adherence.")
        else:
            verdict = "at_risk"
            limiting_factors.append(f"Projected finish is {gap_pct:.1f}% slower than goal time — boost key session hit rate or adjust goal.")
    else:
        ctl_gap = (race_ctl_trend - race_ctl_planned) / max(1.0, race_ctl_planned) * 100.0
        if alignment_overall >= 80 and ctl_gap >= -8:
            verdict = "on_track"
        elif alignment_overall >= 60:
            verdict = "catchable"
            limiting_factors.append("Plan adherence is moderate — hitting upcoming key sessions will close the gap.")
        else:
            verdict = "at_risk"
            limiting_factors.append("Recent missed sessions are pulling projected race fitness below plan.")

    if baseline.get("acwr") and baseline["acwr"] > 1.35:
        limiting_factors.append(f"ACWR is elevated ({baseline['acwr']:.2f}) — prioritize sleep and easy-day discipline.")
    if due and s_key < 75:
        limiting_factors.append(f"Key session hit rate is {s_key:.0f}% — protect weekend long/brick workouts.")

    event_d = _parse_date(plan.event_date, today)
    days_to_race = (event_d - today).days
    current_week = next((w for w in weeks if _parse_date(w.start_date, today) <= today <= _parse_date(w.start_date, today) + timedelta(days=6)), weeks[0] if weeks else None)

    return {
        "days_to_race": days_to_race,
        "weeks_to_race": round(days_to_race / 7.0, 1),
        "current_week_index": current_week.week_index if current_week else 1,
        "current_phase": current_week.phase if current_week else "base",
        "baseline": baseline,
        "alignment": {
            "overall": alignment_overall,
            "completion": s_comp,
            "load": s_load,
            "intensity": s_int,
            "key_sessions": s_key,
            "due_sessions": len(due),
        },
        "disciplines": disc_progress,
        "prediction": {
            "target_time_s": target_time_s,
            "current_predicted_s": pred_now["total_s"],
            "race_day_optimal_s": pred_race_optimal["total_s"],
            "race_day_trend_s": pred_race_trend["total_s"],
            "race_day_splits": pred_race_trend["splits"],
            "verdict": verdict,
            "limiting_factors": limiting_factors,
        },
        "trajectory": trajectory,
    }


def _state_hash(recent: list[TrainingSession], upcoming: list[TrainingSession], user_note: str) -> str:
    sig = {
        "recent": [(s.id, s.status, s.compliance_score, s.scheduled_date) for s in recent],
        "upcoming": [(s.id, s.status, s.scheduled_date, s.target_duration_s, s.target_tss) for s in upcoming],
        "note": user_note.strip().lower(),
    }
    return hashlib.sha256(json.dumps(sig, sort_keys=True).encode()).hexdigest()[:32]


def adapt_plan(
    db: Session,
    plan: TrainingPlan,
    prefs: dict[str, Any],
    *,
    trigger: str = "manual",
    user_note: str = "",
    today: date | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Adapt upcoming 14 days based on completed/missed sessions & athlete feedback.

    Uses Gemini Flash when configured & within budget; falls back cleanly to a
    deterministic rescheduler if offline, unconfigured, or budget-capped.
    """
    today = today or date.today()
    match_stats = match_activities_to_plan(db, plan, today=today)

    sessions = list(
        db.scalars(
            select(TrainingSession)
            .where(TrainingSession.plan_id == plan.id)
            .order_by(TrainingSession.scheduled_date.asc(), TrainingSession.id.asc())
        )
    )
    win_past = today - timedelta(days=10)
    win_future = today + timedelta(days=14)
    recent = [s for s in sessions if win_past <= _parse_date(s.scheduled_date, today) < today]
    upcoming = [
        s
        for s in sessions
        if today <= _parse_date(s.scheduled_date, today) <= win_future and s.status in ("planned", "moved")
    ]

    h = _state_hash(recent, upcoming, user_note)
    if not force and plan.last_adapted_hash == h:
        return {"adapted": False, "reason": "No changes since last adaptation", "match": match_stats, "diff": []}

    baseline = athlete_baseline(db, prefs, today)
    compact_payload = {
        "today": _iso(today),
        "plan_name": plan.name,
        "plan_type": plan.plan_type,
        "event_date": plan.event_date,
        "athlete_load": {"ctl": baseline["ctl"], "atl": baseline["atl"], "tsb": baseline["tsb"], "acwr": baseline["acwr"]},
        "user_note": user_note.strip()[:400],
        "recent_sessions": [
            {
                "id": s.id,
                "date": s.scheduled_date,
                "sport": s.sport,
                "type": s.session_type,
                "priority": s.priority,
                "status": s.status,
                "compliance": s.compliance_score,
                "dur_min": round(s.target_duration_s / 60),
                "title": s.title,
            }
            for s in recent
        ],
        "upcoming_sessions": [
            {
                "id": s.id,
                "date": s.scheduled_date,
                "sport": s.sport,
                "type": s.session_type,
                "priority": s.priority,
                "dur_min": round(s.target_duration_s / 60),
                "km": s.target_distance_km,
                "tss": s.target_tss,
                "title": s.title,
            }
            for s in upcoming
        ],
    }

    mutations: list[dict[str, Any]] = []
    summary = ""
    model_used = "deterministic"

    try:
        res, model_used = gemini.generate_json(
            db,
            feature="plan_adapt",
            system_prompt=_ADAPT_SYSTEM_PROMPT,
            user_payload=compact_payload,
            tier="fast",
            max_output_tokens=1500,
        )
        summary = str(res.get("summary") or "").strip()
        raw_muts = res.get("mutations") or []
        if isinstance(raw_muts, list):
            mutations = [m for m in raw_muts if isinstance(m, dict)]
    except (gemini.GeminiNotConfiguredError, gemini.BudgetExceededError, gemini.GeminiError) as exc:
        logger.info("Adaptation using deterministic fallback: %s", exc)
        summary, mutations = _deterministic_adapt(recent, upcoming, baseline, today, user_note)
        model_used = "deterministic"

    diff = _apply_mutations(db, plan, sessions, mutations, today)
    plan.last_adapted_hash = _state_hash(recent, upcoming, user_note)
    if not summary:
        summary = (
            f"Adjusted {len(diff)} upcoming session(s) based on recent training."
            if diff
            else "Your upcoming schedule looks well-balanced — no changes needed."
        )

    db.add(
        PlanAdaptation(
            plan_id=plan.id,
            trigger=trigger,
            model_used=model_used,
            summary=summary,
            diff=diff,
        )
    )
    db.flush()
    return {
        "adapted": True,
        "model_used": model_used,
        "summary": summary,
        "diff": diff,
        "match": match_stats,
    }


def _deterministic_adapt(
    recent: list[TrainingSession],
    upcoming: list[TrainingSession],
    baseline: dict[str, Any],
    today: date,
    user_note: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Rule-based fallback when Gemini is unavailable or at budget cap."""
    muts: list[dict[str, Any]] = []
    reasons: list[str] = []

    tired = any(w in user_note.lower() for w in ("tired", "fatigue", "sore", "sick", "heavy"))
    high_acwr = (baseline.get("acwr") or 0.0) > 1.35 or (baseline.get("tsb") or 0.0) < -22

    if (tired or high_acwr) and upcoming:
        nxt = upcoming[0]
        muts.append(
            {
                "session_id": nxt.id,
                "action": "adjust_load",
                "duration_scale": 0.78,
                "note": "Reduced load by ~22% to manage fatigue.",
            }
        )
        reasons.append(f"Trimmed {nxt.title} by 22% to protect recovery.")

    missed_keys = [s for s in recent if s.status == "missed" and s.priority == "key"]
    if missed_keys and upcoming:
        mk = missed_keys[-1]
        easy_slot = next((s for s in upcoming[:5] if s.priority != "key"), None)
        if easy_slot:
            muts.append(
                {
                    "session_id": easy_slot.id,
                    "action": "swap_type",
                    "new_title": f"{mk.title} (Adapted)",
                    "new_session_type": mk.session_type,
                    "duration_scale": 0.85,
                    "note": f"Replaced supporting session with trimmed {mk.title} missed on {mk.scheduled_date}.",
                }
            )
            reasons.append(f"Moved missed {mk.title} into {easy_slot.scheduled_date} at 85% volume.")

    summary = " ".join(reasons) if reasons else "Plan checked — upcoming sessions remain on track."
    return summary, muts


def _apply_mutations(
    db: Session,
    plan: TrainingPlan,
    sessions: list[TrainingSession],
    mutations: list[dict[str, Any]],
    today: date,
) -> list[dict[str, Any]]:
    by_id = {s.id: s for s in sessions}
    event_d = _parse_date(plan.event_date, today + timedelta(days=90))
    applied: list[dict[str, Any]] = []

    for m in mutations[:6]:
        sid = m.get("session_id")
        s = by_id.get(int(sid)) if isinstance(sid, int) else None
        if not s or s.status in ("completed", "skipped"):
            continue
        action = str(m.get("action") or "")
        before = {
            "scheduled_date": s.scheduled_date,
            "title": s.title,
            "duration_min": round(s.target_duration_s / 60),
            "tss": s.target_tss,
            "status": s.status,
        }
        note = str(m.get("note") or "")[:300]

        if action == "skip":
            s.status = "skipped"
            s.adaptation_note = note or "Skipped by adaptive coach"
        elif action in ("reschedule", "adjust_load", "swap_type"):
            new_date_s = m.get("new_date")
            if isinstance(new_date_s, str):
                nd = _parse_date(new_date_s, today)
                if today <= nd <= event_d:
                    s.scheduled_date = _iso(nd)
                    s.status = "moved"
            scale = m.get("duration_scale")
            if isinstance(scale, (int, float)):
                clamped = max(0.5, min(1.25, float(scale)))
                s.target_duration_s = round(s.target_duration_s * clamped)
                s.target_distance_km = round(s.target_distance_km * clamped, 1)
                s.target_elev_m = round(s.target_elev_m * clamped, 0)
                s.target_tss = round(s.target_tss * clamped, 0)
            if isinstance(m.get("new_title"), str) and m["new_title"].strip():
                s.title = m["new_title"].strip()[:180]
            if isinstance(m.get("new_description"), str) and m["new_description"].strip():
                s.description = m["new_description"].strip()[:800]
            if isinstance(m.get("new_session_type"), str) and m["new_session_type"].strip():
                s.session_type = m["new_session_type"].strip()[:20]
            s.adaptation_note = note or f"Adapted ({action})"
        else:
            continue

        after = {
            "scheduled_date": s.scheduled_date,
            "title": s.title,
            "duration_min": round(s.target_duration_s / 60),
            "tss": s.target_tss,
            "status": s.status,
        }
        if after != before:
            applied.append({"session_id": s.id, "action": action, "before": before, "after": after, "note": note})

    db.flush()
    return applied


def serialize_plan_summary(plan: TrainingPlan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "name": plan.name,
        "status": plan.status,
        "plan_type": plan.plan_type,
        "start_date": plan.start_date,
        "event_date": plan.event_date,
        "goal_spec": plan.goal_spec,
        "schedule_prefs": plan.schedule_prefs,
        "coach_summary": plan.coach_summary,
        "created_at": plan.created_at.isoformat() + "Z" if plan.created_at else None,
    }


def serialize_plan_detail(
    db: Session, plan: TrainingPlan, prefs: dict[str, Any], *, today: date | None = None
) -> dict[str, Any]:
    today = today or date.today()
    match_activities_to_plan(db, plan, today=today)
    analytics = compute_plan_analytics(db, plan, prefs, today=today)

    weeks = list(
        db.scalars(
            select(TrainingWeek)
            .where(TrainingWeek.plan_id == plan.id)
            .order_by(TrainingWeek.week_index.asc())
        )
    )
    sessions = list(
        db.scalars(
            select(TrainingSession)
            .where(TrainingSession.plan_id == plan.id)
            .order_by(TrainingSession.scheduled_date.asc(), TrainingSession.id.asc())
        )
    )
    adaptations = list(
        db.scalars(
            select(PlanAdaptation)
            .where(PlanAdaptation.plan_id == plan.id)
            .order_by(PlanAdaptation.created_at.desc())
            .limit(12)
        )
    )

    sessions_by_week: dict[int, list[dict[str, Any]]] = {}
    for s in sessions:
        sessions_by_week.setdefault(s.week_id, []).append(
            {
                "id": s.id,
                "week_id": s.week_id,
                "scheduled_date": s.scheduled_date,
                "scheduled_slot": s.scheduled_slot,
                "scheduled_start": s.scheduled_start,
                "scheduled_end": s.scheduled_end,
                "sport": s.sport,
                "session_type": s.session_type,
                "priority": s.priority,
                "title": s.title,
                "description": s.description,
                "workout_steps": s.workout_steps or [],
                "target_duration_s": s.target_duration_s,
                "target_distance_km": s.target_distance_km,
                "target_elev_m": s.target_elev_m,
                "target_tss": s.target_tss,
                "status": s.status,
                "matched_activity_id": s.matched_activity_id,
                "compliance_score": s.compliance_score,
                "gcal_event_id": s.gcal_event_id,
                "adaptation_note": s.adaptation_note,
            }
        )

    out = serialize_plan_summary(plan)
    out["analytics"] = analytics
    out["ai"] = gemini.get_ai_config(db)
    out["weeks"] = [
        {
            "id": w.id,
            "week_index": w.week_index,
            "start_date": w.start_date,
            "phase": w.phase,
            "target_tss": w.target_tss,
            "target_duration_s": w.target_duration_s,
            "target_distance_km": w.target_distance_km,
            "target_elev_m": w.target_elev_m,
            "discipline_split": w.discipline_split or {},
            "coach_focus": w.coach_focus,
            "sessions": sessions_by_week.get(w.id, []),
        }
        for w in weeks
    ]
    out["adaptations"] = [
        {
            "id": a.id,
            "created_at": a.created_at.isoformat() + "Z" if a.created_at else None,
            "trigger": a.trigger,
            "model_used": a.model_used,
            "summary": a.summary,
            "diff": a.diff or [],
        }
        for a in adaptations
    ]
    return out


def sync_active_plans_after_ingest(db: Session, prefs: dict[str, Any]) -> dict[str, Any]:
    """Called after Strava/Komoot sync: match activities, auto-adapt, sync Google Calendar & push alerts."""
    from routepass import push
    from routepass.providers import gcal

    plans = list(db.scalars(select(TrainingPlan).where(TrainingPlan.status == "active")))
    total_matched = 0
    total_missed = 0
    adapted = 0
    cal_synced = 0
    gcal_cfg = gcal.get_config(db)
    push_prefs = push.get_prefs(db)

    for plan in plans:
        res = match_activities_to_plan(db, plan)
        total_matched += res["matched"]
        total_missed += res["missed"]
        if res["matched"] > 0 and push_prefs.get("notify_completed", True):
            push.send_notification(
                db,
                title=f"{plan.name}: Workout synced",
                body=f"Matched {res['matched']} activity to your training plan.",
                url="/insights/training",
                kind="completed",
            )
        if res["missed"] > 0 or res["matched"] > 0:
            try:
                ad = adapt_plan(db, plan, prefs, trigger="auto_sync", force=False)
                if ad.get("adapted") and ad.get("diff"):
                    adapted += 1
                    if push_prefs.get("notify_adapted", True):
                        push.send_notification(
                            db,
                            title=f"{plan.name}: Plan adapted",
                            body=ad.get("summary") or "Upcoming sessions were automatically adjusted.",
                            url="/insights/training",
                            kind="adapted",
                        )
            except Exception:  # noqa: BLE001
                logger.exception("Auto-adaptation failed for plan %s", plan.id)

        if gcal_cfg.get("connected") and gcal_cfg.get("target_calendar_id") and gcal_cfg.get("auto_sync", True):
            try:
                gcal.sync_plan_to_calendar(db, plan)
                cal_synced += 1
            except Exception:  # noqa: BLE001
                logger.exception("Google Calendar auto-sync failed for plan %s", plan.id)

    try:
        push.dispatch_due_reminders(db)
    except Exception:  # noqa: BLE001
        logger.exception("Push reminder dispatch failed")

    return {
        "plans": len(plans),
        "matched": total_matched,
        "missed": total_missed,
        "adapted": adapted,
        "calendar_synced": cal_synced,
    }

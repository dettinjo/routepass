"""Multi-sport adaptive Training Plan engine (Running, Trail, Cycling, Triathlon).

The code does all the numbers: periodisation, matching activities to sessions, compliance, load
(CTL/ATL/TSB), race predictions and the built-in adaptation rules. The optional AI coach
(routepass.ai.coach) only writes text and proposes changes, which _apply_mutations checks.
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


def _detraining_factor(days_since_last: int | None) -> float:
    """Compute realistic aerobic sharpness factor based on days since last recorded workout."""
    if days_since_last is None:
        return 0.85
    if days_since_last <= 5:
        return 1.0
    if days_since_last <= 14:
        return round(1.0 - (days_since_last - 5) * 0.006, 3)  # up to ~5.4% decay
    if days_since_last <= 30:
        return round(0.946 - (days_since_last - 14) * 0.0045, 3)  # down to ~0.874
    return round(max(0.78, 0.874 - (days_since_last - 30) * 0.0025), 3)


def athlete_baseline(db: Session, prefs: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Compute dynamic multi-sport fitness, recency/detraining decay, and threshold snapshot."""
    today = today or date.today()
    load = insights.training_load(db, today)
    cur = load.get("current") or {}
    series = load.get("series") or []
    ctl = float(cur.get("ctl") or 0.0)
    atl = float(cur.get("atl") or 0.0)
    tsb = float(cur.get("tsb") or 0.0)
    acwr = round(atl / ctl, 2) if ctl >= 5 else None

    ctl_14d_ago = float(series[-15]["ctl"]) if len(series) >= 15 else ctl
    ctl_ramp_per_week = round((ctl - ctl_14d_ago) / 2.0, 1)

    since_90 = today - timedelta(days=90)
    since_28 = today - timedelta(days=28)
    since_14 = today - timedelta(days=14)
    recent_acts = list(
        db.scalars(
            select(Activity)
            .where(Activity.start_time >= since_90.isoformat())
            .order_by(Activity.start_time.desc())
        )
    )

    last_overall_date: date | None = None
    last_by_disc: dict[str, date | None] = {"run": None, "bike": None, "swim": None}
    acts_14d = 0
    acts_42d = 0
    since_42 = today - timedelta(days=42)

    disc_stats: dict[str, dict[str, float]] = {
        "run": {"hours": 0.0, "km": 0.0, "elev_m": 0.0, "count": 0},
        "bike": {"hours": 0.0, "km": 0.0, "elev_m": 0.0, "count": 0},
        "swim": {"hours": 0.0, "km": 0.0, "elev_m": 0.0, "count": 0},
    }
    longest_run_km = 0.0
    longest_bike_km = 0.0
    for a in recent_acts:
        a_date = (a.start_local or a.start_time).date()
        if last_overall_date is None or a_date > last_overall_date:
            last_overall_date = a_date
        if a_date >= since_14:
            acts_14d += 1
        if a_date >= since_42:
            acts_42d += 1

        disc_key: str | None = None
        if a.family == "run":
            disc_key = "run"
        elif a.family == "ride":
            disc_key = "bike"
        elif a.family == "water" or "swim" in (a.sport or "").lower():
            disc_key = "swim"

        if disc_key and (last_by_disc[disc_key] is None or a_date > last_by_disc[disc_key]):
            last_by_disc[disc_key] = a_date

        if a_date < since_28 or not disc_key:
            continue
        hrs = float(a.moving_time_s or 0.0) / 3600.0
        km = float(a.distance_m or 0.0) / 1000.0
        elev = float(a.elevation_gain_m or 0.0)
        if disc_key == "run":
            longest_run_km = max(longest_run_km, km)
        elif disc_key == "bike":
            longest_bike_km = max(longest_bike_km, km)
        d = disc_stats[disc_key]
        d["hours"] += hrs
        d["km"] += km
        d["elev_m"] += elev
        d["count"] += 1

    days_since_last = max(0, (today - last_overall_date).days) if last_overall_date else None
    recency_by_disc = {
        k: {
            "last_date": _iso(v) if v else None,
            "days_ago": max(0, (today - v).days) if v else None,
        }
        for k, v in last_by_disc.items()
    }
    detraining = _detraining_factor(days_since_last)

    if days_since_last is None or days_since_last > 14:
        readiness_label = "Detraining"
        readiness_note = (
            f"Last activity was {days_since_last} days ago — applying {round((1 - detraining) * 100, 1)}% recency decay and easing volume back in."
            if days_since_last is not None
            else "No activities recorded in the last 90 days — starting conservatively from base."
        )
    elif acwr and acwr > 1.35 or tsb < -22:
        readiness_label = "Fatigued"
        readiness_note = (
            f"High acute load (TSB {tsb:+.0f}, ACWR {acwr or '—'}) — prioritize recovery and easy Z2."
        )
    elif tsb > 8 and ctl >= 25:
        readiness_label = "Fresh & Sharp"
        readiness_note = (
            f"Well-rested (TSB {tsb:+.0f}) with solid base fitness (CTL {ctl:.0f}) — ready for key workouts."
        )
    elif ctl_ramp_per_week >= 1.5:
        readiness_label = "Building"
        readiness_note = f"Fitness rising +{ctl_ramp_per_week:.1f} CTL/wk ({acts_14d} sessions in last 14d)."
    else:
        readiness_label = "Steady"
        readiness_note = f"Active {days_since_last}d ago · {acts_14d} sessions in the last 14 days."

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
    confidence_pct = min(
        96,
        max(
            35,
            int(
                40
                + min(30, acts_42d * 2.2)
                + (12 if gap_ms or ftp else 0)
                + (10 if days_since_last is not None and days_since_last <= 5 else 0)
                - (15 if days_since_last is not None and days_since_last > 14 else 0)
            ),
        ),
    )

    return {
        "as_of": _iso(today),
        "ctl": round(ctl, 1),
        "atl": round(atl, 1),
        "tsb": round(tsb, 1),
        "acwr": acwr,
        "ctl_ramp_per_week": ctl_ramp_per_week,
        "days_since_last_activity": days_since_last,
        "last_activity_date": _iso(last_overall_date) if last_overall_date else None,
        "recency_by_discipline": recency_by_disc,
        "detraining_factor": detraining,
        "readiness_label": readiness_label,
        "readiness_note": readiness_note,
        "activities_14d": acts_14d,
        "activities_42d": acts_42d,
        "confidence_pct": confidence_pct,
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

    max_hours = float(
        schedule_prefs.get("max_weekly_hours") or max(5.0, baseline["total_weekly_hours"] * 1.25)
    )
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

        templates = _weekly_templates(
            plan_type, phase, run_km_goal, run_elev_goal, bike_km_goal, bike_elev_goal, swim_km_goal
        )
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
                if s_date < start_date:
                    # Week 1 starts on its Monday, but nothing may be scheduled before the plan exists.
                    first = (start_date - w_start).days
                    free = [c for c in range(first, 7) if c not in rest_days and c not in used_days]
                    if not free:
                        continue
                    d_off = free[0]
                    s_date = w_start + timedelta(days=d_off)
                if phase == "race_week" and s_date >= event_date:
                    continue
                used_days.add(d_off)

            dur_s = round(max(1200.0, week_hours * 3600.0 * share))
            tss = round(
                max(
                    18.0,
                    week_tss * share * (1.15 if stype in ("intervals", "tempo", "hills", "race") else 0.92),
                ),
                0,
            )
            dist_km, elev_m = _estimate_session_volume(
                sport,
                stype,
                dur_s,
                phase,
                run_km_goal,
                run_elev_goal,
                bike_km_goal,
                bike_elev_goal,
                swim_km_goal,
                baseline,
            )
            if stype == "race":
                if plan_type in ("trail_run", "road_run"):
                    dist_km, elev_m = run_km_goal, run_elev_goal
                elif plan_type == "cycling":
                    dist_km, elev_m = bike_km_goal, bike_elev_goal
                elif plan_type == "triathlon":
                    dist_km, elev_m = (
                        round(swim_km_goal + bike_km_goal + run_km_goal, 1),
                        bike_elev_goal + run_elev_goal,
                    )

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
        main_sport = (
            "trail_run"
            if plan_type == "trail_run"
            else (
                "bike"
                if plan_type == "cycling"
                else ("brick" if plan_type in ("triathlon", "duathlon") else "run")
            )
        )
        return [
            (
                1,
                "run" if main_sport != "bike" else "bike",
                "easy",
                "supporting",
                0.30,
                "Shakeout & Strides",
                "Short aerobic opener with 4×20s light strides.",
                ["15m easy Z1-Z2", "4×20s relaxed strides", "10m easy"],
            ),
            (
                3,
                "run" if main_sport != "bike" else "bike",
                "recovery",
                "optional",
                0.20,
                "Pre-Race Mobility & Spin",
                "Keep legs fresh, hydrate and carb-load.",
                ["25m very easy Z1"],
            ),
            (
                6,
                main_sport,
                "race",
                "key",
                0.50,
                "Race Day Execution",
                "Execute pacing & fueling plan cleanly.",
                ["Controlled start first 25%", "Steady fueling every 30-40m", "Strong finish"],
            ),
        ]

    if plan_type == "trail_run":
        if phase in ("build", "peak"):
            return [
                (
                    1,
                    "trail_run",
                    "easy",
                    "supporting",
                    0.16,
                    "Aerobic Trail Run",
                    "Easy conversational Z2 on rolling terrain.",
                    ["10m warmup", "Z2 aerobic trail", "5m cooldown"],
                ),
                (
                    2,
                    "trail_run",
                    "hills",
                    "key",
                    0.18,
                    "Climb Power Repeats",
                    "Sustained uphill efforts at Z3-Z4 focusing on hiking/running efficiency.",
                    ["15m easy", "6×4m uphill Z4 (jog down)", "10m easy"],
                ),
                (
                    3,
                    "trail_run",
                    "recovery",
                    "optional",
                    0.12,
                    "Recovery Jog & Mobility",
                    "Very easy Z1 flush to absorb vertical load.",
                    ["35-45m easy Z1"],
                ),
                (
                    5,
                    "trail_run",
                    "long",
                    "key",
                    0.34,
                    "Long Mountain Trail Run",
                    "Practice race nutrition (60-80g carbs/h) and steady climbing VAM.",
                    ["20m settle in Z2", "Steady mountain Z2 + climbs", "Fuel every 35m"],
                ),
                (
                    6,
                    "trail_run",
                    "long",
                    "key",
                    0.20,
                    "Back-to-Back Fatigue Run",
                    "Steady Z2 on tired legs to build ultra durability.",
                    ["10m gentle start", "Steady Z2 trail", "Walk steep pitches"],
                ),
            ]
        return [
            (
                1,
                "trail_run",
                "easy",
                "supporting",
                0.20,
                "Easy Aerobic Run",
                "Relaxed Z2 effort; keep HR controlled.",
                ["Easy Z2 throughout"],
            ),
            (
                2,
                "trail_run",
                "tempo",
                "key",
                0.20,
                "Rolling Tempo / Threshold",
                "Sustained Z3-Z4 rhythm on undulating trails.",
                ["15m warmup", "2×12m Z3-Z4 (3m easy)", "10m cooldown"],
            ),
            (
                4,
                "trail_run",
                "easy",
                "supporting",
                0.18,
                "Trail Cadence & Strides",
                "Easy run finishing with 6×20s hill strides.",
                ["Easy Z2", "6×20s uphill strides"],
            ),
            (
                6,
                "trail_run",
                "long",
                "key",
                0.42,
                "Weekend Long Trail Run",
                "Build time on feet and vertical gain progressively.",
                ["Steady Z2 effort", "Practice race hydration"],
            ),
        ]

    if plan_type == "cycling":
        return [
            (
                1,
                "bike",
                "intervals",
                "key",
                0.20,
                "Sweet-Spot / Threshold Intervals",
                "Build sustainable climbing & flat power at 88-96% FTP.",
                ["15m warmup", "3×12m @ 90% FTP (4m Z1)", "10m spin"],
            ),
            (
                2,
                "bike",
                "easy",
                "supporting",
                0.18,
                "Endurance Z2 Spin",
                "High-cadence aerobic base ride at 65-75% FTP.",
                ["Steady Z2 endurance"],
            ),
            (
                4,
                "bike",
                "hills",
                "key",
                0.22,
                "Climb Tempo & Torque",
                "Sustained climbs at 80-88% FTP with low-cadence seated work.",
                ["15m warmup", "3×10m climb tempo", "15m easy"],
            ),
            (
                6,
                "bike",
                "long",
                "key",
                0.40,
                "Weekend Endurance Ride",
                "Long aerobic ride targeting race elevation & fueling.",
                ["Steady Z2", "60-80g carbs/h", "Controlled climbs"],
            ),
        ]

    if plan_type == "triathlon":
        return [
            (
                1,
                "swim",
                "intervals",
                "supporting",
                0.14,
                "CSS Swim Threshold",
                "Aerobic efficiency & pacing near Critical Swim Speed.",
                ["300m warmup", "8×100m @ CSS (15s rest)", "200m cooldown"],
            ),
            (
                2,
                "bike",
                "tempo",
                "key",
                0.22,
                "Aero Bike Tempo",
                "Sustained race-position riding at 78-85% FTP.",
                ["15m warmup", "2×20m aero tempo", "10m easy"],
            ),
            (
                3,
                "run",
                "tempo",
                "key",
                0.16,
                "Threshold Run",
                "Controlled Z3-Z4 cruise intervals.",
                ["15m warmup", "4×6m @ threshold GAP (2m jog)", "10m easy"],
            ),
            (
                4,
                "swim",
                "easy",
                "optional",
                0.12,
                "Endurance Swim & Drills",
                "Continuous aerobic swim with catch-up & sighting drills.",
                ["200m drills", "Continuous Z2 swim", "100m easy"],
            ),
            (
                5,
                "brick",
                "brick",
                "key",
                0.24,
                "Race-Sim Brick (Bike → Run)",
                "Longer bike followed immediately by off-the-bike transition run.",
                ["Main bike Z2-Z3", "Quick T2 (<3m)", "15-30m run at goal pace"],
            ),
            (
                6,
                "run",
                "long",
                "key",
                0.12,
                "Steady Aerobic Long Run",
                "Relaxed Z2 run to build run durability.",
                ["Steady Z2 aerobic"],
            ),
        ]

    if plan_type == "duathlon":
        return [
            (
                1,
                "run",
                "intervals",
                "key",
                0.20,
                "Run Threshold Repeats",
                "Z4 intervals to sharpen leg speed.",
                ["15m warmup", "5×5m Z4 (2m jog)", "10m easy"],
            ),
            (
                2,
                "bike",
                "tempo",
                "key",
                0.25,
                "Bike Sweet-Spot",
                "Sustained 85-92% FTP blocks.",
                ["15m warmup", "2×20m sweet-spot", "10m spin"],
            ),
            (
                4,
                "run",
                "easy",
                "supporting",
                0.18,
                "Aerobic Run",
                "Easy Z2 recovery & cadence.",
                ["Steady Z2 run"],
            ),
            (
                6,
                "brick",
                "brick",
                "key",
                0.37,
                "Long Bike-to-Run Brick",
                "Race-specific bike endurance into fast-settling run legs.",
                ["Long bike Z2", "Quick transition", "20-35m steady run"],
            ),
        ]

    # road_run or base_build
    return [
        (1, "run", "easy", "supporting", 0.22, "Easy Aerobic Run", "Conversational Z2 run.", ["Steady Z2"]),
        (
            2,
            "run",
            "intervals",
            "key",
            0.22,
            "Threshold / Cruise Intervals",
            "Build lactate threshold pace cleanly.",
            ["15m warmup", "4×8m @ threshold (2m jog)", "10m cooldown"],
        ),
        (
            4,
            "run" if plan_type == "road_run" else "bike",
            "easy",
            "supporting",
            0.20,
            "Aerobic Volume",
            "Easy Z2 cross-training or aerobic run.",
            ["Steady Z2"],
        ),
        (
            6,
            "run",
            "long",
            "key",
            0.36,
            "Weekend Long Run",
            "Progressive aerobic endurance run.",
            ["Steady Z2", "Last 15% steady Z3"],
        ),
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
    """Create a training plan with the built-in rules. With use_ai the AI coach then writes the
    sessions of the coming weeks in the background (routepass.ai.coach)."""
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
    schedule_prefs["ai_coach"] = bool(use_ai)  # the AI coach writes sessions as weeks come up

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

    # Archive any previous active plan if requested (default: keep one active plan)
    if payload.get("set_active", True):
        for prev in db.scalars(select(TrainingPlan).where(TrainingPlan.status == "active")):
            prev.status = "archived"

    plan = TrainingPlan(
        name=name,
        status="active",
        plan_type=plan_type,
        start_date=_iso(start_date),
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


def plan_first_day(plan: TrainingPlan) -> date:
    """The first day a session may be due: the plan's start, never before it was created."""
    start = _parse_date(plan.start_date, date.today())
    if plan.created_at is not None:
        # Older plans stored the Monday of week 1 even when created mid-week.
        created = plan.created_at.date()
        if 0 < (created - start).days < 7:
            start = created
    return start


def _refresh_week_totals(db: Session, week_ids: set[int]) -> None:
    for week in db.scalars(select(TrainingWeek).where(TrainingWeek.id.in_(week_ids))):
        rows = list(db.scalars(select(TrainingSession).where(TrainingSession.week_id == week.id)))
        week.target_tss = round(sum(float(r.target_tss or 0) for r in rows), 0)
        week.target_duration_s = round(sum(float(r.target_duration_s or 0) for r in rows), 0)
        week.target_distance_km = round(sum(float(r.target_distance_km or 0) for r in rows), 1)
        week.target_elev_m = round(sum(float(r.target_elev_m or 0) for r in rows), 0)
        split: dict[str, float] = {}
        for r in rows:
            if r.sport == "rest":
                continue
            k = "run" if r.sport in ("run", "trail_run") else r.sport
            split[k] = round(split.get(k, 0.0) + float(r.target_duration_s or 0) / 3600.0, 2)
        week.discipline_split = split


def _drop_sessions_before_start(
    db: Session, plan: TrainingPlan, sessions: list[TrainingSession]
) -> list[TrainingSession]:
    """Plans created before this fix scheduled week 1 from its Monday, so days that had already passed
    showed up as missed. Unmatched sessions before the plan's first day are removed."""
    first_day = plan_first_day(plan)
    stale = [
        s
        for s in sessions
        if s.matched_activity_id is None
        and s.status in ("planned", "missed", "moved")
        and _parse_date(s.scheduled_date, first_day) < first_day
    ]
    if not stale:
        return sessions
    weeks = {s.week_id for s in stale}
    for s in stale:
        db.delete(s)
    db.flush()
    _refresh_week_totals(db, weeks)
    return [s for s in sessions if s not in stale]


def match_activities_to_plan(db: Session, plan: TrainingPlan, *, today: date | None = None) -> dict[str, int]:
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
    sessions = _drop_sessions_before_start(db, plan, sessions)
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
                dur_ratio = (
                    (float(a.moving_time_s or 0.0) / max(1.0, s.target_duration_s))
                    if s.target_duration_s
                    else 1.0
                )
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
    apply_detraining: bool = True,
) -> dict[str, Any]:
    """Estimate race finish time in seconds for the given CTL, baseline, and recency/detraining."""
    targets = (plan.goal_spec or {}).get("targets") or {}
    cur_ctl = max(15.0, float(baseline.get("ctl") or 25.0))
    ctl_ratio = max(0.75, min(1.30, (ctl_value + 25.0) / (cur_ctl + 25.0)))
    detrain = float(baseline.get("detraining_factor") or 1.0) if apply_detraining else 1.0
    speed_gain = math.pow(ctl_ratio, 0.18) * durability_factor * detrain

    if plan.plan_type in ("trail_run", "road_run"):
        dist_km = float(targets.get("run_km") or (50.0 if plan.plan_type == "trail_run" else 21.1))
        elev_m = float(targets.get("run_elev_m") or (2000.0 if plan.plan_type == "trail_run" else 150.0))
        gap_ms = float(baseline.get("median_gap_ms") or 2.85) * speed_gain
        vam = float(baseline.get("median_climb_vam_mh") or 650.0) * speed_gain
        riegel = math.pow(max(1.0, dist_km / 10.0), 0.075 if plan.plan_type == "trail_run" else 0.06)
        flat_s = (dist_km * 1000.0) / max(1.2, gap_ms) * riegel
        climb_s = (elev_m / max(300.0, vam)) * 3600.0 * 0.55 if elev_m > 0 else 0.0
        total_s = round(flat_s + climb_s)
        return {"total_s": total_s, "splits": {"run_s": total_s}, "gap_ms": gap_ms, "vam": vam}

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
        return {"total_s": total_s, "splits": {"bike_s": total_s}, "ftp_w": ftp, "avg_np": round(ftp * 0.78)}

    # Triathlon or Duathlon
    swim_km = float(targets.get("swim_km") or (1.9 if plan.plan_type == "triathlon" else 0.0))
    bike_km = float(targets.get("bike_km") or 90.0)
    bike_elev = float(targets.get("bike_elev_m") or 700.0)
    run_km = float(targets.get("run_km") or 21.1)
    run_elev = float(targets.get("run_elev_m") or 100.0)

    css = float(baseline.get("swim_css_s_per_100m") or 125.0) / max(0.7, speed_gain)
    swim_s = round(swim_km * 10.0 * css) if swim_km > 0 else 0

    ftp = float(baseline.get("ftp_w") or 210.0) * speed_gain
    weight = float(baseline.get("weight_kg") or 72.0) + 9.0
    bike_kmh = max(21.0, min(40.0, 17.5 + (ftp / weight) * 4.4))
    bike_s = round((bike_km / bike_kmh) * 3600.0 + (bike_elev / 700.0) * 3600.0 * 0.5)

    gap_ms = float(baseline.get("median_gap_ms") or 2.85) * speed_gain
    run_s = round(((run_km * 1000.0) / max(1.2, gap_ms)) * 1.07 + (run_elev / 650.0) * 3600.0 * 0.5)
    transitions_s = 360 if plan.plan_type == "triathlon" else 240
    total_s = swim_s + bike_s + run_s + transitions_s
    return {
        "total_s": total_s,
        "splits": {"swim_s": swim_s, "bike_s": bike_s, "run_s": run_s, "transitions_s": transitions_s},
        "css": css,
        "avg_np": round(ftp * 0.76),
    }


def _build_simulated_race_activity(
    plan: TrainingPlan,
    baseline: dict[str, Any],
    pred_race: dict[str, Any],
) -> dict[str, Any]:
    """Build a completed-activity-style preview of Race Day with predicted times, speed/pace, and splits."""
    targets = (plan.goal_spec or {}).get("targets") or {}
    total_s = max(1, int(pred_race["total_s"]))
    target_time_s = (plan.goal_spec or {}).get("target_time_s")
    delta_s = (total_s - int(target_time_s)) if target_time_s else None
    hrs = total_s / 3600.0
    carbs_g = round(hrs * 70) if hrs >= 1.25 else round(hrs * 40)
    calories = round(hrs * 680)
    est_tss = round(hrs * 72)

    if plan.plan_type in ("trail_run", "road_run"):
        dist_km = float(targets.get("run_km") or (50.0 if plan.plan_type == "trail_run" else 21.1))
        elev_m = float(targets.get("run_elev_m") or (2000.0 if plan.plan_type == "trail_run" else 150.0))
        avg_speed_kmh = round(dist_km / max(0.01, hrs), 2)
        avg_pace_s = round(total_s / max(0.1, dist_km))
        gap_ms = float(pred_race.get("gap_ms") or baseline.get("median_gap_ms") or 2.85)
        gap_s = round(1000.0 / max(1.0, gap_ms))
        effort_km = round(dist_km + elev_m / 100.0, 1)
        # Quarter-by-quarter pacing with slight realistic late-race fade
        q_weights = [0.235, 0.245, 0.255, 0.265]
        q_labels = ["Q1 · Controlled Start", "Q2 · Steady Rhythm", "Q3 · Aerobic Grind", "Q4 · Strong Finish"]
        splits = []
        cum_s = 0
        for w, lbl in zip(q_weights, q_labels):
            qs = round(total_s * w)
            cum_s += qs
            qkm = round(dist_km / 4.0, 1)
            qelev = round(elev_m / 4.0)
            splits.append(
                {
                    "label": lbl,
                    "distance_km": qkm,
                    "elev_m": qelev,
                    "time_s": qs,
                    "cumulative_s": cum_s,
                    "pace_s_per_km": round(qs / max(0.1, qkm)),
                    "speed_kmh": round(qkm / max(0.01, qs / 3600.0), 1),
                    "note": f"~{round((qs / 3600.0) * 70)}g carbs" if hrs >= 1.5 else "Steady HR Z2-Z3",
                }
            )
        return {
            "name": plan.name,
            "date": plan.event_date,
            "sport": "TrailRun" if plan.plan_type == "trail_run" else "Run",
            "distance_km": round(dist_km, 1),
            "elevation_gain_m": round(elev_m),
            "effort_km": effort_km,
            "predicted_time_s": total_s,
            "target_time_s": target_time_s,
            "delta_s": delta_s,
            "avg_speed_kmh": avg_speed_kmh,
            "avg_pace_s_per_km": avg_pace_s,
            "gap_s_per_km": gap_s,
            "estimated_tss": est_tss,
            "estimated_calories": calories,
            "estimated_carbs_g": carbs_g,
            "confidence_pct": baseline.get("confidence_pct", 70),
            "splits": splits,
        }

    if plan.plan_type == "cycling":
        dist_km = float(targets.get("bike_km") or 120.0)
        elev_m = float(targets.get("bike_elev_m") or 1500.0)
        avg_speed_kmh = round(dist_km / max(0.01, hrs), 1)
        q_weights = [0.24, 0.25, 0.255, 0.255]
        q_labels = ["Q1 · Warmup & Group", "Q2 · Climb Tempo", "Q3 · Endurance Fueling", "Q4 · Final Push"]
        splits = []
        cum_s = 0
        for w, lbl in zip(q_weights, q_labels):
            qs = round(total_s * w)
            cum_s += qs
            qkm = round(dist_km / 4.0, 1)
            splits.append(
                {
                    "label": lbl,
                    "distance_km": qkm,
                    "elev_m": round(elev_m / 4.0),
                    "time_s": qs,
                    "cumulative_s": cum_s,
                    "speed_kmh": round(qkm / max(0.01, qs / 3600.0), 1),
                    "note": f"~{pred_race.get('avg_np', 175)}W NP",
                }
            )
        return {
            "name": plan.name,
            "date": plan.event_date,
            "sport": "Ride",
            "distance_km": round(dist_km, 1),
            "elevation_gain_m": round(elev_m),
            "predicted_time_s": total_s,
            "target_time_s": target_time_s,
            "delta_s": delta_s,
            "avg_speed_kmh": avg_speed_kmh,
            "avg_np_w": pred_race.get("avg_np"),
            "estimated_tss": est_tss,
            "estimated_calories": calories,
            "estimated_carbs_g": carbs_g,
            "confidence_pct": baseline.get("confidence_pct", 70),
            "splits": splits,
        }

    # Triathlon / Duathlon
    swim_km = float(targets.get("swim_km") or (1.9 if plan.plan_type == "triathlon" else 0.0))
    bike_km = float(targets.get("bike_km") or 90.0)
    bike_elev = float(targets.get("bike_elev_m") or 700.0)
    run_km = float(targets.get("run_km") or 21.1)
    run_elev = float(targets.get("run_elev_m") or 100.0)
    sp = pred_race.get("splits") or {}
    legs = []
    cum = 0
    if sp.get("swim_s"):
        cum += sp["swim_s"]
        legs.append(
            {
                "label": "Swim",
                "distance_km": swim_km,
                "elev_m": 0,
                "time_s": sp["swim_s"],
                "cumulative_s": cum,
                "speed_kmh": round(swim_km / max(0.01, sp["swim_s"] / 3600.0), 1),
                "note": f"~{round(sp['swim_s'] / max(0.1, swim_km * 10))}s / 100m",
            }
        )
    if sp.get("bike_s"):
        cum += sp["bike_s"]
        legs.append(
            {
                "label": "Bike",
                "distance_km": bike_km,
                "elev_m": round(bike_elev),
                "time_s": sp["bike_s"],
                "cumulative_s": cum,
                "speed_kmh": round(bike_km / max(0.01, sp["bike_s"] / 3600.0), 1),
                "note": f"~{pred_race.get('avg_np', 170)}W NP · 75g carbs/h",
            }
        )
    if sp.get("run_s"):
        cum += sp["run_s"]
        legs.append(
            {
                "label": "Run (Off-the-Bike)",
                "distance_km": run_km,
                "elev_m": round(run_elev),
                "time_s": sp["run_s"],
                "cumulative_s": cum,
                "pace_s_per_km": round(sp["run_s"] / max(0.1, run_km)),
                "speed_kmh": round(run_km / max(0.01, sp["run_s"] / 3600.0), 1),
                "note": "Includes 7% brick fatigue",
            }
        )
    if sp.get("transitions_s"):
        cum += sp["transitions_s"]
        legs.append(
            {
                "label": "T1 + T2 Transitions",
                "distance_km": 0,
                "elev_m": 0,
                "time_s": sp["transitions_s"],
                "cumulative_s": cum,
                "note": "Swim→Bike & Bike→Run",
            }
        )
    total_km = round(swim_km + bike_km + run_km, 1)
    return {
        "name": plan.name,
        "date": plan.event_date,
        "sport": "Triathlon" if plan.plan_type == "triathlon" else "Duathlon",
        "distance_km": total_km,
        "elevation_gain_m": round(bike_elev + run_elev),
        "predicted_time_s": total_s,
        "target_time_s": target_time_s,
        "delta_s": delta_s,
        "avg_speed_kmh": round(total_km / max(0.01, hrs), 1),
        "estimated_tss": est_tss,
        "estimated_calories": calories,
        "estimated_carbs_g": carbs_g,
        "confidence_pct": baseline.get("confidence_pct", 70),
        "splits": legs,
    }


def _compute_gamification(
    sessions: list[TrainingSession],
    alignment_overall: float,
    baseline: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    """Compute XP, level, completion streak, and motivational badges."""
    completed = [s for s in sessions if s.status == "completed"]
    partial = [s for s in sessions if s.status == "partial"]
    key_done = [s for s in completed if s.priority == "key"]
    cal_synced = any(s.gcal_event_id for s in sessions)

    # Streak of most recent due sessions completed/partial
    due_past = [s for s in sessions if s.sport != "rest" and _parse_date(s.scheduled_date, today) <= today]
    streak = 0
    for s in reversed(due_past):
        if s.status in ("completed", "partial"):
            streak += 1
        elif s.status in ("missed",):
            break

    xp = (
        len(completed) * 100
        + len(partial) * 55
        + len(key_done) * 60
        + streak * 25
        + int(baseline.get("activities_42d", 0)) * 15
    )
    level = max(1, (xp // 400) + 1)
    titles = [
        "Trail Rookie",
        "Consistent Mover",
        "Endurance Builder",
        "Mountain Climber",
        "Ultra Engine",
        "Peak Performer",
        "Apex Athlete",
    ]
    level_title = titles[min(len(titles) - 1, level - 1)]
    xp_in_level = xp % 400
    xp_progress_pct = round((xp_in_level / 400.0) * 100)

    badges: list[dict[str, str]] = []
    if streak >= 3:
        badges.append({"id": "streak", "icon": "flame", "label": f"{streak}-Session Streak", "tone": "good"})
    if alignment_overall >= 85 and due_past:
        badges.append({"id": "aligned", "icon": "target", "label": "85%+ Plan Alignment", "tone": "good"})
    if len(key_done) >= 2:
        badges.append(
            {
                "id": "key_ace",
                "icon": "bolt",
                "label": f"{len(key_done)} Key Workouts Crushed",
                "tone": "warn",
            }
        )
    if (baseline.get("weekly_avg", {}).get("run", {}).get("elev_m") or 0) >= 800:
        badges.append({"id": "vert", "icon": "mountain", "label": "Vert Hunter", "tone": "good"})
    if baseline.get("days_since_last_activity") is not None and baseline["days_since_last_activity"] <= 2:
        badges.append({"id": "fresh", "icon": "heart", "label": "Active Momentum", "tone": "good"})
    if cal_synced:
        badges.append({"id": "calendar", "icon": "calendar", "label": "Calendar Auto-Synced", "tone": ""})

    return {
        "xp": xp,
        "level": level,
        "level_title": level_title,
        "xp_next_level": level * 400,
        "xp_progress_pct": xp_progress_pct,
        "streak_sessions": streak,
        "completed_sessions": len(completed),
        "badges": badges,
    }


def compute_plan_analytics(
    db: Session, plan: TrainingPlan, prefs: dict[str, Any], *, today: date | None = None
) -> dict[str, Any]:
    """Compute alignment score, discipline progress, race prediction, gamification, and trajectory graph."""
    today = today or date.today()
    baseline = athlete_baseline(db, prefs, today)
    quality = insights.data_quality(db, today)
    first_day = plan_first_day(plan)
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
        {a.id: a for a in db.scalars(select(Activity).where(Activity.id.in_(act_ids)))} if act_ids else {}
    )

    due = [
        s
        for s in sessions
        if s.sport != "rest" and first_day <= _parse_date(s.scheduled_date, today) <= today
    ]
    # Too little history to judge adherence: no score, no "at risk" from one or two sessions.
    enough_data = len(due) >= 3 and (today - first_day).days >= 10
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
            dk,
            {
                "planned_hours": 0.0,
                "actual_hours": 0.0,
                "planned_km": 0.0,
                "actual_km": 0.0,
                "planned_sessions": 0,
                "completed_sessions": 0,
            },
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

    load_series = insights.training_load(db, today).get("series") or []
    ctl_by_day = {pt["date"]: float(pt["ctl"]) for pt in load_series}

    start_ctl = float((plan.baseline or {}).get("ctl") or baseline["ctl"] or 25.0)
    cur_ctl = float(baseline["ctl"] or start_ctl)
    adherence_factor = max(0.45, min(1.05, alignment_overall / 100.0)) if due else 0.92

    planned_ctl = start_ctl
    proj_opt_ctl = cur_ctl
    proj_trend_ctl = cur_ctl
    decay = 1.0 - math.exp(-7.0 / 42.0)

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
        pred = _predict_race_time_s(plan, baseline, ref_ctl, apply_detraining=not is_future)
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

    pred_now = _predict_race_time_s(plan, baseline, cur_ctl, apply_detraining=True)
    pred_race_optimal = _predict_race_time_s(plan, baseline, race_ctl_optimal, apply_detraining=False)
    pred_race_trend = _predict_race_time_s(plan, baseline, race_ctl_trend, apply_detraining=False)
    simulated_activity = _build_simulated_race_activity(plan, baseline, pred_race_trend)
    target_time_s = (plan.goal_spec or {}).get("target_time_s")

    limiting_factors: list[str] = []
    attention: list[dict[str, Any]] = []
    if not target_time_s and not enough_data:
        verdict = "early"
    elif target_time_s:
        gap_pct = (pred_race_trend["total_s"] - float(target_time_s)) / max(1.0, float(target_time_s)) * 100.0
        if gap_pct <= 2.5:
            verdict = "on_track"
        elif gap_pct <= 8.0:
            verdict = "catchable"
            limiting_factors.append(
                f"Projected finish is {gap_pct:.1f}% slower than goal time at current adherence."
            )
        else:
            verdict = "at_risk"
            limiting_factors.append(
                f"Projected finish is {gap_pct:.1f}% slower than goal time — boost key session hit rate or adjust goal."
            )
    else:
        ctl_gap = (race_ctl_trend - race_ctl_planned) / max(1.0, race_ctl_planned) * 100.0
        if alignment_overall >= 80 and ctl_gap >= -8:
            verdict = "on_track"
        elif alignment_overall >= 60:
            verdict = "catchable"
            limiting_factors.append(
                "Plan adherence is moderate — hitting upcoming key sessions will close the gap."
            )
        else:
            verdict = "at_risk"
            limiting_factors.append("Recent missed sessions are pulling projected race fitness below plan.")

    for text in limiting_factors:
        attention.append({"level": "warn", "text": text, "action": "adapt"})
    if baseline.get("days_since_last_activity") is not None and baseline["days_since_last_activity"] > 7:
        text = f"Last recorded activity was {baseline['days_since_last_activity']} days ago — the prediction includes some fitness loss."
        limiting_factors.append(text)
        attention.append({"level": "warn", "text": text, "action": None})
    if baseline.get("acwr") and baseline["acwr"] > 1.35:
        text = (
            f"Load is rising fast (ACWR {baseline['acwr']:.2f}) — prioritise sleep and keep easy days easy."
        )
        limiting_factors.append(text)
        attention.append({"level": "warn", "text": text, "action": None})
    if enough_data and s_key < 75:
        text = f"Key session hit rate is {s_key:.0f}% — protect the weekend long sessions."
        limiting_factors.append(text)
        attention.append({"level": "warn", "text": text, "action": "adapt"})
    if quality["level"] != "high" and quality["activities"] > 0 and quality["missing"]:
        attention.append(
            {
                "level": "info",
                "text": "Training load is mostly estimated from duration — add your heart-rate values for tighter predictions.",
                "action": "profile",
            }
        )

    # Uncertainty band: wider when load is estimated or history is thin.
    range_pct = {"high": 0.04, "medium": 0.07, "low": 0.1}[quality["level"]]
    if (baseline.get("confidence_pct") or 70) < 60:
        range_pct += 0.03
    trend_s = float(pred_race_trend["total_s"] or 0)

    def _round5(v: float) -> int:
        return int(round(v / 300.0) * 300)

    event_d = _parse_date(plan.event_date, today)
    days_to_race = (event_d - today).days
    current_week = next(
        (
            w
            for w in weeks
            if _parse_date(w.start_date, today)
            <= today
            <= _parse_date(w.start_date, today) + timedelta(days=6)
        ),
        weeks[0] if weeks else None,
    )
    gamification = _compute_gamification(sessions, alignment_overall, baseline, today)

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
            "enough_data": enough_data,
        },
        "disciplines": disc_progress,
        "gamification": gamification,
        "prediction": {
            "target_time_s": target_time_s,
            "current_predicted_s": pred_now["total_s"],
            "race_day_optimal_s": pred_race_optimal["total_s"],
            "race_day_trend_s": pred_race_trend["total_s"],
            "race_day_splits": pred_race_trend["splits"],
            "simulated_activity": simulated_activity,
            "verdict": verdict,
            "limiting_factors": limiting_factors,
            "attention": attention,
            "range_low_s": _round5(trend_s * (1 - range_pct)) if trend_s else None,
            "range_high_s": _round5(trend_s * (1 + range_pct)) if trend_s else None,
            "range_pct": round(range_pct * 100),
        },
        "data_quality": quality,
        "first_day": _iso(first_day),
        "trajectory": trajectory,
    }


def _state_hash(recent: list[TrainingSession], upcoming: list[TrainingSession], user_note: str) -> str:
    sig = {
        "recent": [(s.id, s.status, s.compliance_score, s.scheduled_date) for s in recent],
        "upcoming": [(s.id, s.status, s.scheduled_date, s.target_duration_s, s.target_tss) for s in upcoming],
        "note": user_note.strip().lower(),
    }
    return hashlib.sha256(json.dumps(sig, sort_keys=True).encode()).hexdigest()[:32]


def ai_enabled(db: Session, plan: TrainingPlan | None = None) -> bool:
    """The AI coach works on this plan: a key is set, budget is left and the plan has it on."""
    cfg = gemini.get_ai_config(db)
    if not cfg["configured"] or cfg["remaining_usd"] <= 0:
        return False
    return plan is None or bool((plan.schedule_prefs or {}).get("ai_coach", True))


def ai_info(db: Session) -> dict[str, Any]:
    """Gemini configuration and spend plus what the AI coach is doing right now."""
    from routepass.ai import coach

    return {**gemini.get_ai_config(db), "coach": coach.status()}


def prepare_adaptation(
    db: Session,
    plan: TrainingPlan,
    prefs: dict[str, Any],
    *,
    user_note: str = "",
    today: date | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Match activities and gather what an adaptation looks at. Returns {"changed": False, ...} when
    nothing happened since the last adaptation, else the context for finish_adaptation, including the
    compact payload the AI coach gets."""
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
        return {"changed": False, "match": match_stats}

    baseline = athlete_baseline(db, prefs, today)
    payload = {
        "today": _iso(today),
        "plan_name": plan.name,
        "plan_type": plan.plan_type,
        "event_date": plan.event_date,
        "athlete_load": {k: baseline.get(k) for k in ("ctl", "atl", "tsb", "acwr")},
        "user_note": user_note.strip()[:600],
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
                "felt": s.feel,
                "rpe": s.rpe,
                "athlete_note": s.feedback_note,
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
        "rest_days": (plan.schedule_prefs or {}).get("rest_days", []),
    }
    return {
        "changed": True,
        "match": match_stats,
        "today": _iso(today),
        "user_note": user_note,
        "recent_ids": [s.id for s in recent],
        "upcoming_ids": [s.id for s in upcoming],
        "baseline": baseline,
        "payload": payload,
    }


def finish_adaptation(
    db: Session,
    plan: TrainingPlan,
    ctx: dict[str, Any],
    *,
    trigger: str,
    ai: dict[str, Any] | None = None,
    ai_error: str | None = None,
) -> dict[str, Any]:
    """Apply an adaptation: the AI coach's proposal (checked first) when there is one, else the
    built-in rules. Records it in the plan's history and syncs the calendar."""
    today = _parse_date(ctx["today"], date.today())
    by_id = {s.id: s for s in db.scalars(select(TrainingSession).where(TrainingSession.plan_id == plan.id))}
    recent = [by_id[i] for i in ctx["recent_ids"] if i in by_id]
    upcoming = [
        by_id[i] for i in ctx["upcoming_ids"] if i in by_id and by_id[i].status in ("planned", "moved")
    ]

    if ai is not None:
        summary = str(ai.get("summary") or "").strip()[:600]
        mutations = [m for m in (ai.get("mutations") or []) if isinstance(m, dict)]
        model_used = str(ai.get("model") or "ai")
    else:
        summary, mutations = _deterministic_adapt(recent, upcoming, ctx["baseline"], today, ctx["user_note"])
        model_used = "deterministic"

    diff, rejected = _apply_mutations(
        db, plan, list(by_id.values()), mutations, today, allowed_ids={s.id for s in upcoming}
    )
    plan.last_adapted_hash = _state_hash(recent, upcoming, ctx["user_note"])
    if not summary:
        summary = (
            f"Adjusted {len(diff)} upcoming session(s) based on recent training."
            if diff
            else "Your upcoming schedule looks well-balanced — no changes needed."
        )
    db.add(
        PlanAdaptation(
            plan_id=plan.id,
            trigger=trigger[:32],
            model_used=model_used,
            summary=summary,
            diff=diff,
            details={"rejected": rejected, "user_note": ctx["user_note"][:300]}
            if rejected or ctx["user_note"]
            else None,
            ai_error=(ai_error or None) and ai_error[:300],
        )
    )
    db.flush()
    cal_sync = _maybe_sync_calendar(db, plan)
    return {
        "adapted": True,
        "model_used": model_used,
        "summary": summary,
        "diff": diff,
        "rejected": rejected,
        "ai_error": ai_error,
        "match": ctx["match"],
        "calendar_sync": cal_sync,
    }


def adapt_plan(
    db: Session,
    plan: TrainingPlan,
    prefs: dict[str, Any],
    *,
    trigger: str = "manual",
    user_note: str = "",
    today: date | None = None,
    force: bool = False,
    ai_error: str | None = None,
) -> dict[str, Any]:
    """Adapt the next 14 days with the built-in rules, right away. The AI coach does the same in the
    background (routepass.ai.coach.adapt), calling Gemini between prepare and finish."""
    ctx = prepare_adaptation(db, plan, prefs, user_note=user_note, today=today, force=force)
    if not ctx["changed"]:
        return {
            "adapted": False,
            "reason": "No changes since last adaptation",
            "match": ctx["match"],
            "diff": [],
        }
    return finish_adaptation(db, plan, ctx, trigger=trigger, ai_error=ai_error)


def _maybe_sync_calendar(db: Session, plan: TrainingPlan) -> dict[str, Any] | None:
    """Best-effort Google Calendar sync when connected and auto_sync is enabled."""
    try:
        from routepass.providers import gcal

        cfg = gcal.get_config(db)
        if cfg.get("connected") and cfg.get("target_calendar_id") and cfg.get("auto_sync", True):
            return gcal.sync_plan_to_calendar(db, plan)
    except Exception:  # noqa: BLE001
        logger.exception("Auto Google Calendar sync failed for plan %s", plan.id)
    return None


def skip_and_adapt_session(
    db: Session,
    session: TrainingSession,
    prefs: dict[str, Any],
    *,
    reason: str,
    severity: str = "moderate",
    note: str = "",
    today: date | None = None,
) -> dict[str, Any]:
    """Skip or convert a session based on athlete feedback (time, sickness, muscle_pain, fatigue, injury),
    schedule protective recovery/mobility sessions where appropriate, adapt upcoming days, and sync calendar.
    """
    today = today or date.today()
    plan = db.get(TrainingPlan, session.plan_id)
    if plan is None:
        raise ValueError("Training plan not found for session")

    s_date = _parse_date(session.scheduled_date, today)
    reason_l = reason.strip().lower()
    sev = severity.strip().lower() if severity in ("mild", "moderate", "severe") else "moderate"
    user_extra = note.strip()[:250]

    upcoming_sessions = list(
        db.scalars(
            select(TrainingSession)
            .where(
                TrainingSession.plan_id == plan.id,
                TrainingSession.id != session.id,
                TrainingSession.status.in_(("planned", "moved")),
            )
            .order_by(TrainingSession.scheduled_date.asc(), TrainingSession.id.asc())
        )
    )

    immediate_actions: list[str] = []
    recovery_planned = False

    if reason_l == "time":
        session.status = "skipped"
        session.compliance_score = 0.0
        session.adaptation_note = f"Skipped (no time){': ' + user_extra if user_extra else ''}"
        immediate_actions.append(f"Marked '{session.title}' as skipped due to time constraints.")

    elif reason_l in ("muscle_pain", "fatigue"):
        if sev == "severe" or s_date < today:
            session.status = "skipped"
            session.compliance_score = 0.0
            session.adaptation_note = (
                f"Skipped ({reason_l.replace('_', ' ')}, {sev}){': ' + user_extra if user_extra else ''}"
            )
            immediate_actions.append(
                f"Skipped '{session.title}' for full rest ({reason_l.replace('_', ' ')})."
            )
        else:
            # Convert today's/upcoming session directly into a gentle recovery & mobility session
            dur_s = 1500 if sev == "moderate" else 1800
            session.sport = "strength"
            session.session_type = "recovery"
            session.priority = "supporting"
            session.title = "Active Recovery & Mobility Flow"
            session.description = (
                "Low-impact foam rolling, hip/calf/hamstring mobility, and easy walking to flush soreness "
                "without adding mechanical stress."
            )
            session.workout_steps = [
                "10 min easy walk or gentle spin (Z1)",
                "10 min dynamic mobility & hip/ankle opener",
                "5-10 min foam rolling & light stretching on sore muscles",
            ]
            session.target_duration_s = dur_s
            session.target_distance_km = 0.0
            session.target_elev_m = 0.0
            session.target_tss = 15.0
            session.status = "moved"
            session.adaptation_note = f"Converted to recovery ({reason_l.replace('_', ' ')}, {sev})"
            recovery_planned = True
            immediate_actions.append(
                f"Converted '{session.title}' into a {dur_s // 60} min Recovery & Mobility session."
            )

        # Protect the next 2-3 days from intensity spikes
        horizon = s_date + timedelta(days=3 if sev == "severe" else 2)
        for nxt in upcoming_sessions:
            nd = _parse_date(nxt.scheduled_date, today)
            if not (s_date < nd <= horizon):
                continue
            if sev == "severe" and not recovery_planned:
                nxt.sport = "strength"
                nxt.session_type = "recovery"
                nxt.priority = "supporting"
                nxt.title = "Gentle Recovery & Mobility Check-in"
                nxt.description = "Easy movement check-in before resuming normal training load."
                nxt.target_duration_s = 1500
                nxt.target_distance_km = 0.0
                nxt.target_elev_m = 0.0
                nxt.target_tss = 15.0
                nxt.status = "moved"
                nxt.adaptation_note = f"Recovery day inserted after severe {reason_l.replace('_', ' ')}"
                recovery_planned = True
                immediate_actions.append(f"Replaced {nxt.scheduled_date} with a 25 min Recovery Check-in.")
            elif nxt.session_type in ("intervals", "threshold", "hills", "long", "brick"):
                scale = 0.72 if sev == "severe" else 0.82
                nxt.target_duration_s = round(nxt.target_duration_s * scale)
                nxt.target_distance_km = round(nxt.target_distance_km * scale, 1)
                nxt.target_elev_m = round(nxt.target_elev_m * scale, 0)
                nxt.target_tss = round(nxt.target_tss * scale, 0)
                nxt.adaptation_note = f"Volume trimmed {round((1 - scale) * 100)}% for recovery"
                immediate_actions.append(
                    f"Trimmed {nxt.title} on {nxt.scheduled_date} by {round((1 - scale) * 100)}%."
                )

    elif reason_l == "sickness":
        session.status = "skipped"
        session.compliance_score = 0.0
        session.adaptation_note = f"Skipped (sickness, {sev}){': ' + user_extra if user_extra else ''}"
        days_off = 2 if sev == "mild" else (3 if sev == "moderate" else 5)
        cutoff = s_date + timedelta(days=days_off)
        immediate_actions.append(
            f"Skipped '{session.title}' and protected the next {days_off} days for illness recovery."
        )

        window_sessions = [
            nxt for nxt in upcoming_sessions if s_date < _parse_date(nxt.scheduled_date, today) <= cutoff
        ]
        for idx, nxt in enumerate(window_sessions):
            is_last = idx == len(window_sessions) - 1
            if is_last:
                nxt.session_type = "recovery"
                nxt.priority = "supporting"
                nxt.title = "Easy Return-to-Training Shakeout"
                nxt.description = "Only complete if fever-free for 24h and resting HR is back to normal. Keep strictly Z1-Z2."
                nxt.target_duration_s = 1500
                nxt.target_distance_km = round(min(nxt.target_distance_km or 4.0, 4.0), 1)
                nxt.target_elev_m = 0.0
                nxt.target_tss = 18.0
                nxt.status = "moved"
                nxt.adaptation_note = "Gentle return shakeout after sickness"
                recovery_planned = True
                immediate_actions.append(f"Scheduled Easy Return Shakeout on {nxt.scheduled_date}.")
            else:
                nxt.status = "skipped"
                nxt.compliance_score = 0.0
                nxt.adaptation_note = f"Auto-cleared for sickness recovery ({sev})"
                immediate_actions.append(f"Cleared {nxt.title} on {nxt.scheduled_date} for rest.")

    elif reason_l == "injury":
        session.status = "skipped"
        session.compliance_score = 0.0
        session.adaptation_note = f"Skipped (injury/pain, {sev}){': ' + user_extra if user_extra else ''}"
        days_protect = 3 if sev == "mild" else (5 if sev == "moderate" else 7)
        cutoff = s_date + timedelta(days=days_protect)
        immediate_actions.append(
            f"Skipped '{session.title}' and protected the next {days_protect} days against impact load."
        )
        for nxt in upcoming_sessions:
            nd = _parse_date(nxt.scheduled_date, today)
            if not (s_date < nd <= cutoff):
                continue
            if sev == "severe":
                nxt.status = "skipped"
                nxt.compliance_score = 0.0
                nxt.adaptation_note = "Paused due to injury — consult physio before resuming"
            elif nxt.sport in ("run", "trail_run", session.sport):
                nxt.sport = "strength"
                nxt.session_type = "recovery"
                nxt.priority = "supporting"
                nxt.title = "Low-Impact Rehab & Mobility"
                nxt.description = "Pain-free mobility, core stability, and gentle non-impact work."
                nxt.target_duration_s = 1800
                nxt.target_distance_km = 0.0
                nxt.target_elev_m = 0.0
                nxt.target_tss = 16.0
                nxt.status = "moved"
                nxt.adaptation_note = f"Swapped to low-impact rehab ({sev} injury)"
                recovery_planned = True
                immediate_actions.append(f"Swapped {nxt.scheduled_date} to Low-Impact Rehab & Mobility.")

    else:
        session.status = "skipped"
        session.compliance_score = 0.0
        session.adaptation_note = f"Skipped ({reason_l}){': ' + user_extra if user_extra else ''}"

    db.flush()

    coach_note = (
        f"Athlete reported '{reason_l}' (severity: {sev}) for session '{session.title}' on {session.scheduled_date}. "
        f"{'Note: ' + user_extra + '. ' if user_extra else ''}"
        f"Immediate actions already applied: {' '.join(immediate_actions)} "
        "Adapt remaining upcoming sessions smoothly without overloading recovery."
    )
    if ai_enabled(db, plan):
        # the caller commits, then hands this to the AI coach (routepass.ai.coach.submit_adapt)
        adapt_res = {"queued": True, "trigger": f"skip_{reason_l}", "user_note": coach_note}
    else:
        adapt_res = adapt_plan(
            db,
            plan,
            prefs,
            trigger=f"skip_{reason_l}",
            user_note=coach_note,
            today=today,
            force=True,
        )
    return {
        "session_id": session.id,
        "reason": reason_l,
        "severity": sev,
        "recovery_planned": recovery_planned,
        "immediate_actions": immediate_actions,
        "adaptation": adapt_res,
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

    tired = any(
        w in user_note.lower()
        for w in ("tired", "fatigue", "sore", "sick", "heavy", "pain", "injury", "muscle_pain")
    )
    high_acwr = (baseline.get("acwr") or 0.0) > 1.35 or (baseline.get("tsb") or 0.0) < -22

    non_recovery = [s for s in upcoming if s.session_type != "recovery"]
    if (tired or high_acwr) and non_recovery:
        nxt = non_recovery[0]
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
    if missed_keys and non_recovery and not tired:
        mk = missed_keys[-1]
        easy_slot = next((s for s in non_recovery[:5] if s.priority != "key"), None)
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


# What the AI coach may set a session to, and which types count as hard days.
SESSION_TYPES = ("easy", "long", "tempo", "intervals", "hills", "recovery", "strides", "brick", "strength")
HARD_TYPES = ("tempo", "intervals", "hills", "race")
MAX_MUTATIONS = 6


def _as_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def _apply_mutations(
    db: Session,
    plan: TrainingPlan,
    sessions: list[TrainingSession],
    mutations: list[dict[str, Any]],
    today: date,
    *,
    allowed_ids: set[int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply proposed changes after checking each one. Returns (applied diff, rejected with reason).

    Rules the code enforces, whoever proposed the change: only open sessions in the next 14 days;
    race sessions are never touched; key sessions are never skipped; known session types only;
    no two hard days back to back; load changes stay within 50–125 %."""
    by_id = {s.id: s for s in sessions}
    event_d = _parse_date(plan.event_date, today + timedelta(days=90))
    horizon = min(event_d, today + timedelta(days=14))
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    def reject(m: dict[str, Any], why: str) -> None:
        rejected.append({"session_id": m.get("session_id"), "action": m.get("action"), "reason": why})

    def hard_neighbour(s: TrainingSession, on: date) -> TrainingSession | None:
        for o in sessions:
            if o.id == s.id or o.status in ("skipped", "missed") or o.session_type not in HARD_TYPES:
                continue
            if abs((_parse_date(o.scheduled_date, today) - on).days) == 1:
                return o
        return None

    for m in mutations:
        if len(applied) >= MAX_MUTATIONS:
            reject(m, f"more than {MAX_MUTATIONS} changes at once")
            continue
        sid = _as_int(m.get("session_id"))
        s = by_id.get(sid) if sid is not None else None
        action = str(m.get("action") or "")
        if s is None or (allowed_ids is not None and s.id not in allowed_ids):
            reject(m, "not an open session in the next 14 days")
            continue
        if s.status in ("completed", "partial", "skipped") or s.matched_activity_id:
            reject(m, "session already done or skipped")
            continue
        if s.session_type == "race":
            reject(m, "race sessions are never changed")
            continue
        if action not in ("skip", "reschedule", "adjust_load", "swap_type"):
            reject(m, f"unknown action {action!r}")
            continue
        note = str(m.get("note") or "")[:300]
        before = {
            "scheduled_date": s.scheduled_date,
            "title": s.title,
            "duration_min": round(s.target_duration_s / 60),
            "tss": s.target_tss,
            "status": s.status,
        }

        if action == "skip":
            if s.priority == "key":
                reject(m, "key sessions are moved or shortened, not skipped")
                continue
            s.status = "skipped"
            s.adaptation_note = note or "Skipped by the coach"
        else:
            new_date = _parse_date(s.scheduled_date, today)
            if isinstance(m.get("new_date"), str):
                nd = _parse_date(m["new_date"], new_date)
                if not today <= nd <= horizon:
                    reject(m, "new date outside the next 14 days")
                    continue
                new_date = nd
            new_type = s.session_type
            if isinstance(m.get("new_session_type"), str) and m["new_session_type"].strip():
                t = m["new_session_type"].strip().lower()
                if t not in SESSION_TYPES:
                    reject(m, f"unknown session type {t!r}")
                    continue
                new_type = t
            creates_hard_day = new_type in HARD_TYPES and (
                new_type != s.session_type or _iso(new_date) != s.scheduled_date
            )
            if creates_hard_day:
                clash = hard_neighbour(s, new_date)
                if clash is not None:
                    reject(m, f"would put two hard days back to back (next to “{clash.title}”)")
                    continue
            scale = m.get("duration_scale")
            if isinstance(scale, bool) or (scale is not None and not isinstance(scale, (int, float))):
                scale = None

            if s.original_target is None:
                from routepass.analysis.training_extras import _snapshot

                s.original_target = _snapshot(s)
            if _iso(new_date) != s.scheduled_date:
                s.scheduled_date = _iso(new_date)
                week = db.scalar(
                    select(TrainingWeek).where(
                        TrainingWeek.plan_id == plan.id, TrainingWeek.start_date == _iso(_monday_of(new_date))
                    )
                )
                if week is not None:
                    s.week_id = week.id
            s.session_type = new_type
            if scale is not None:
                k = max(0.5, min(1.25, float(scale)))
                s.target_duration_s = round(s.target_duration_s * k)
                s.target_distance_km = round(s.target_distance_km * k, 1)
                s.target_elev_m = round(s.target_elev_m * k, 0)
                s.target_tss = round(s.target_tss * k, 0)
            if isinstance(m.get("new_title"), str) and m["new_title"].strip():
                s.title = m["new_title"].strip()[:180]
            if isinstance(m.get("new_description"), str) and m["new_description"].strip():
                s.description = m["new_description"].strip()[:800]
            s.status = "moved"
            s.adaptation_note = note or f"Adapted ({action.replace('_', ' ')})"

        after = {
            "scheduled_date": s.scheduled_date,
            "title": s.title,
            "duration_min": round(s.target_duration_s / 60),
            "tss": s.target_tss,
            "status": s.status,
        }
        if after != before:
            applied.append(
                {"session_id": s.id, "action": action, "before": before, "after": after, "note": note}
            )

    db.flush()
    return applied, rejected


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
            .where(PlanAdaptation.plan_id == plan.id, PlanAdaptation.trigger != "weekly_review")
            .order_by(PlanAdaptation.created_at.desc())
            .limit(12)
        )
    )

    matched_ids = [s.matched_activity_id for s in sessions if s.matched_activity_id]
    matched = (
        {a.id: a for a in db.scalars(select(Activity).where(Activity.id.in_(matched_ids)))}
        if matched_ids
        else {}
    )

    def _matched(aid: int | None) -> dict[str, Any] | None:
        a = matched.get(aid) if aid else None
        if a is None:
            return None
        return {
            "id": a.id,
            "name": a.name,
            "sport": a.sport,
            "family": a.family,
            "distance_m": a.distance_m,
            "moving_time_s": a.moving_time_s,
            "elevation_gain_m": a.elevation_gain_m,
            "load": a.load,
        }

    from routepass.analysis import training_extras as tx

    week_by_id = {w.id: w for w in weeks}
    week_by_index = {w.week_index: w for w in weeks}
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
                "matched_activity": _matched(s.matched_activity_id),
                "compliance_level": tx.compliance_level(s, today),
                "why": tx.session_why(
                    s,
                    week_by_id.get(s.week_id),
                    week_by_index.get(week_by_id[s.week_id].week_index - 1)
                    if s.week_id in week_by_id
                    else None,
                ),
                "zone": tx.SESSION_ZONE.get(s.session_type),
                "rpe": s.rpe,
                "feel": s.feel,
                "feedback_note": s.feedback_note,
                "changed": s.original_target is not None,
                "compliance_score": s.compliance_score,
                "gcal_event_id": s.gcal_event_id,
                "adaptation_note": s.adaptation_note,
                "coach_feedback": s.coach_feedback,
            }
        )

    out = serialize_plan_summary(plan)
    out["analytics"] = analytics
    out["zones"] = tx.personal_zones(prefs.get("profile") or {}, analytics.get("baseline") or {})
    out["ai"] = ai_info(db)
    out["ai_coach"] = bool((plan.schedule_prefs or {}).get("ai_coach", True))
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
            "ai_written": w.ai_written_at is not None,
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
            "details": a.details,
            "ai_error": a.ai_error,
        }
        for a in adaptations
    ]
    review = db.scalar(
        select(PlanAdaptation)
        .where(PlanAdaptation.plan_id == plan.id, PlanAdaptation.trigger == "weekly_review")
        .order_by(PlanAdaptation.created_at.desc())
        .limit(1)
    )
    out["weekly_review"] = (
        {
            **(review.details or {}),
            "id": review.id,
            "created_at": review.created_at.isoformat() + "Z" if review.created_at else None,
            "model_used": review.model_used,
            "ai_error": review.ai_error,
        }
        if review is not None
        else None
    )
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
    ai_plans: list[int] = []
    gcal_cfg = gcal.get_config(db)
    push_prefs = push.get_prefs(db)

    for plan in plans:
        res = match_activities_to_plan(db, plan)
        total_matched += res["matched"]
        total_missed += res["missed"]
        # with the AI coach on, its note on the workout is the notification (routepass.ai.coach.feedback)
        if res["matched"] > 0 and push_prefs.get("notify_completed", True) and not ai_enabled(db, plan):
            push.send_notification(
                db,
                title=f"{plan.name}: Workout synced",
                body=f"Matched {res['matched']} activity to your training plan.",
                url="/insights/training",
                kind="completed",
            )
        if (res["missed"] > 0 or res["matched"] > 0) and ai_enabled(db, plan):
            ai_plans.append(plan.id)  # the AI coach adapts it in the background after this sync
        elif res["missed"] > 0 or res["matched"] > 0:
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

        if (
            gcal_cfg.get("connected")
            and gcal_cfg.get("target_calendar_id")
            and gcal_cfg.get("auto_sync", True)
        ):
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
        "ai_adapt": ai_plans,
    }

"""50k / ultra trail-running training readiness, durability, and GPX race pacing."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from routepass import store
from routepass.analysis import insights
from routepass.analysis import track as trk
from routepass.models import Activity, Track


def _pace_str(speed_ms: float | None) -> str | None:
    if not speed_ms or speed_ms <= 0.2:
        return None
    sec_per_km = 1000.0 / speed_ms
    mins = int(sec_per_km // 60)
    secs = int(round(sec_per_km % 60))
    if secs == 60:
        mins += 1
        secs = 0
    return f"{mins}:{secs:02d}/km"


def _phase_for_days(days_to_race: int | None) -> str:
    if days_to_race is None:
        return "unscheduled"
    if days_to_race < 0:
        return "completed"
    if days_to_race <= 7:
        return "race_week"
    if days_to_race <= 21:
        return "taper"
    if days_to_race <= 49:
        return "peak"
    if days_to_race <= 91:
        return "build"
    return "base"


def _acwr_status(acwr: float | None) -> str:
    if acwr is None:
        return "unknown"
    if acwr < 0.8:
        return "low"
    if acwr <= 1.3:
        return "optimal"
    if acwr <= 1.5:
        return "caution"
    return "high_risk"


def _athlete_trail_baseline(db: Session, lookback_days: int = 180) -> dict[str, Any]:
    """Derive median GAP speed (m/s) and climbing VAM (m/h) from recent foot tracks."""
    cutoff = date.today() - timedelta(days=lookback_days)
    rows = db.execute(
        select(Activity, Track)
        .join(Track, Track.activity_id == Activity.id)
        .where(Activity.family.in_(("run", "walk")), Activity.start_time >= cutoff)
        .order_by(Activity.start_time.desc())
        .limit(60)
    ).all()

    gap_speeds: list[float] = []
    vams: list[float] = []
    for act, tr in rows:
        detail = tr.detail or {}
        summary = detail.get("summary") or {}
        g = summary.get("gap_speed_ms") or act.avg_speed_ms
        if g and 1.2 <= float(g) <= 6.5 and (act.distance_m or 0) >= 3000:
            gap_speeds.append(float(g))
        for c in detail.get("climbs") or []:
            v = c.get("vam")
            if v and 150 <= float(v) <= 1800 and (c.get("gain_m") or 0) >= 50:
                vams.append(float(v))

    med_gap = round(float(median(gap_speeds)), 3) if gap_speeds else None
    med_vam = round(float(median(vams)), 0) if vams else None
    return {
        "sample_runs": len(gap_speeds),
        "median_gap_speed_ms": med_gap,
        "median_gap_pace": _pace_str(med_gap),
        "median_climb_vam_mh": med_vam,
    }


def trail_readiness(db: Session, prefs: dict[str, Any], *, weeks: int = 8) -> dict[str, Any]:
    """Build a complete 50k trail-running readiness dossier for UI and AI Coach MCP."""
    race = dict(store.DEFAULT_PREFERENCES["trail_race"])
    race.update(prefs.get("trail_race") or {})

    today = date.today()
    race_date: date | None = None
    if race.get("date"):
        try:
            race_date = date.fromisoformat(str(race["date"])[:10])
        except ValueError:
            race_date = None
    days_to_race = (race_date - today).days if race_date else None
    weeks_to_race = round(days_to_race / 7.0, 1) if days_to_race is not None else None
    phase = _phase_for_days(days_to_race)

    race_dist_km = float(race.get("distance_km") or 50.0)
    race_vert_m = float(race.get("elevation_gain_m") or 2000.0)
    race_effort_km = round(race_dist_km + race_vert_m / 100.0, 1)
    race_vert_ratio = round(race_vert_m / race_dist_km, 1) if race_dist_km > 0 else 0.0

    # Anchor Monday of current week, look back `weeks` ISO weeks
    cur_monday = today - timedelta(days=today.weekday())
    start_monday = cur_monday - timedelta(days=7 * (weeks - 1))

    acts = db.scalars(
        select(Activity)
        .where(Activity.family.in_(("run", "walk")), Activity.start_time >= start_monday)
        .order_by(Activity.start_time.asc())
    ).all()

    by_week: dict[date, list[Activity]] = defaultdict(list)
    by_day: dict[date, dict[str, float]] = defaultdict(lambda: {"km": 0.0, "vert": 0.0})
    for a in acts:
        d = (a.start_local or a.start_time).date()
        wk = d - timedelta(days=d.weekday())
        by_week[wk].append(a)
        by_day[d]["km"] += (a.distance_m or 0.0) / 1000.0
        by_day[d]["vert"] += a.elevation_gain_m or 0.0

    weekly_rows: list[dict[str, Any]] = []
    for i in range(weeks):
        wk = start_monday + timedelta(days=7 * i)
        w_acts = by_week.get(wk, [])
        dist_km = sum((a.distance_m or 0.0) / 1000.0 for a in w_acts)
        vert_m = sum(a.elevation_gain_m or 0.0 for a in w_acts)
        hours = sum((a.moving_time_s or 0.0) / 3600.0 for a in w_acts)
        longest = max(((a.distance_m or 0.0) / 1000.0 for a in w_acts), default=0.0)
        longest_vert = max((a.elevation_gain_m or 0.0 for a in w_acts), default=0.0)

        # Biggest consecutive 2-day pair inside this week (captures Sat+Sun back-to-back long runs)
        b2b_km = 0.0
        b2b_vert = 0.0
        for offset in range(6):
            d1 = wk + timedelta(days=offset)
            d2 = d1 + timedelta(days=1)
            if by_day[d1]["km"] > 0 and by_day[d2]["km"] > 0:
                pair_km = by_day[d1]["km"] + by_day[d2]["km"]
                if pair_km > b2b_km:
                    b2b_km = pair_km
                    b2b_vert = by_day[d1]["vert"] + by_day[d2]["vert"]

        weekly_rows.append(
            {
                "week_start": wk.isoformat(),
                "runs": len(w_acts),
                "distance_km": round(dist_km, 1),
                "elevation_m": round(vert_m, 0),
                "effort_km": round(dist_km + vert_m / 100.0, 1),
                "moving_hours": round(hours, 1),
                "longest_km": round(longest, 1),
                "longest_elevation_m": round(longest_vert, 0),
                "back_to_back_km": round(b2b_km, 1),
                "back_to_back_elevation_m": round(b2b_vert, 0),
                "vert_per_km": round(vert_m / dist_km, 1) if dist_km > 0.5 else 0.0,
            }
        )

    # Fitness / fatigue / ACWR across all sports (systemic load matters for injury risk)
    load = insights.training_load(db, today)
    cur_load = load.get("current") or {}
    ctl = float(cur_load.get("fitness") or 0.0)
    atl = float(cur_load.get("fatigue") or 0.0)
    tsb = float(cur_load.get("form") or 0.0)
    acwr = round(atl / ctl, 2) if ctl >= 5.0 else None

    # Long-run aerobic durability (foot runs >= 75 min with stored Track)
    long_rows = db.execute(
        select(Activity, Track)
        .join(Track, Track.activity_id == Activity.id)
        .where(Activity.family.in_(("run", "walk")), Activity.moving_time_s >= 4500)
        .order_by(Activity.start_time.desc())
        .limit(10)
    ).all()
    long_runs: list[dict[str, Any]] = []
    for act, tr in long_rows:
        detail = tr.detail or {}
        summary = detail.get("summary") or {}
        dec = detail.get("decoupling") or {}
        gap = summary.get("gap_speed_ms")
        dist_km = round((act.distance_m or 0.0) / 1000.0, 1)
        vert = round(act.elevation_gain_m or 0.0, 0)
        long_runs.append(
            {
                "id": act.id,
                "date": (act.start_local or act.start_time).date().isoformat(),
                "name": act.name,
                "distance_km": dist_km,
                "elevation_m": vert,
                "effort_km": round(dist_km + vert / 100.0, 1),
                "moving_time_s": round(act.moving_time_s or 0.0, 0),
                "avg_hr": act.avg_hr,
                "gap_pace": _pace_str(gap),
                "decoupling_pct": dec.get("pct"),
            }
        )

    baseline = _athlete_trail_baseline(db)

    # Recent 4 completed/active weeks summary
    recent4 = weekly_rows[-4:]
    avg_wk_km = round(sum(w["distance_km"] for w in recent4) / max(len(recent4), 1), 1)
    avg_wk_vert = round(sum(w["elevation_m"] for w in recent4) / max(len(recent4), 1), 0)
    avg_wk_effort = round(sum(w["effort_km"] for w in recent4) / max(len(recent4), 1), 1)
    max_long_km = max((w["longest_km"] for w in weekly_rows), default=0.0)
    max_b2b_km = max((w["back_to_back_km"] for w in weekly_rows), default=0.0)
    recent_vert_ratio = round(avg_wk_vert / avg_wk_km, 1) if avg_wk_km > 1.0 else 0.0

    # Gear / shoe status
    gear = insights.gear_stats(db, insights.Filters(families=["run", "walk"]), prefs).get("gear") or []
    shoes_summary = [
        {
            "label": g["label"],
            "distance_km": round(g["distance_m"] / 1000.0, 1),
            "runs": g["count"],
            "service_km": g.get("service_km"),
            "service_due": g.get("service_due", False),
        }
        for g in gear[:6]
    ]

    # Actionable coaching flags
    flags: list[dict[str, str]] = []
    if acwr is not None:
        if acwr > 1.5:
            flags.append(
                {
                    "severity": "bad",
                    "code": "acwr_high",
                    "message": f"Acute:Chronic load ratio is {acwr} (>1.5) — high overuse/injury risk; schedule a recovery week.",
                }
            )
        elif acwr > 1.3:
            flags.append(
                {
                    "severity": "warn",
                    "code": "acwr_caution",
                    "message": f"Acute:Chronic load ratio is {acwr} (1.3–1.5) — aggressive ramp; avoid adding extra intensity this week.",
                }
            )
        elif acwr >= 0.8:
            flags.append(
                {
                    "severity": "good",
                    "code": "acwr_optimal",
                    "message": f"Load ramp is in the sweet spot (ACWR {acwr}, CTL {round(ctl, 1)}).",
                }
            )

    if race_vert_ratio >= 20 and avg_wk_km >= 10 and recent_vert_ratio < race_vert_ratio * 0.6:
        flags.append(
            {
                "severity": "warn",
                "code": "low_vertical_specificity",
                "message": (
                    f"Recent vertical specificity is {recent_vert_ratio} m/km vs {race_vert_ratio} m/km for your race "
                    "— add hill repeats or hilly trail long runs."
                ),
            }
        )

    if phase in ("build", "peak") and max_b2b_km < race_dist_km * 0.6:
        flags.append(
            {
                "severity": "info",
                "code": "back_to_back_needed",
                "message": (
                    f"Biggest 8-week back-to-back weekend is {max_b2b_km} km. "
                    f"For a {round(race_dist_km)} km trail race, build toward {round(race_dist_km * 0.7)}–{round(race_dist_km * 0.85)} km over Sat+Sun."
                ),
            }
        )

    if phase in ("taper", "race_week"):
        flags.append(
            {
                "severity": "info",
                "code": "taper_phase",
                "message": f"{days_to_race} days to race ({phase.replace('_', ' ')}) — cut volume 30–50% while keeping short strides and sleep high.",
            }
        )

    high_drift = [lr for lr in long_runs[:5] if lr.get("decoupling_pct") is not None and lr["decoupling_pct"] > 7.0]
    if high_drift:
        flags.append(
            {
                "severity": "warn",
                "code": "aerobic_drift",
                "message": (
                    f"{len(high_drift)} of your last {min(5, len(long_runs))} long runs showed >7% aerobic decoupling "
                    "— practice slower starts, steady fueling, and Zone 2 volume."
                ),
            }
        )

    for sh in shoes_summary:
        if sh["service_due"] or (sh["service_km"] is None and sh["distance_km"] >= 650):
            flags.append(
                {
                    "severity": "warn",
                    "code": "shoe_mileage",
                    "message": f"{sh['label']} has {sh['distance_km']} km — check outsole lugs and midsole cushioning before race day.",
                }
            )

    return {
        "race": {
            **race,
            "days_to_race": days_to_race,
            "weeks_to_race": weeks_to_race,
            "phase": phase,
            "effort_km": race_effort_km,
            "vert_per_km": race_vert_ratio,
        },
        "fitness": {
            "ctl": round(ctl, 1),
            "atl": round(atl, 1),
            "tsb": round(tsb, 1),
            "acwr": acwr,
            "acwr_status": _acwr_status(acwr),
            "state": cur_load.get("state"),
        },
        "recent_4w": {
            "avg_weekly_km": avg_wk_km,
            "avg_weekly_elevation_m": avg_wk_vert,
            "avg_weekly_effort_km": avg_wk_effort,
            "vert_per_km": recent_vert_ratio,
            "max_long_run_km": round(max_long_km, 1),
            "max_back_to_back_km": round(max_b2b_km, 1),
        },
        "baseline": baseline,
        "weeks": weekly_rows,
        "long_runs": long_runs,
        "shoes": shoes_summary,
        "coaching_flags": flags,
    }


def analyze_trail_activity(db: Session, activity_id: int, prefs: dict[str, Any]) -> dict[str, Any]:
    """Trail-focused deep dive for a single activity (for AI Coach MCP & UI)."""
    act = db.get(Activity, activity_id)
    if act is None:
        raise ValueError(f"Activity {activity_id} not found")
    tr = db.get(Track, activity_id)
    detail = (tr.detail if tr else None) or {}
    summary = detail.get("summary") or {}

    dist_km = round((act.distance_m or 0.0) / 1000.0, 2)
    vert_m = round(act.elevation_gain_m or 0.0, 0)
    effort_km = round(dist_km + vert_m / 100.0, 2)
    vert_per_km = round(vert_m / dist_km, 1) if dist_km > 0.1 else 0.0

    race = {**store.DEFAULT_PREFERENCES["trail_race"], **(prefs.get("trail_race") or {})}
    race_km = float(race.get("distance_km") or 50.0)
    race_vert = float(race.get("elevation_gain_m") or 2000.0)
    race_vert_ratio = round(race_vert / race_km, 1) if race_km > 0 else 0.0

    gap_ms = summary.get("gap_speed_ms")
    splits = detail.get("splits") or []
    compact_splits = [
        {
            "km": s["index"],
            "pace": _pace_str(s.get("speed_ms")),
            "gap": _pace_str(s.get("gap_speed_ms")),
            "gain_m": s.get("gain_m"),
            "loss_m": s.get("loss_m"),
            "hr": s.get("hr"),
        }
        for s in splits
    ]
    return {
        "id": act.id,
        "name": act.name,
        "date": (act.start_local or act.start_time).isoformat(),
        "sport": act.sport,
        "gear": act.gear,
        "distance_km": dist_km,
        "elevation_gain_m": vert_m,
        "elevation_loss_m": round(act.elevation_loss_m or 0.0, 0),
        "effort_km": effort_km,
        "vert_per_km": vert_per_km,
        "race_vert_ratio_pct": round(vert_per_km / race_vert_ratio * 100, 0) if race_vert_ratio else None,
        "moving_time_s": round(act.moving_time_s or 0.0, 0),
        "avg_pace": _pace_str(act.avg_speed_ms),
        "gap_pace": _pace_str(gap_ms),
        "avg_hr": act.avg_hr,
        "max_hr": act.max_hr,
        "load_tss": act.load,
        "decoupling": detail.get("decoupling"),
        "hr_zones": detail.get("hr_zones"),
        "climbs": detail.get("climbs") or [],
        "splits": compact_splits,
    }


def plan_gpx_race(
    db: Session,
    gpx_bytes: bytes,
    *,
    aid_stations_km: list[float] | None = None,
    fade_pct: float = 8.0,
    carbs_g_per_h: float = 70.0,
    fluid_ml_per_h: float = 600.0,
    base_gap_speed_ms: float | None = None,
) -> dict[str, Any]:
    """Estimate split times, climbs, and nutrition for a target GPX trail race."""
    track = trk.from_gpx(gpx_bytes)
    if track is None or track.distance_m is None or track.n < 2:
        raise ValueError("Could not parse a valid GPS route from GPX")

    d = np.maximum.accumulate(np.nan_to_num(track.distance_m, nan=0.0))
    total_m = float(d[-1] - d[0])
    if total_m < 500:
        raise ValueError("GPX route is too short (< 0.5 km)")
    total_km = total_m / 1000.0

    ele = trk.despike(track.elevation_m) if track.elevation_m is not None else np.zeros_like(d)
    ele_s = trk._smooth_by_distance(ele, d, 60.0)
    total_gain, total_loss = trk.elevation_gain_loss(ele, d)

    baseline = _athlete_trail_baseline(db)
    # Default ultra-sustainable flat GAP: 88% of recent median training GAP (or 6:15/km fallback)
    ref_gap = float(base_gap_speed_ms) if base_gap_speed_ms else (
        float(baseline["median_gap_speed_ms"]) * 0.88 if baseline["median_gap_speed_ms"] else 2.65
    )
    ref_gap = max(1.2, min(ref_gap, 5.5))

    # Build monotonic segment boundaries (in km)
    stations = sorted({round(float(x), 2) for x in (aid_stations_km or []) if 0.5 < float(x) < total_km - 0.5})
    if not stations:
        # Default to ~10 km aid station splits
        step = 10.0 if total_km >= 25 else 5.0
        cur = step
        while cur < total_km - 1.0:
            stations.append(round(cur, 1))
            cur += step
    boundaries_km = [0.0, *stations, round(total_km, 2)]

    # Compute incremental point-by-point estimated time using Minetti cost + linear fade
    dd = np.diff(d)
    de = np.diff(ele_s)
    mid_frac = ((d[:-1] + d[1:]) * 0.5 - d[0]) / max(total_m, 1.0)
    grade = np.where(dd > 0.5, de / np.maximum(dd, 0.5), 0.0)
    cost_factor = trk.minetti_gap_factor(grade)
    fade_factor = 1.0 + (max(0.0, min(fade_pct, 35.0)) / 100.0) * mid_frac
    seg_dt = np.where(dd > 0.1, (dd / ref_gap) * cost_factor * fade_factor, 0.0)
    cum_t = np.concatenate([[0.0], np.cumsum(seg_dt)])

    legs: list[dict[str, Any]] = []
    for idx in range(len(boundaries_km) - 1):
        k0, k1 = boundaries_km[idx], boundaries_km[idx + 1]
        i0 = int(np.searchsorted(d, d[0] + k0 * 1000.0))
        i1 = min(int(np.searchsorted(d, d[0] + k1 * 1000.0)), track.n - 1)
        if i1 <= i0:
            continue
        leg_km = max((d[i1] - d[i0]) / 1000.0, 0.01)
        leg_gain, leg_loss = trk.elevation_gain_loss(ele[i0 : i1 + 1], d[i0 : i1 + 1])
        leg_s = float(cum_t[i1] - cum_t[i0])
        cum_s = float(cum_t[i1])
        leg_hours = leg_s / 3600.0
        legs.append(
            {
                "leg": idx + 1,
                "from_km": round(k0, 1),
                "to_km": round(k1, 1),
                "distance_km": round(leg_km, 1),
                "gain_m": round(leg_gain, 0),
                "loss_m": round(leg_loss, 0),
                "est_duration_s": round(leg_s, 0),
                "est_cumulative_s": round(cum_s, 0),
                "est_pace": _pace_str((leg_km * 1000.0) / leg_s) if leg_s > 0 else None,
                "carbs_g": round(leg_hours * carbs_g_per_h, 0),
                "fluid_ml": round(leg_hours * fluid_ml_per_h, 0),
            }
        )

    # Detect major climbs using synthetic time_s from predicted pacing
    synth_track = trk.NormalizedTrack(time_s=cum_t, lat=track.lat, lon=track.lon, elevation_m=ele, distance_m=d)
    climbs = trk.detect_climbs(synth_track)

    total_s = float(cum_t[-1])
    total_h = total_s / 3600.0
    return {
        "distance_km": round(total_km, 2),
        "elevation_gain_m": round(total_gain, 0),
        "elevation_loss_m": round(total_loss, 0),
        "effort_km": round(total_km + total_gain / 100.0, 1),
        "vert_per_km": round(total_gain / total_km, 1),
        "base_gap_pace": _pace_str(ref_gap),
        "fade_pct": fade_pct,
        "est_total_s": round(total_s, 0),
        "est_avg_pace": _pace_str(total_m / total_s) if total_s > 0 else None,
        "total_carbs_g": round(total_h * carbs_g_per_h, 0),
        "total_fluid_l": round((total_h * fluid_ml_per_h) / 1000.0, 1),
        "legs": legs,
        "climbs": climbs,
    }

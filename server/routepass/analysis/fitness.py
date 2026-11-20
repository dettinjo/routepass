"""How fit you are: estimates computed from recorded data, never guessed by a model.

- Cycling threshold and VO2max: from a power meter when there is one, otherwise from climbs — the
  power needed to lift rider and bike at the climb's rate plus rolling and air resistance. Steady
  climbs are the one place where speed tells power well; descents and flat speed do not.
- Running VO2max (Daniels' VDOT), threshold pace and race predictions: from best efforts.
- Heart-rate VO2max (Uth) when max and resting heart rate are in the profile.
- Durability: heart-rate drift over long sessions (needs heart rate).
- Load: fitness now, six weeks ago, a year ago, and six weeks ahead at the current load.

Every estimate says what it is based on and how sure it is; `needs` lists what would improve it.
The AI coach explains these numbers (routepass.ai.coach.fitness_report); it does not make them.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from routepass import store
from routepass.analysis import insights
from routepass.models import Activity, Effort, Track

G = 9.81
BIKE_KG = 9.0
CRR = 0.005  # road tyres on asphalt
CDA = 0.36  # m², riding the hoods
RHO = 1.2  # air density, kg/m³
DRIVETRAIN = 0.975
CLIMB_MIN_S = 240
CLIMB_MIN_GRADE = 4.0
POWER_DECAY = 0.05  # sustainable power ∝ duration^-0.05: 20 min → 95 % for an hour (the usual FTP rule)
RUN_DISTANCES = (1609, 5000, 10000, 21097, 42195)
PREDICT = (("5 km", 5000), ("10 km", 10000), ("Half marathon", 21097), ("Marathon", 42195))


# ── cycling ──────────────────────────────────────────────────────────────────


def climb_power(climb: dict[str, Any], rider_kg: float) -> float | None:
    """Watts needed for a recorded climb: gravity + rolling + air, through the drivetrain."""
    t, length, gain = climb.get("duration_s"), climb.get("length_m"), climb.get("gain_m")
    if not t or not length or not gain or t <= 0:
        return None
    m = rider_kg + BIKE_KG
    v = length / t
    grav = m * G * gain / t
    roll = CRR * m * G * v
    aero = 0.5 * RHO * CDA * v**3
    return (grav + roll + aero) / DRIVETRAIN


def _to_hour(power: float, seconds: float) -> float:
    """Power held for `seconds` → power for an hour (threshold)."""
    return power * (seconds / 3600) ** POWER_DECAY


def _climbs(db: Session, since: datetime, until: datetime) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            Activity.id,
            Activity.name,
            Activity.start_time,
            Activity.start_local,
            Activity.sport,
            Track.detail,
        )
        .join(Track, Track.activity_id == Activity.id)
        .where(
            Activity.family == "ride",
            Activity.start_time >= since,
            Activity.start_time < until,
            Activity.sport.not_in(("EBikeRide", "EMountainBikeRide")),
        )
    )
    out = []
    for r in rows:
        for c in (r.detail or {}).get("climbs") or []:
            if (c.get("duration_s") or 0) >= CLIMB_MIN_S and (c.get("grade_pct") or 0) >= CLIMB_MIN_GRADE:
                out.append(
                    {
                        **c,
                        "activity": {
                            "id": r.id,
                            "name": r.name,
                            "date": (r.start_local or r.start_time).date().isoformat(),
                        },
                    }
                )
    return out


def _cycling_from_climbs(climbs: list[dict[str, Any]], kg: float) -> dict[str, Any] | None:
    if not climbs:
        return None
    rated = []
    for c in climbs:
        p = climb_power(c, kg)
        if p and 80 < p < 700:
            rated.append({**c, "power_w": round(p), "threshold_w": round(_to_hour(p, c["duration_s"]))})
    if not rated:
        return None
    rated.sort(key=lambda c: -c["threshold_w"])
    # The best few, not the single best: one tailwind climb must not set the number.
    top = rated[:3]
    threshold = (
        sorted(c["threshold_w"] for c in top)[len(top) // 2] if len(top) >= 3 else top[0]["threshold_w"]
    )
    five = [c for c in rated if c["duration_s"] <= 480]
    p5 = max((c["power_w"] for c in five), default=None) or threshold / 0.82
    steep = sum(1 for c in rated if c["grade_pct"] >= 6)
    confidence = "medium" if len(rated) >= 8 and steep >= 2 else "low"
    return {
        "basis": "climbs",
        "threshold_w": round(threshold),
        "threshold_wkg": round(threshold / kg, 2),
        "p5_w": round(p5),
        "vo2max": round(10.8 * p5 / kg + 7, 1),
        "climbs_used": len(rated),
        "best_climbs": [
            {k: c[k] for k in ("activity", "gain_m", "length_m", "grade_pct", "duration_s", "vam", "power_w")}
            for c in top
        ],
        "confidence": confidence,
        "note": "Estimated from climbs: wind, drafting and road surface make this ±10 %.",
    }


def _critical_power(db: Session, since: datetime) -> dict[str, Any] | None:
    """CP and W′ from the measured power curve (work = CP·t + W′ over 3–20 min)."""
    best: dict[int, float] = {}
    for key, value in db.execute(
        select(Effort.key, Effort.value)
        .join(Activity, Activity.id == Effort.activity_id)
        .where(Effort.kind == "power", Effort.key.in_((180, 300, 600, 1200)), Activity.start_time >= since)
    ):
        best[key] = max(best.get(key, 0.0), float(value))
    pts = [(t, p) for t, p in best.items() if p > 0]
    if len(pts) < 3:
        return None
    ts = [t for t, _ in pts]
    ws = [t * p for t, p in pts]
    n = len(pts)
    mt, mw = sum(ts) / n, sum(ws) / n
    var = sum((t - mt) ** 2 for t in ts)
    if var == 0:
        return None
    cp = sum((t - mt) * (w - mw) for t, w in zip(ts, ws)) / var
    w_prime = mw - cp * mt
    if not (50 < cp < 600 and 3000 < w_prime < 40000):
        return None
    return {
        "cp_w": round(cp),
        "w_prime_kj": round(w_prime / 1000, 1),
        "p5_w": round(best.get(300, cp * 1.15)),
    }


def cycling(db: Session, profile: dict[str, Any], until: datetime, window_days: int = 120) -> dict[str, Any]:
    kg = profile.get("weight_kg")
    since = until - timedelta(days=window_days)
    out: dict[str, Any] = {"window_days": window_days}
    cp = _critical_power(db, since)
    ftp = profile.get("ftp")
    if cp and kg:
        out.update(
            basis="power",
            threshold_w=cp["cp_w"],
            threshold_wkg=round(cp["cp_w"] / kg, 2),
            cp_w=cp["cp_w"],
            w_prime_kj=cp["w_prime_kj"],
            vo2max=round(10.8 * cp["p5_w"] / kg + 7, 1),
            confidence="high",
            note="From your power meter.",
        )
        return out
    if not kg:
        out["missing"] = "Add your weight to estimate cycling power from climbs."
        return out
    est = _cycling_from_climbs(_climbs(db, since, until), kg)
    if est is None and window_days < 365:
        return {**cycling(db, profile, until, 365), "older": True}
    if est is None:
        out["missing"] = "No steady climbs of 4 % or more lasting 4 minutes in the last year."
        return out
    out.update(est)
    if ftp:
        out["profile_ftp"] = ftp
    return out


# ── running ──────────────────────────────────────────────────────────────────


def vdot(distance_m: float, seconds: float) -> float | None:
    """Daniels & Gilbert: VO2max implied by a race-pace effort."""
    if seconds <= 0 or distance_m <= 0:
        return None
    t = seconds / 60
    v = distance_m / t  # m/min
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v * v
    pct = 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)
    return vo2 / pct


def predict_time(v_dot: float, distance_m: float) -> float:
    lo, hi = 60.0, 60.0 * 60 * 24
    for _ in range(60):
        mid = (lo + hi) / 2
        if (vdot(distance_m, mid) or 0) > v_dot:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def threshold_pace(v_dot: float) -> float:
    """Seconds per km at ~88 % of VO2max (Daniels' T pace)."""
    target = 0.88 * v_dot
    a, b, c = 0.000104, 0.182258, -4.60 - target
    v = (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)  # m/min
    return 60000 / v


def running(db: Session, prefs: dict[str, Any], until: datetime, window_days: int = 365) -> dict[str, Any]:
    since = until - timedelta(days=window_days)
    best = None
    for key, value, act in db.execute(
        select(Effort.key, Effort.value, Activity)
        .join(Activity, Activity.id == Effort.activity_id)
        .where(
            Effort.kind == "time",
            Effort.key.in_(RUN_DISTANCES),
            Activity.family == "run",
            Activity.start_time >= since,
            Activity.start_time < until,
        )
    ):
        v = vdot(key, value)
        if not v or not 20 < v < 85:
            continue
        # Efforts of 5 km+ come first: a fast mile inside a game or intervals overstates VO2max.
        rank = (key >= 5000, v)
        if best is None or rank > (best[1] >= 5000, best[0]):
            best = (v, key, value, act)
    if best is None:
        return {"window_days": window_days, "missing": "No run of 1 mile or longer in the last year."}
    v, dist, secs, act = best
    out: dict[str, Any] = {
        "window_days": window_days,
        "basis": "best_effort",
        "vo2max": round(v, 1),
        "from_effort": {
            "distance_m": dist,
            "time_s": round(secs),
            "activity": {
                "id": act.id,
                "name": act.name,
                "date": (act.start_local or act.start_time).date().isoformat(),
            },
            "trail": act.sport == "TrailRun",
        },
        "threshold_pace_s_per_km": round(threshold_pace(v)),
        "predictions": [
            {"label": lbl, "distance_m": d, "time_s": round(predict_time(v, d))} for lbl, d in PREDICT
        ],
        "confidence": "medium" if dist >= 5000 else "low",
        "note": "From your best run effort; a hilly or easy effort gives a lower number than a race would.",
    }
    race = prefs.get("trail_race") or {}
    km, gain = race.get("distance_km"), race.get("elevation_gain_m")
    if km:
        # Effort-equivalent distance: 100 m of climbing ≈ 1 km on the flat (rough trail rule of thumb).
        flat_m = (float(km) + float(gain or 0) / 100) * 1000
        out["trail_prediction"] = {
            "label": race.get("name") or f"{km:g} km trail",
            "distance_km": km,
            "elevation_gain_m": gain,
            "time_s": round(predict_time(v, flat_m) * 1.08),  # terrain, fuelling, aid stations
        }
    return out


# ── heart rate, durability, load ─────────────────────────────────────────────


def heart_rate(profile: dict[str, Any]) -> dict[str, Any] | None:
    mx, rest = profile.get("hr_max"), profile.get("hr_rest")
    if not mx or not rest:
        return None
    return {"vo2max": round(15.3 * mx / rest, 1), "basis": "uth", "note": "From max and resting heart rate."}


def durability(db: Session, until: datetime, days: int = 180) -> dict[str, Any]:
    rows = db.execute(
        select(Activity.start_time, Activity.family, Activity.moving_time_s, Track.detail)
        .join(Track, Track.activity_id == Activity.id)
        .where(Activity.start_time >= until - timedelta(days=days), Activity.moving_time_s >= 5400)
    )
    vals = [
        ((r.detail or {}).get("decoupling") or {}).get("pct")
        for r in rows
        if ((r.detail or {}).get("decoupling") or {}).get("pct") is not None
    ]
    if len(vals) < 2:
        return {"missing": "Record long sessions (90 min+) with a heart-rate sensor to measure durability."}
    avg = sum(vals) / len(vals)
    return {
        "decoupling_pct": round(avg, 1),
        "sessions": len(vals),
        "verdict": "good" if avg < 5 else "fair" if avg < 10 else "low",
        "note": "Heart-rate drift in the second half of long sessions; under 5 % means good aerobic durability.",
    }


def load_outlook(db: Session, today: date) -> dict[str, Any]:
    tl = insights.training_load(db, today, days=400)
    s = tl["series"]
    if not s:
        return {}
    cur = s[-1]

    def at(days_ago: int) -> float | None:
        return s[-1 - days_ago]["ctl"] if len(s) > days_ago else None

    recent = [p["load"] for p in s[-28:]]
    daily = sum(recent) / len(recent) if recent else 0.0
    ctl, k = cur["ctl"], 1 - math.exp(-1 / 42)
    for _ in range(42):
        ctl += (daily - ctl) * k
    six = at(42)
    return {
        "ctl": cur["ctl"],
        "atl": cur["atl"],
        "tsb": cur["tsb"],
        "status": tl["status"],
        "ctl_6w_ago": six,
        "change_6w_pct": round((cur["ctl"] - six) / six * 100) if six else None,
        "ctl_1y_ago": at(365),
        "avg_daily_load_28d": round(daily, 1),
        "ctl_in_6w_at_this_load": round(ctl, 1),
        "ramp_7d": tl["ramp_7d"],
    }


def state_line(load: dict[str, Any]) -> str:
    """One sentence on where you stand, from the numbers."""
    if not load:
        return "Not enough recorded training yet to tell your fitness."
    ctl, tsb, ch = load["ctl"], load["tsb"], load.get("change_6w_pct")
    trend = (
        ""
        if ch is None
        else (
            f", up {ch} % in 6 weeks"
            if ch >= 3
            else f", down {-ch} % in 6 weeks"
            if ch <= -3
            else ", steady over 6 weeks"
        )
    )
    head = f"Fitness {ctl:.0f}{trend}; form {tsb:+.0f}"
    if tsb < -30:
        tail = "fatigue is high — an easy week would turn it into form."
    elif tsb < -10:
        tail = "productive training load — keep the easy days easy."
    elif tsb > 15 and (ch or 0) < 0:
        tail = "rested but losing fitness — time to build again."
    elif tsb > 5:
        tail = "fresh — a good moment for a hard session or a race."
    else:
        tail = "balanced."
    return f"{head}: {tail}"


# ── all together ─────────────────────────────────────────────────────────────


def estimates(db: Session, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    prefs = store.get_preferences(db)
    profile = prefs.get("profile") or {}
    until = datetime.combine(today + timedelta(days=1), datetime.min.time())
    load = load_outlook(db, today)
    out = {
        "date": today.isoformat(),
        "state": state_line(load),
        "load": load,
        "cycling": cycling(db, profile, until),
        "running": running(db, prefs, until),
        "heart_rate": heart_rate(profile),
        "durability": durability(db, until),
    }
    needs = []
    if not profile.get("weight_kg"):
        needs.append("Weight — needed for watts per kg and for estimating power from climbs.")
    if not profile.get("hr_max") or not profile.get("hr_rest"):
        needs.append("Max and resting heart rate — for a heart-rate VO2max and heart-rate zones.")
    if out["durability"].get("missing"):
        needs.append("A heart-rate sensor on long sessions — for durability and effort-based load.")
    if out["cycling"].get("basis") == "climbs":
        needs.append("A power meter — would replace the climb estimate with measured power.")
    out["needs"] = needs
    return out


def trend(db: Session, months: int = 24, today: date | None = None) -> list[dict[str, Any]]:
    """Month by month: cycling threshold W/kg (best of the previous 120 days) and running VO2max
    (best of the previous 365 days)."""
    today = today or date.today()
    prefs = store.get_preferences(db)
    profile = prefs.get("profile") or {}
    out = []
    first = today.replace(day=1)
    for i in range(months - 1, -1, -1):
        y, m = divmod(first.year * 12 + first.month - 1 - i, 12)
        month_end = date(y, m + 1, 1) + timedelta(days=32)
        month_end = month_end.replace(day=1)
        until = datetime.combine(min(month_end, today + timedelta(days=1)), datetime.min.time())
        c = cycling(db, profile, until, 120) if profile.get("weight_kg") else {}
        r = running(db, prefs, until, 365)
        out.append(
            {
                "month": f"{y}-{m + 1:02d}",
                "cycling_wkg": c.get("threshold_wkg") if not c.get("older") else None,
                "running_vo2max": r.get("vo2max"),
            }
        )
    return out

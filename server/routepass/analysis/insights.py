"""Aggregate analysis over the deduplicated activity table."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from routepass.analysis.track import BEST_DISTANCES_M, POWER_CURVE_S
from routepass.models import Activity, Effort, ProviderActivity
from routepass.providers import sports
from routepass.providers.gpx import decode_polyline

TOTAL_COLUMNS = (
    Activity.id,
    Activity.start_time,
    Activity.start_local,
    Activity.sport,
    Activity.family,
    Activity.distance_m,
    Activity.moving_time_s,
    Activity.elevation_gain_m,
    Activity.load,
    Activity.work_kj,
    Activity.calories,
)


@dataclass
class Filters:
    start: date | None = None
    end: date | None = None  # inclusive
    families: list[str] | None = None
    sports: list[str] | None = None

    def apply(self, q: Select) -> Select:
        if self.start:
            q = q.where(Activity.start_time >= datetime.combine(self.start, datetime.min.time()))
        if self.end:
            q = q.where(
                Activity.start_time < datetime.combine(self.end + timedelta(days=1), datetime.min.time())
            )
        if self.families:
            q = q.where(Activity.family.in_(self.families))
        if self.sports:
            q = q.where(Activity.sport.in_(self.sports))
        return q


def _local(row) -> datetime:
    return row.start_local or row.start_time


def _empty_totals() -> dict[str, float]:
    return {
        "count": 0,
        "distance_m": 0.0,
        "moving_time_s": 0.0,
        "elevation_m": 0.0,
        "load": 0.0,
        "work_kj": 0.0,
    }


def _add(t: dict[str, float], row) -> None:
    t["count"] += 1
    t["distance_m"] += row.distance_m or 0
    t["moving_time_s"] += row.moving_time_s or 0
    t["elevation_m"] += row.elevation_gain_m or 0
    t["load"] += row.load or 0
    t["work_kj"] += row.work_kj or 0


def _round(t: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 1) for k, v in t.items()}


def _rows(db: Session, f: Filters) -> list:
    return db.execute(f.apply(select(*TOTAL_COLUMNS))).all()


# ── totals & comparison ──────────────────────────────────────────────────────


def totals(db: Session, f: Filters) -> dict[str, Any]:
    rows = _rows(db, f)
    overall = _empty_totals()
    by_family: dict[str, dict] = defaultdict(_empty_totals)
    by_sport: dict[str, dict] = defaultdict(_empty_totals)
    days = set()
    for r in rows:
        _add(overall, r)
        _add(by_family[r.family], r)
        _add(by_sport[r.sport], r)
        days.add(_local(r).date())
    out = _round(overall)
    out["active_days"] = len(days)
    longest = max(rows, key=lambda r: r.distance_m or 0, default=None)
    out["longest_distance_m"] = longest.distance_m if longest else None
    return {
        "totals": out,
        "by_family": {
            k: _round(v) for k, v in sorted(by_family.items(), key=lambda x: -x[1]["moving_time_s"])
        },
        "by_sport": [
            {"sport": k, "label": sports.label(k), "family": sports.family(k), **_round(v)}
            for k, v in sorted(by_sport.items(), key=lambda x: -x[1]["moving_time_s"])
        ],
    }


def period_comparison(db: Session, today: date, families: list[str] | None = None) -> dict[str, Any]:
    """This week/month/year to date vs the same span of the previous period."""
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    prev_month_end = month_start - timedelta(days=1)
    spans = {
        "week": (week_start, today, week_start - timedelta(days=7), today - timedelta(days=7)),
        "month": (
            month_start,
            today,
            prev_month_end.replace(day=1),
            prev_month_end.replace(day=min(today.day, prev_month_end.day)),
        ),
        "year": (
            year_start,
            today,
            year_start.replace(year=year_start.year - 1),
            _safe_replace_year(today, today.year - 1),
        ),
    }
    out = {}
    for key, (s, e, ps, pe) in spans.items():
        cur = totals(db, Filters(start=s, end=e, families=families))["totals"]
        prev = totals(db, Filters(start=ps, end=pe, families=families))["totals"]
        out[key] = {"current": cur, "previous": prev, "range": [s.isoformat(), e.isoformat()]}
    return out


def _safe_replace_year(d: date, year: int) -> date:
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


# ── time series ──────────────────────────────────────────────────────────────


def _bucket(d: date, grain: str) -> date:
    if grain == "day":
        return d
    if grain == "week":
        return d - timedelta(days=d.weekday())
    if grain == "month":
        return d.replace(day=1)
    return d.replace(month=1, day=1)


def _next_bucket(d: date, grain: str) -> date:
    if grain == "day":
        return d + timedelta(days=1)
    if grain == "week":
        return d + timedelta(days=7)
    if grain == "month":
        return (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return d.replace(year=d.year + 1)


def timeseries(db: Session, f: Filters, grain: str = "week", group: str = "family") -> dict[str, Any]:
    rows = _rows(db, f)
    if not rows:
        return {"grain": grain, "buckets": [], "groups": []}
    data: dict[date, dict[str, dict]] = defaultdict(lambda: defaultdict(_empty_totals))
    groups: set[str] = set()
    first = last = None
    for r in rows:
        d = _local(r).date()
        b = _bucket(d, grain)
        key = r.family if group == "family" else r.sport if group == "sport" else "all"
        groups.add(key)
        _add(data[b][key], r)
        first = b if first is None or b < first else first
        last = b if last is None or b > last else last
    start = _bucket(f.start, grain) if f.start else first
    end = _bucket(f.end, grain) if f.end else last
    buckets = []
    cur = start
    while cur <= end:
        entry = {"start": cur.isoformat(), "groups": {}}
        total = _empty_totals()
        for key, t in data.get(cur, {}).items():
            entry["groups"][key] = _round(t)
            for k in total:
                total[k] += t[k]
        entry["total"] = _round(total)
        buckets.append(entry)
        cur = _next_bucket(cur, grain)
    return {"grain": grain, "group": group, "groups": sorted(groups), "buckets": buckets}


def calendar(db: Session, f: Filters) -> list[dict[str, Any]]:
    per_day: dict[date, dict] = defaultdict(_empty_totals)
    fams: dict[date, set] = defaultdict(set)
    for r in _rows(db, f):
        d = _local(r).date()
        _add(per_day[d], r)
        fams[d].add(r.family)
    return [
        {"date": d.isoformat(), **_round(t), "families": sorted(fams[d])} for d, t in sorted(per_day.items())
    ]


def cumulative_by_year(db: Session, f: Filters, metric: str = "distance_m") -> dict[str, list]:
    """Year-over-year: running total per day-of-year for each year."""
    per_year: dict[int, list[float]] = {}
    for r in sorted(_rows(db, f), key=_local):
        d = _local(r).date()
        series = per_year.setdefault(d.year, [0.0] * 367)
        doy = d.timetuple().tm_yday
        value = {
            "distance_m": r.distance_m,
            "moving_time_s": r.moving_time_s,
            "elevation_m": r.elevation_gain_m,
        }.get(metric) or (1 if metric == "count" else 0)
        series[doy] += value
    out = {}
    today = date.today()
    for year, series in sorted(per_year.items()):
        running, cum = 0.0, []
        limit = today.timetuple().tm_yday if year == today.year else (366 if _leap(year) else 365)
        for doy in range(1, limit + 1):
            running += series[doy]
            cum.append(round(running, 1))
        out[str(year)] = cum
    return out


def _leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


# ── training load ────────────────────────────────────────────────────────────


def training_load(
    db: Session, end: date, days: int = 365, families: list[str] | None = None
) -> dict[str, Any]:
    """Fitness (CTL, 42 d), fatigue (ATL, 7 d) and form (TSB) — exponentially weighted daily load."""
    warmup = 120
    start = end - timedelta(days=days + warmup)
    daily: dict[date, float] = defaultdict(float)
    methods: dict[str, int] = defaultdict(int)
    for r in db.execute(
        Filters(start=start, end=end, families=families).apply(
            select(Activity.start_time, Activity.start_local, Activity.load, Activity.load_method)
        )
    ):
        if r.load:
            daily[_local(r).date()] += r.load
            methods[r.load_method or "unknown"] += 1
    ctl = atl = 0.0
    k_ctl, k_atl = 1 - math.exp(-1 / 42), 1 - math.exp(-1 / 7)
    series = []
    d = start
    while d <= end:
        load = daily.get(d, 0.0)
        tsb = ctl - atl  # form = yesterday's fitness − fatigue
        ctl += (load - ctl) * k_ctl
        atl += (load - atl) * k_atl
        if d > end - timedelta(days=days):
            series.append(
                {
                    "date": d.isoformat(),
                    "load": round(load, 1),
                    "ctl": round(ctl, 1),
                    "atl": round(atl, 1),
                    "tsb": round(tsb, 1),
                }
            )
        d += timedelta(days=1)
    last = series[-1] if series else None
    ramp = None
    if len(series) > 7:
        ramp = round(series[-1]["ctl"] - series[-8]["ctl"], 1)
    return {
        "series": series,
        "current": last,
        "ramp_7d": ramp,
        "methods": dict(methods),
        "status": _form_status(last["tsb"]) if last else None,
    }


def _form_status(tsb: float) -> str:
    if tsb > 25:
        return "transition"
    if tsb > 5:
        return "fresh"
    if tsb > -10:
        return "neutral"
    if tsb > -30:
        return "productive"
    return "overreaching"


# ── records ──────────────────────────────────────────────────────────────────


def _activity_ref(a: Activity) -> dict[str, Any]:
    return {
        "id": a.id,
        "name": a.name,
        "date": (a.start_local or a.start_time).date().isoformat(),
        "sport": a.sport,
    }


def records(db: Session, f: Filters) -> dict[str, Any]:
    out: dict[str, Any] = {}
    fams = f.families or ["ride", "run", "walk", "winter", "water", "other"]
    for fam in fams:
        ff = Filters(f.start, f.end, [fam], f.sports)
        base = ff.apply(select(Activity))
        recs = {}
        for key, col, min_dist in (
            ("longest", Activity.distance_m, 0),
            ("most_elevation", Activity.elevation_gain_m, 0),
            ("longest_time", Activity.moving_time_s, 0),
            ("fastest_avg", Activity.avg_speed_ms, {"ride": 20000, "run": 5000}.get(fam, 3000)),
            ("highest_power", Activity.normalized_power, 0),
            ("biggest_load", Activity.load, 0),
        ):
            q = base.where(col.is_not(None))
            if min_dist:
                q = q.where(Activity.distance_m >= min_dist)
            a = db.scalar(q.order_by(col.desc()).limit(1))
            if a is not None and getattr(a, col.key):
                recs[key] = {"value": getattr(a, col.key), "activity": _activity_ref(a)}
        best = []
        for dist in BEST_DISTANCES_M.get(fam, ()):
            row = db.execute(
                ff.apply(
                    select(Effort.value, Activity)
                    .join(Activity, Activity.id == Effort.activity_id)
                    .where(Effort.kind == "time", Effort.key == dist)
                )
                .order_by(Effort.value)
                .limit(1)
            ).first()
            if row:
                best.append({"distance_m": dist, "time_s": row[0], "activity": _activity_ref(row[1])})
        if best:
            recs["best_times"] = best
        climb = db.execute(
            ff.apply(
                select(Effort.value, Activity)
                .join(Activity, Activity.id == Effort.activity_id)
                .where(Effort.kind == "climb")
            )
            .order_by(Effort.value.desc())
            .limit(1)
        ).first()
        if climb:
            recs["biggest_climb"] = {"value": climb[0], "activity": _activity_ref(climb[1])}
        if recs:
            out[fam] = recs
    return out


def power_curve(db: Session, f: Filters) -> list[dict[str, Any]]:
    out = []
    for secs in POWER_CURVE_S:
        row = db.execute(
            f.apply(
                select(Effort.value, Activity)
                .join(Activity, Activity.id == Effort.activity_id)
                .where(Effort.kind == "power", Effort.key == secs)
            )
            .order_by(Effort.value.desc())
            .limit(1)
        ).first()
        if row:
            out.append({"seconds": secs, "watts": row[0], "activity": _activity_ref(row[1])})
    return out


# ── habits ───────────────────────────────────────────────────────────────────


def habits(db: Session, f: Filters) -> dict[str, Any]:
    rows = _rows(db, f)
    grid = [[0] * 24 for _ in range(7)]
    by_weekday = [_empty_totals() for _ in range(7)]
    distance_hist: dict[str, int] = defaultdict(int)
    edges = [0, 5, 10, 20, 30, 50, 75, 100, 150, 200]
    for r in rows:
        local = _local(r)
        grid[local.weekday()][local.hour] += 1
        _add(by_weekday[local.weekday()], r)
        km = (r.distance_m or 0) / 1000
        label = next((f"{lo}–{hi}" for lo, hi in zip(edges, edges[1:]) if km < hi), f"{edges[-1]}+")
        distance_hist[label] += 1
    order = [f"{lo}–{hi}" for lo, hi in zip(edges, edges[1:])] + [f"{edges[-1]}+"]
    return {
        "weekday_hour": grid,
        "by_weekday": [_round(t) for t in by_weekday],
        "distance_histogram": [{"bucket": b, "count": distance_hist.get(b, 0)} for b in order],
        "streaks": streaks([_local(r).date() for r in rows]),
    }


def streaks(days: list[date], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    unique = sorted(set(days))
    if not unique:
        return {"current_days": 0, "longest_days": 0, "current_weeks": 0, "longest_weeks": 0}
    longest = cur = 1
    for a, b in zip(unique, unique[1:]):
        cur = cur + 1 if (b - a).days == 1 else 1
        longest = max(longest, cur)
    current = 0
    d = today if today in unique else today - timedelta(days=1)
    s = set(unique)
    while d in s:
        current += 1
        d -= timedelta(days=1)
    weeks = sorted({x - timedelta(days=x.weekday()) for x in unique})
    lw = cw = 1
    for a, b in zip(weeks, weeks[1:]):
        cw = cw + 1 if (b - a).days == 7 else 1
        lw = max(lw, cw)
    this_week = today - timedelta(days=today.weekday())
    wset = set(weeks)
    current_weeks = 0
    w = this_week if this_week in wset else this_week - timedelta(days=7)
    while w in wset:
        current_weeks += 1
        w -= timedelta(days=7)
    return {
        "current_days": current,
        "longest_days": longest,
        "current_weeks": current_weeks,
        "longest_weeks": lw,
    }


def eddington(db: Session, f: Filters, unit_km: float = 1.0) -> dict[str, Any]:
    """Largest E such that on E days you covered at least E km (or miles)."""
    per_day: dict[date, float] = defaultdict(float)
    for r in _rows(db, f):
        per_day[_local(r).date()] += (r.distance_m or 0) / 1000 / unit_km
    values = sorted(per_day.values(), reverse=True)
    e = 0
    for i, v in enumerate(values, start=1):
        if v >= i:
            e = i
        else:
            break
    return {"value": e, "next": e + 1, "days_needed": max(0, (e + 1) - sum(1 for v in values if v >= e + 1))}


# ── maps ─────────────────────────────────────────────────────────────────────


def heatmap(db: Session, f: Filters, max_points: int = 150) -> list[dict[str, Any]]:
    out = []
    for a in db.execute(
        f.apply(select(Activity.id, Activity.family, Activity.polyline).where(Activity.polyline.is_not(None)))
    ):
        pts = decode_polyline(a.polyline)
        if len(pts) > max_points:
            step = len(pts) / max_points
            pts = [pts[int(i * step)] for i in range(max_points)] + [pts[-1]]
        out.append(
            {"id": a.id, "family": a.family, "points": [[round(p[0], 5), round(p[1], 5)] for p in pts]}
        )
    return out


# ── coverage ─────────────────────────────────────────────────────────────────


def coverage(db: Session) -> dict[str, Any]:
    live = (
        select(ProviderActivity.activity_id, ProviderActivity.provider)
        .where(ProviderActivity.deleted.is_(False), ProviderActivity.activity_id.is_not(None))
        .subquery()
    )
    providers_per = db.execute(
        select(live.c.activity_id, func.group_concat(live.c.provider)).group_by(live.c.activity_id)
    ).all()
    counts = {"both": 0, "strava_only": 0, "komoot_only": 0}
    for _, provs in providers_per:
        p = set((provs or "").split(","))
        if {"strava", "komoot"} <= p:
            counts["both"] += 1
        elif "strava" in p:
            counts["strava_only"] += 1
        elif "komoot" in p:
            counts["komoot_only"] += 1
    raw = dict(
        db.execute(
            select(ProviderActivity.provider, func.count())
            .where(ProviderActivity.deleted.is_(False))
            .group_by(ProviderActivity.provider)
        ).all()
    )
    counts["activities"] = sum(counts[k] for k in ("both", "strava_only", "komoot_only"))
    counts["provider_records"] = raw
    counts["duplicates_hidden"] = sum(raw.values()) - counts["activities"]
    return counts

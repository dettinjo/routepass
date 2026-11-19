"""Aggregate analysis over the deduplicated activity table."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from routepass import store
from routepass.analysis.track import BEST_DISTANCES_M, POWER_CURVE_S
from routepass.models import Activity, Effort, ProviderActivity, Track
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


# ── explorer tiles ───────────────────────────────────────────────────────────


def _latlon_to_tile(lat: float, lon: float, zoom: int = 14) -> tuple[int, int]:
    lat_c = max(-85.0511, min(85.0511, lat))
    n = 1 << zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat_c)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _tile_nw_latlon(x: int, y: int, zoom: int = 14) -> tuple[float, float]:
    n = 1 << zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n)))
    return round(math.degrees(lat_rad), 5), round(lon, 5)


def _rect_bounds(x0: int, y0: int, w: int, h: int, zoom: int = 14) -> list[list[float]]:
    n_lat, w_lon = _tile_nw_latlon(x0, y0, zoom)
    s_lat, e_lon = _tile_nw_latlon(x0 + w, y0 + h, zoom)
    return [[s_lat, w_lon], [n_lat, e_lon]]


def _polyline_tiles(pts: list[tuple[float, float]], zoom: int = 14) -> set[tuple[int, int]]:
    tiles: set[tuple[int, int]] = set()
    prev: tuple[int, int] | None = None
    for lat, lon in pts:
        tx, ty = _latlon_to_tile(lat, lon, zoom)
        tiles.add((tx, ty))
        if prev is not None:
            dx, dy = tx - prev[0], ty - prev[1]
            steps = max(abs(dx), abs(dy))
            if 1 < steps <= 32:
                for s in range(1, steps):
                    tiles.add((round(prev[0] + dx * s / steps), round(prev[1] + dy * s / steps)))
        prev = (tx, ty)
    return tiles


_TILE_CACHE: dict[tuple, dict[str, Any]] = {}


def explorer_tiles(db: Session, f: Filters, zoom: int = 14, max_render: int = 2500) -> dict[str, Any]:
    """Cached wrapper: recomputed only when activities change."""
    stamp = db.execute(
        f.apply(select(func.count(), func.max(Activity.updated_at)).select_from(Activity))
    ).one()
    key = (
        f.start,
        f.end,
        tuple(f.families or ()),
        tuple(f.sports or ()),
        zoom,
        max_render,
        stamp[0],
        stamp[1],
    )
    if key not in _TILE_CACHE:
        if len(_TILE_CACHE) > 16:
            _TILE_CACHE.clear()
        _TILE_CACHE[key] = _explorer_tiles(db, f, zoom, max_render)
    return _TILE_CACHE[key]


def _explorer_tiles(db: Session, f: Filters, zoom: int = 14, max_render: int = 2500) -> dict[str, Any]:
    """Veloviewer / Statshunters style Explorer Tiles: total tiles, max square (N×N), max cluster, and yearly discovery."""
    rows = db.execute(
        f.apply(
            select(Activity.id, Activity.start_time, Activity.start_local, Activity.polyline).where(
                Activity.polyline.is_not(None)
            )
        ).order_by(Activity.start_time.asc())
    ).all()
    visited: set[tuple[int, int]] = set()
    by_year: dict[str, int] = defaultdict(int)
    for r in rows:
        pts = decode_polyline(r.polyline)
        if not pts:
            continue
        tset = _polyline_tiles(pts, zoom)
        new = tset - visited
        if new:
            yr = str(_local(r).year)
            by_year[yr] += len(new)
            visited |= new

    if not visited:
        return {
            "zoom": zoom,
            "total_tiles": 0,
            "cluster_tiles": 0,
            "max_cluster": 0,
            "max_square": 0,
            "square_bounds": None,
            "new_by_year": {},
            "tiles": [],
        }

    # Max square via dynamic programming on sorted (x, y)
    dp: dict[tuple[int, int], int] = {}
    best_size = 0
    best_br: tuple[int, int] = (0, 0)
    for x, y in sorted(visited):
        if (x - 1, y) in dp and (x, y - 1) in dp and (x - 1, y - 1) in dp:
            s = 1 + min(dp[(x - 1, y)], dp[(x, y - 1)], dp[(x - 1, y - 1)])
        else:
            s = 1
        dp[(x, y)] = s
        if s > best_size:
            best_size = s
            best_br = (x, y)

    sq_bounds = (
        _rect_bounds(best_br[0] - best_size + 1, best_br[1] - best_size + 1, best_size, best_size, zoom)
        if best_size > 0
        else None
    )

    # Cluster tiles: tiles whose 4 orthogonal neighbors are all visited
    cluster_set = {
        (x, y)
        for (x, y) in visited
        if (x + 1, y) in visited and (x - 1, y) in visited and (x, y + 1) in visited and (x, y - 1) in visited
    }
    largest_cluster: set[tuple[int, int]] = set()
    seen_cluster: set[tuple[int, int]] = set()
    for start_tile in cluster_set:
        if start_tile in seen_cluster:
            continue
        comp: set[tuple[int, int]] = set()
        stack = [start_tile]
        seen_cluster.add(start_tile)
        while stack:
            cx, cy = stack.pop()
            comp.add((cx, cy))
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if (nx, ny) in cluster_set and (nx, ny) not in seen_cluster:
                    seen_cluster.add((nx, ny))
                    stack.append((nx, ny))
        if len(comp) > len(largest_cluster):
            largest_cluster = comp

    ordered = sorted(visited, key=lambda t: (t not in largest_cluster, t not in cluster_set))[:max_render]
    tile_rects = [
        {
            "bounds": _rect_bounds(x, y, 1, 1, zoom),
            "cluster": (x, y) in largest_cluster or (x, y) in cluster_set,
        }
        for x, y in ordered
    ]

    return {
        "zoom": zoom,
        "total_tiles": len(visited),
        "cluster_tiles": len(cluster_set),
        "max_cluster": len(largest_cluster),
        "max_square": best_size,
        "square_bounds": sq_bounds,
        "new_by_year": dict(sorted(by_year.items())),
        "tiles": tile_rects,
    }


def activity_tile_stats(db: Session, act: Activity, zoom: int = 14) -> dict[str, int]:
    """Count zoom-14 explorer tiles touched by `act` and how many were visited for the first time."""
    if not act.polyline:
        return {"tiles_visited": 0, "new_tiles": 0}
    act_tiles = _polyline_tiles(decode_polyline(act.polyline), zoom)
    if not act_tiles:
        return {"tiles_visited": 0, "new_tiles": 0}
    prior: set[tuple[int, int]] = set()
    for (poly,) in db.execute(
        select(Activity.polyline).where(Activity.start_time < act.start_time, Activity.polyline.is_not(None))
    ):
        prior |= _polyline_tiles(decode_polyline(poly), zoom)
        if act_tiles <= prior:
            return {"tiles_visited": len(act_tiles), "new_tiles": 0}
    return {"tiles_visited": len(act_tiles), "new_tiles": len(act_tiles - prior)}


# ── zones, polarization & efficiency ─────────────────────────────────────────


def zone_distribution(db: Session, f: Filters, grain: str = "week") -> dict[str, Any]:
    """Aggregate HR and Power time-in-zones + Seiler 3-zone polarization across activities."""
    q = f.apply(
        select(Activity.start_time, Activity.start_local, Track.detail).join(
            Track, Track.activity_id == Activity.id
        )
    ).order_by(Activity.start_time.asc())
    hr_tot = [0.0] * 5
    pw_tot = [0.0] * 7
    hr_buckets: dict[date, list[float]] = defaultdict(lambda: [0.0] * 5)
    pw_buckets: dict[date, list[float]] = defaultdict(lambda: [0.0] * 7)
    for r in db.execute(q):
        b = _bucket(_local(r).date(), grain)
        detail = r.detail or {}
        if hz := (detail.get("hr_zones") or {}).get("seconds"):
            for i, s in enumerate(hz[:5]):
                hr_tot[i] += s
                hr_buckets[b][i] += s
        if pz := (detail.get("power_zones") or {}).get("seconds"):
            for i, s in enumerate(pz[:7]):
                pw_tot[i] += s
                pw_buckets[b][i] += s

    def _pol(low: float, mid: float, high: float) -> dict[str, float]:
        tot = low + mid + high
        if tot <= 0:
            return {"low_pct": 0.0, "threshold_pct": 0.0, "high_pct": 0.0}
        return {
            "low_pct": round(low / tot * 100, 1),
            "threshold_pct": round(mid / tot * 100, 1),
            "high_pct": round(high / tot * 100, 1),
        }

    return {
        "grain": grain,
        "hr": {
            "seconds": [round(x, 1) for x in hr_tot],
            "total_s": round(sum(hr_tot), 1),
            "polarization": _pol(hr_tot[0] + hr_tot[1], hr_tot[2], hr_tot[3] + hr_tot[4]),
            "buckets": [
                {"start": d.isoformat(), "values": {f"Z{i + 1}": round(v, 1) for i, v in enumerate(vals)}}
                for d, vals in sorted(hr_buckets.items())
            ],
        },
        "power": {
            "seconds": [round(x, 1) for x in pw_tot],
            "total_s": round(sum(pw_tot), 1),
            "polarization": _pol(
                pw_tot[0] + pw_tot[1], pw_tot[2] + pw_tot[3], pw_tot[4] + pw_tot[5] + pw_tot[6]
            ),
            "buckets": [
                {"start": d.isoformat(), "values": {f"Z{i + 1}": round(v, 1) for i, v in enumerate(vals)}}
                for d, vals in sorted(pw_buckets.items())
            ],
        },
    }


def efficiency_trend(db: Session, f: Filters) -> list[dict[str, Any]]:
    """Aerobic Efficiency Factor (NP/HR or speed/HR) and decoupling over time."""
    q = f.apply(
        select(
            Activity.id,
            Activity.name,
            Activity.family,
            Activity.start_time,
            Activity.start_local,
            Activity.moving_time_s,
            Activity.avg_speed_ms,
            Activity.avg_hr,
            Activity.avg_power,
            Activity.normalized_power,
            Track.detail,
        )
        .outerjoin(Track, Track.activity_id == Activity.id)
        .where(Activity.avg_hr.is_not(None), Activity.avg_hr > 60, Activity.moving_time_s >= 600)
    ).order_by(Activity.start_time.asc())
    out = []
    for r in db.execute(q):
        hr = float(r.avg_hr)
        pw = r.normalized_power or r.avg_power
        ef_power = round(float(pw) / hr, 2) if pw and pw > 30 else None
        ef_speed = (
            round(float(r.avg_speed_ms) * 60.0 / hr, 2) if r.avg_speed_ms and r.avg_speed_ms > 0.5 else None
        )
        dec = ((r.detail or {}).get("decoupling") or {}).get("pct") if r.detail else None
        if ef_power is None and ef_speed is None and dec is None:
            continue
        out.append(
            {
                "id": r.id,
                "name": r.name,
                "date": _local(r).date().isoformat(),
                "family": r.family,
                "avg_hr": round(hr, 1),
                "ef_power": ef_power,
                "ef_speed": ef_speed,
                "decoupling_pct": dec,
            }
        )
    return out


# ── goals & gear ─────────────────────────────────────────────────────────────


def goals_progress(
    db: Session, today: date, prefs: dict[str, Any], families: list[str] | None = None
) -> list[dict[str, Any]]:
    """Progress and pro-rata pace projection against configured weekly/monthly/yearly goals."""
    goals = prefs.get("goals") or {}
    periods = period_comparison(db, today, families)
    week_days = today.weekday() + 1
    month_end = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    year_days = 366 if _leap(today.year) else 365
    doy = today.timetuple().tm_yday

    specs = [
        (
            "weekly_distance_km",
            "Weekly distance",
            "km",
            periods["week"]["current"]["distance_m"] / 1000.0,
            week_days / 7.0,
        ),
        (
            "weekly_time_hours",
            "Weekly time",
            "h",
            periods["week"]["current"]["moving_time_s"] / 3600.0,
            week_days / 7.0,
        ),
        (
            "monthly_distance_km",
            "Monthly distance",
            "km",
            periods["month"]["current"]["distance_m"] / 1000.0,
            today.day / float(month_end.day),
        ),
        (
            "yearly_distance_km",
            "Yearly distance",
            "km",
            periods["year"]["current"]["distance_m"] / 1000.0,
            doy / float(year_days),
        ),
        (
            "yearly_elevation_m",
            "Yearly elevation",
            "m",
            periods["year"]["current"]["elevation_m"],
            doy / float(year_days),
        ),
    ]
    out = []
    for key, label, unit, cur, ratio in specs:
        target = goals.get(key)
        if not target or float(target) <= 0:
            continue
        tgt = float(target)
        expected = tgt * ratio
        projected = cur / max(ratio, 1 / 365.0)
        out.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "current": round(cur, 1),
                "target": round(tgt, 1),
                "pct": round(min(100.0, cur / tgt * 100.0), 1),
                "expected": round(expected, 1),
                "ahead_behind": round(cur - expected, 1),
                "projected": round(projected, 1),
                "on_track": cur >= expected * 0.95,
            }
        )
    return out


def gear_stats(db: Session, f: Filters, prefs: dict[str, Any]) -> dict[str, Any]:
    """Aggregate mileage, hours, elevation and service-interval status per gear and recording device."""
    targets = prefs.get("gear_targets") or {}
    gear_names = store.get_value(db, "strava.gear") or {}
    q = f.apply(
        select(
            Activity.gear,
            Activity.device,
            Activity.family,
            Activity.start_time,
            Activity.start_local,
            Activity.distance_m,
            Activity.moving_time_s,
            Activity.elevation_gain_m,
        )
    )
    gear_map: dict[str, dict[str, Any]] = {}
    dev_map: dict[str, dict[str, Any]] = {}

    def _accum(bucket: dict[str, dict[str, Any]], key: str, r) -> None:
        d = _local(r).date().isoformat()
        item = bucket.get(key)
        if item is None:
            tcfg = targets.get(key) or {}
            item = {
                "key": key,
                "label": tcfg.get("label") or gear_names.get(key) or key,
                "count": 0,
                "distance_m": 0.0,
                "moving_time_s": 0.0,
                "elevation_m": 0.0,
                "first_date": d,
                "last_date": d,
                "families": set(),
                "service_km": tcfg.get("service_km"),
            }
            bucket[key] = item
        item["count"] += 1
        item["distance_m"] += r.distance_m or 0.0
        item["moving_time_s"] += r.moving_time_s or 0.0
        item["elevation_m"] += r.elevation_gain_m or 0.0
        if d < item["first_date"]:
            item["first_date"] = d
        if d > item["last_date"]:
            item["last_date"] = d
        item["families"].add(r.family)

    for r in db.execute(q):
        if r.gear:
            _accum(gear_map, r.gear, r)
        if r.device:
            _accum(dev_map, r.device, r)

    def _finalize(bucket: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for item in sorted(bucket.values(), key=lambda x: -x["distance_m"]):
            km_val = item["distance_m"] / 1000.0
            svc = float(item["service_km"]) if item.get("service_km") else None
            rows.append(
                {
                    **item,
                    "distance_m": round(item["distance_m"], 1),
                    "moving_time_s": round(item["moving_time_s"], 1),
                    "elevation_m": round(item["elevation_m"], 1),
                    "families": sorted(item["families"]),
                    "service_km": svc,
                    "remaining_km": round(svc - km_val, 1) if svc else None,
                    "service_due": bool(svc and km_val >= svc),
                }
            )
        return rows

    return {"gear": _finalize(gear_map), "devices": _finalize(dev_map)}


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

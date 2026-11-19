"""Route suggestions for a training session.

Three sources, all read-only:
  • your own history — activities that start near the chosen point; a loop you did many times is one
    suggestion ("done 6×"), and point-to-point trips are marked and ranked lower;
  • your saved (planned) Komoot tours;
  • Komoot's suggested tours near the point (editorial and community, with rating and visitors).

Each candidate is scored 0–100 on how well it fits the session (distance, climbing, how far its start
is, loop, sport). Nothing is ever created on Komoot: a chosen route is only attached to the session,
with a link to open it in Komoot or a GPX of your own recording.

Based on the first version in feat/training-route-finder.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from routepass.models import Activity, ProviderActivity, TrainingPlan, TrainingSession
from routepass.providers import komoot as kmt
from routepass.providers.gpx import decode_polyline, encode_polyline, simplify
from routepass.timeutil import utcnow

logger = logging.getLogger(__name__)

SESSION_FAMILY = {
    "trail_run": "run",
    "run": "run",
    "bike": "ride",
    "ride": "ride",
    "cycling": "ride",
    "brick": "ride",
    "hike": "walk",
    "walk": "walk",
}
ROUTE_SPORTS = set(SESSION_FAMILY)
KOMOOT_SPORT = {
    "trail_run": "jogging",
    "run": "jogging",
    "bike": "racebike",
    "ride": "racebike",
    "cycling": "racebike",
    "brick": "racebike",
    "hike": "hike",
    "walk": "hike",
}
KOMOOT_FAMILY = {
    "jogging": "run",
    "running": "run",
    "trail_running": "run",
    "hike": "walk",
    "mountaineering": "walk",
    "racebike": "ride",
    "touringbicycle": "ride",
    "mtb": "ride",
    "mtb_easy": "ride",
    "mtb_advanced": "ride",
    "e_touringbicycle": "ride",
    "e_mtb": "ride",
    "e_racebike": "ride",
}
LOOP_KM = 0.6  # a route whose end is this close to its start is a loop

_cache: dict[tuple, tuple[float, Any]] = {}
_lock = threading.Lock()


def _cached(key: tuple, ttl_s: float, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl_s:
            return hit[1]
    value = fn()
    with _lock:
        _cache[key] = (time.time(), value)
    return value


def _km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


# ── where to start ───────────────────────────────────────────────────────────


def default_start(db: Session, prefs: dict[str, Any]) -> dict[str, Any]:
    """Saved place called Home → first saved place → where your recent activities usually start."""
    places = [p for p in prefs.get("places") or [] if p.get("lat") is not None and p.get("lng") is not None]
    home = next((p for p in places if str(p.get("name", "")).strip().lower() == "home"), None) or (
        places[0] if places else None
    )
    if home:
        return {
            "label": home["name"],
            "lat": float(home["lat"]),
            "lng": float(home["lng"]),
            "source": "place",
        }
    rows = db.execute(
        select(Activity.start_lat, Activity.start_lng)
        .where(Activity.start_lat.is_not(None), Activity.trainer.is_not(True))
        .order_by(Activity.start_time.desc())
        .limit(30)
    ).all()
    if rows:
        lats, lngs = sorted(r[0] for r in rows), sorted(r[1] for r in rows)
        return {
            "label": "Where you usually start",
            "lat": round(lats[len(lats) // 2], 5),
            "lng": round(lngs[len(lngs) // 2], 5),
            "source": "history",
        }
    return {"label": None, "lat": None, "lng": None, "source": "none"}


def geocode(query: str) -> list[dict[str, Any]]:
    """Places matching a search (OpenStreetMap Nominatim), cached for a day."""
    q = query.strip()
    if len(q) < 3:
        return []

    def fetch() -> list[dict[str, Any]]:
        try:
            resp = httpx.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": q, "format": "jsonv2", "limit": 6, "addressdetails": 0},
                headers={
                    "User-Agent": "RoutePass self-hosted training planner (https://github.com/dettinjo/routepass)"
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            items = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("Place search failed for %r: %s", q, exc)
            return []
        out = []
        for it in items if isinstance(items, list) else []:
            try:
                name = str(it.get("name") or it.get("display_name", "").split(",")[0]).strip()
                out.append(
                    {
                        "label": name or q,
                        "detail": str(it.get("display_name") or "")[:140],
                        "lat": round(float(it["lat"]), 5),
                        "lng": round(float(it["lon"]), 5),
                    }
                )
            except (KeyError, ValueError, TypeError):
                continue
        return out

    return _cached(("geocode", q.lower()), 86400, fetch)


# ── what the session asks for ────────────────────────────────────────────────


def _typical_speed_kmh(db: Session, family: str) -> float:
    """Your median moving speed for this sport over the last 120 days (default if unknown)."""
    since = utcnow() - timedelta(days=120)
    speeds = sorted(
        v
        for (v,) in db.execute(
            select(Activity.avg_speed_ms).where(
                Activity.family == family,
                Activity.start_time >= since,
                Activity.avg_speed_ms.is_not(None),
                Activity.trainer.is_not(True),
            )
        )
        if v and v > 0.5
    )
    if len(speeds) >= 3:
        return round(speeds[len(speeds) // 2] * 3.6, 1)
    return {"ride": 24.0, "run": 9.5, "walk": 4.5}.get(family, 9.5)


def session_targets(db: Session, s: TrainingSession) -> dict[str, Any]:
    family = SESSION_FAMILY.get(s.sport, "run")
    km = float(s.target_distance_km or 0)
    basis = "plan"
    if km < 0.5 and s.target_duration_s:
        km = round(float(s.target_duration_s) / 3600 * _typical_speed_kmh(db, family), 1)
        basis = "duration at your usual speed"
    return {
        "sport": s.sport,
        "family": family,
        "komoot_sport": KOMOOT_SPORT.get(s.sport, "jogging"),
        "distance_km": round(km, 1),
        "elevation_gain_m": round(float(s.target_elev_m or 0)),
        "duration_s": round(float(s.target_duration_s or 0)),
        "distance_basis": basis,
    }


# ── scoring ──────────────────────────────────────────────────────────────────


def score(
    target: dict[str, Any],
    *,
    distance_km: float,
    elevation_m: float,
    start_km: float,
    radius_km: float,
    loop: bool | None,
    family: str | None,
) -> tuple[int, dict[str, Any], list[str]]:
    """0–100: distance 45, climbing 25, start distance 15, loop 10, sport 5."""
    reasons: list[str] = []
    fit: dict[str, Any] = {}
    t_km = target["distance_km"]
    if t_km > 0.5 and distance_km > 0:
        err = (distance_km - t_km) / t_km
        fit["distance_pct"] = round(err * 100)
        d_pts = 45 * max(0.0, 1 - abs(err) / 0.5)
    else:
        d_pts = 30.0
    t_elev = target["elevation_gain_m"]
    if t_elev >= 50:
        diff = elevation_m - t_elev
        fit["elevation_m"] = round(diff)
        e_pts = 25 * max(0.0, 1 - abs(diff) / max(150.0, t_elev * 0.8))
    else:
        per_km = elevation_m / max(1.0, distance_km)
        e_pts = 25.0 if per_km <= 15 else max(5.0, 25 - (per_km - 15) * 0.5)
        if per_km > 15:
            reasons.append("Hillier than this session needs")
    s_pts = 15.0 if start_km <= 1.0 else 15 * max(0.0, 1 - start_km / max(2.0, radius_km))
    l_pts = 10.0 if loop else (5.0 if loop is None else 0.0)
    if loop is False:
        reasons.append("One way — you need a ride back")
    f_pts = 5.0 if family is None or family == target["family"] else 1.0
    total = round(min(100.0, d_pts + e_pts + s_pts + l_pts + f_pts))
    return total, fit, reasons


# ── candidates ───────────────────────────────────────────────────────────────


def _history(
    db: Session, target: dict[str, Any], lat: float, lng: float, radius_km: float
) -> list[dict[str, Any]]:
    fam = target["family"]
    fams = {fam, "walk"} if fam == "run" else {fam}
    rows = list(
        db.scalars(
            select(Activity)
            .where(
                Activity.start_lat.is_not(None),
                Activity.end_lat.is_not(None),
                Activity.distance_m > 500,
                Activity.family.in_(fams),
                Activity.trainer.is_not(True),
            )
            .order_by(Activity.start_time.desc())
            .limit(1500)
        )
    )
    komoot_ids = (
        dict(
            db.execute(
                select(ProviderActivity.activity_id, ProviderActivity.external_id).where(
                    ProviderActivity.provider == "komoot",
                    ProviderActivity.deleted.is_(False),
                    ProviderActivity.activity_id.in_([a.id for a in rows]),
                )
            ).all()
        )
        if rows
        else {}
    )
    groups: list[dict[str, Any]] = []
    for a in rows:
        start_km = _km(lat, lng, a.start_lat, a.start_lng)
        if start_km > radius_km:
            continue
        dist_km = (a.distance_m or 0) / 1000
        elev = a.elevation_gain_m or 0
        loop = _km(a.start_lat, a.start_lng, a.end_lat, a.end_lng) <= LOOP_KM
        # The same route done again: same start, end and length (±5 %) and climbing (±15 %).
        twin = next(
            (
                g
                for g in groups
                if g["loop"] == loop
                and _km(g["start_lat"], g["start_lng"], a.start_lat, a.start_lng) < 0.4
                and _km(g["_end"][0], g["_end"][1], a.end_lat, a.end_lng) < 0.6
                and abs(g["distance_km"] - dist_km) <= 0.05 * max(g["distance_km"], dist_km)
                and abs(g["elevation_gain_m"] - elev) <= max(40, 0.15 * max(g["elevation_gain_m"], elev))
            ),
            None,
        )
        if twin:
            twin["times_done"] += 1
            continue
        groups.append(
            {
                "id": f"history:{a.id}",
                "source": "history",
                "name": a.name or "Your route",
                "sport": a.sport,
                "distance_km": round(dist_km, 1),
                "elevation_gain_m": round(elev),
                "start_lat": a.start_lat,
                "start_lng": a.start_lng,
                "_end": (a.end_lat, a.end_lng),
                "start_distance_km": round(start_km, 1),
                "loop": loop,
                "family": a.family,
                "times_done": 1,
                "last_done": a.start_time.date().isoformat(),
                "activity_id": a.id,
                "polyline": a.polyline,
                "image": None,
                "komoot_tour_id": komoot_ids.get(a.id),
                "komoot_url": f"https://www.komoot.com/tour/{komoot_ids[a.id]}"
                if a.id in komoot_ids
                else None,
                "gpx_url": f"/api/v1/activities/{a.id}/gpx" if a.has_track else None,
            }
        )
    for g in groups:
        g.pop("_end", None)
    return groups


def _komoot_tour(t: dict[str, Any], source: str, lat: float, lng: float) -> dict[str, Any] | None:
    sp = t.get("start_point") or {}
    if sp.get("lat") is None:
        return None
    tid = str(t.get("id"))
    sport = str(t.get("sport") or "")
    summary_types = {
        s.get("type"): s.get("amount", 0) for s in ((t.get("summary") or {}).get("surfaces") or [])
    }
    paved = sum(v for k, v in summary_types.items() if k in ("sf#asphalt", "sf#paved", "sf#concrete"))
    surface = (
        None
        if not summary_types
        else ("mostly paved" if paved >= 0.6 else "mostly unpaved" if paved <= 0.3 else "mixed surface")
    )
    return {
        "id": f"{source}:{tid}",
        "source": source,
        "name": str(t.get("name") or "Komoot tour"),
        "sport": sport,
        "distance_km": round(float(t.get("distance") or 0) / 1000, 1),
        "elevation_gain_m": round(float(t.get("elevation_up") or 0)),
        "start_lat": float(sp["lat"]),
        "start_lng": float(sp["lng"]),
        "start_distance_km": round(_km(lat, lng, sp["lat"], sp["lng"]), 1),
        "loop": True if t.get("smart_tour_type") in ("EDITORIAL_TOUR", "ROUND_TRIP") else None,
        "family": KOMOOT_FAMILY.get(sport),
        "komoot_tour_id": tid,
        "image": t.get("_image"),
        "komoot_url": t.get("share_url")
        or (
            f"https://www.komoot.com/smarttour/{tid}"
            if source == "komoot_nearby"
            else f"https://www.komoot.com/tour/{tid}"
        ),
        "rating": round(float(t["rating_score"]), 1) if t.get("rating_score") else None,
        "visitors": t.get("visitors"),
        "difficulty": (t.get("difficulty") or {}).get("grade"),
        "surface": surface,
        "polyline": None,
        "activity_id": None,
        "gpx_url": None,
        "times_done": 0,
    }


def find_routes(
    db: Session,
    s: TrainingSession,
    prefs: dict[str, Any],
    *,
    lat: float | None = None,
    lng: float | None = None,
    label: str | None = None,
    radius_km: float = 10.0,
) -> dict[str, Any]:
    from routepass.engine.clients import NotConnected, komoot_client

    target = session_targets(db, s)
    start = default_start(db, prefs)
    if lat is not None and lng is not None:
        start = {
            "label": (label or "").strip() or f"{lat:.4f}, {lng:.4f}",
            "lat": lat,
            "lng": lng,
            "source": "custom",
        }
    out: dict[str, Any] = {
        "session_id": s.id,
        "target": target,
        "start": start,
        "radius_km": radius_km,
        "candidates": [],
        "sources": {},
        "errors": {},
        "komoot_connected": False,
        "planner_url": None,
    }
    if start["lat"] is None:
        return out
    lat, lng = start["lat"], start["lng"]
    out["planner_url"] = kmt.planner_url(lat, lng, target["komoot_sport"])

    cands = _history(db, target, lat, lng, radius_km)
    out["sources"]["history"] = len(cands)
    try:
        kc = komoot_client(db)
        out["komoot_connected"] = True
    except NotConnected:
        kc = None
    if kc is not None:
        with kc:
            try:
                planned = _cached(("planned", kc.user_id), 3600, lambda: kmt.planned_tours(kc))
                mine = [
                    c
                    for c in (_komoot_tour(t, "komoot_saved", lat, lng) for t in planned)
                    if c and c["start_distance_km"] <= radius_km and (c["family"] in (None, target["family"]))
                ]
                cands += mine
                out["sources"]["komoot_saved"] = len(mine)
            except kmt.KomootError as exc:
                out["errors"]["komoot_saved"] = str(exc)[:200]
            t_km = target["distance_km"]
            band = (int(t_km * 650), int(t_km * 1350)) if t_km > 1 else (None, None)
            key = ("nearby", round(lat, 3), round(lng, 3), target["komoot_sport"], radius_km, band)
            try:
                nearby = _cached(
                    key,
                    3600,
                    lambda: kmt.discover_tours(
                        kc,
                        lat,
                        lng,
                        sport=target["komoot_sport"],
                        radius_km=radius_km,
                        min_length_m=band[0],
                        max_length_m=band[1],
                        limit=24,
                    ),
                )
                seen = {c["komoot_tour_id"] for c in cands if c.get("komoot_tour_id")}
                near = [
                    c
                    for c in (_komoot_tour(t, "komoot_nearby", lat, lng) for t in nearby)
                    if c and c["komoot_tour_id"] not in seen
                ]
                cands += near
                out["sources"]["komoot_nearby"] = len(near)
            except kmt.KomootError as exc:
                out["errors"]["komoot_nearby"] = str(exc)[:200]

    for c in cands:
        c["match_score"], c["fit"], c["notes"] = score(
            target,
            distance_km=c["distance_km"],
            elevation_m=c["elevation_gain_m"],
            start_km=c["start_distance_km"],
            radius_km=radius_km,
            loop=c["loop"],
            family=c["family"],
        )
    cands.sort(key=lambda c: (-c["match_score"], c["start_distance_km"], -c.get("times_done", 0)))
    out["candidates"] = cands[:30]
    return out


def geometry(db: Session, source: str, ref: str) -> dict[str, Any]:
    """Encoded route line for a candidate, for the map."""
    from routepass.engine.clients import komoot_client

    if source == "history":
        act = db.get(Activity, int(ref))
        return {"polyline": act.polyline if act else None}

    def fetch() -> str | None:
        with komoot_client(db) as kc:
            pts = kmt.tour_coordinates(kc, ref, discovered=source == "komoot_nearby")
        return encode_polyline(simplify(pts, 400)) if len(pts) > 1 else None

    return {"polyline": _cached(("geom", source, ref), 86400, fetch)}


# ── attaching ────────────────────────────────────────────────────────────────

_KEEP = (
    "id",
    "source",
    "name",
    "sport",
    "distance_km",
    "elevation_gain_m",
    "start_lat",
    "start_lng",
    "loop",
    "match_score",
    "komoot_tour_id",
    "komoot_url",
    "activity_id",
    "gpx_url",
    "image",
    "times_done",
    "rating",
)


def attach(db: Session, s: TrainingSession, route: dict[str, Any]) -> dict[str, Any]:
    """Attach a chosen route to the session (nothing is created on Komoot)."""
    data = {k: route.get(k) for k in _KEEP}
    data["name"] = str(data.get("name") or s.title)[:180]
    poly = route.get("polyline")
    if isinstance(poly, str) and poly:
        pts = decode_polyline(poly)
        data["polyline"] = encode_polyline(simplify(pts, 250)) if len(pts) > 1 else None
    s.route_data = data
    db.flush()
    _calendar(db, s)
    return data


def detach(db: Session, s: TrainingSession) -> None:
    s.route_data = None
    db.flush()
    _calendar(db, s)


def _calendar(db: Session, s: TrainingSession) -> None:
    from routepass.analysis import training

    plan = db.get(TrainingPlan, s.plan_id)
    if plan is not None:
        training._maybe_sync_calendar(db, plan)

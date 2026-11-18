"""Import provider records, deduplicate them into Activities, and fetch tracks."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from routepass import store
from routepass.analysis import track as trk
from routepass.engine.clients import komoot_client, strava_client
from routepass.models import Activity, Effort, ProviderActivity, SyncJob, Track
from routepass.providers import sports
from routepass.providers.gpx import decode_polyline, encode_polyline, simplify
from routepass.providers.komoot import KomootClient, KomootError
from routepass.providers.strava import RateLimited, StravaClient, StravaError
from routepass.timeutil import parse_iso, utcnow

logger = logging.getLogger(__name__)

SYNC_EXTERNAL_PREFIX = "routepass-"
FULL_RESCAN_EVERY = timedelta(hours=24)


@dataclass
class ImportStats:
    new: int = 0
    updated: int = 0
    deleted: int = 0
    linked: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "new": self.new,
            "updated": self.updated,
            "deleted": self.deleted,
            "linked": self.linked,
            "errors": self.errors,
        }


# ── provider record normalization ────────────────────────────────────────────


def _strava_fields(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": raw.get("name") or "",
        "sport": raw.get("sport_type") or raw.get("type") or "Workout",
        "start_time": parse_iso(raw.get("start_date")),
        "distance_m": raw.get("distance"),
        "moving_time_s": raw.get("moving_time"),
        "elevation_gain_m": raw.get("total_elevation_gain"),
        "created_by_sync": str(raw.get("external_id") or "").startswith(SYNC_EXTERNAL_PREFIX),
    }


def _komoot_fields(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": raw.get("name") or "",
        "sport": raw.get("sport") or "touringbicycle",
        "start_time": parse_iso(raw.get("date")),
        "distance_m": raw.get("distance"),
        "moving_time_s": raw.get("time_in_motion") or raw.get("duration"),
        "elevation_gain_m": raw.get("elevation_up"),
    }


_STRAVA_KEEP = [
    "id",
    "name",
    "sport_type",
    "type",
    "start_date",
    "start_date_local",
    "timezone",
    "distance",
    "moving_time",
    "elapsed_time",
    "total_elevation_gain",
    "elev_high",
    "elev_low",
    "average_speed",
    "max_speed",
    "average_heartrate",
    "max_heartrate",
    "has_heartrate",
    "average_watts",
    "weighted_average_watts",
    "max_watts",
    "kilojoules",
    "device_watts",
    "average_cadence",
    "average_temp",
    "trainer",
    "commute",
    "manual",
    "private",
    "visibility",
    "gear_id",
    "external_id",
    "start_latlng",
    "end_latlng",
    "achievement_count",
    "kudos_count",
    "pr_count",
    "suffer_score",
    "workout_type",
]
_KOMOOT_KEEP = [
    "id",
    "name",
    "sport",
    "date",
    "distance",
    "duration",
    "time_in_motion",
    "elevation_up",
    "elevation_down",
    "status",
    "start_point",
    "changed_at",
    "source",
]


def _slim(raw: dict[str, Any], keep: list[str]) -> dict[str, Any]:
    out = {k: raw[k] for k in keep if k in raw}
    if raw.get("map", {}).get("summary_polyline"):
        out["summary_polyline"] = raw["map"]["summary_polyline"]
    return out


def upsert_provider_record(
    db: Session, provider: str, raw: dict[str, Any], stats: ImportStats
) -> ProviderActivity | None:
    fields = _strava_fields(raw) if provider == "strava" else _komoot_fields(raw)
    if fields["start_time"] is None:
        return None
    slim = _slim(raw, _STRAVA_KEEP if provider == "strava" else _KOMOOT_KEEP)
    ext_id = str(raw["id"])
    rec = db.scalar(
        select(ProviderActivity).where(
            ProviderActivity.provider == provider, ProviderActivity.external_id == ext_id
        )
    )
    now = utcnow()
    if rec is None:
        rec = ProviderActivity(provider=provider, external_id=ext_id, raw=slim, **fields)
        db.add(rec)
        stats.new += 1
    else:
        changed = rec.deleted or rec.raw != slim
        for key, value in fields.items():
            if key == "created_by_sync" and rec.created_by_sync:
                continue
            setattr(rec, key, value)
        rec.raw = slim
        rec.deleted = False
        if changed:
            stats.updated += 1
            if rec.activity_id:
                refresh_activity(db, rec.activity_id)
    rec.last_seen = now
    return rec


# ── importers ────────────────────────────────────────────────────────────────


def _history_start(db: Session) -> datetime | None:
    raw = store.get_preferences(db)["import"]["history_start"]
    return datetime.fromisoformat(raw) if raw else None


def import_strava(db: Session, client: StravaClient, *, full: bool = False) -> ImportStats:
    stats = ImportStats()
    state = store.get_value(db, "strava.import", {}) or {}
    last_full = parse_iso(state.get("last_full"))
    full = full or last_full is None or utcnow() - last_full > FULL_RESCAN_EVERY
    history_start = _history_start(db)
    after: int | None = int(history_start.timestamp()) if history_start else None
    if not full and state.get("watermark"):
        # Re-read the last few days so renames and late edits are picked up.
        after = max(after or 0, int(state["watermark"]) - 3 * 86400)

    seen: set[str] = set()
    newest = int(state.get("watermark") or 0)
    page = 1
    while True:
        batch = client.list_activities(after=after, page=page, per_page=200)
        for raw in batch:
            rec = upsert_provider_record(db, "strava", raw, stats)
            if rec is not None:
                seen.add(rec.external_id)
                newest = max(newest, int(rec.start_time.timestamp()))
        db.flush()
        if len(batch) < 200:
            break
        page += 1

    if full:
        stats.deleted += _mark_missing(db, "strava", seen, history_start)
        state["last_full"] = utcnow().isoformat()
    state["watermark"] = newest
    state["last_import"] = utcnow().isoformat()
    store.set_value(db, "strava.import", state)
    return stats


def import_komoot(db: Session, client: KomootClient, *, full: bool = False) -> ImportStats:
    stats = ImportStats()
    state = store.get_value(db, "komoot.import", {}) or {}
    last_full = parse_iso(state.get("last_full"))
    full = full or last_full is None or utcnow() - last_full > FULL_RESCAN_EVERY
    history_start = _history_start(db)
    stop_before = history_start
    if not full and state.get("watermark"):
        cutoff = datetime.fromtimestamp(int(state["watermark"])) - timedelta(days=3)
        stop_before = max(stop_before or cutoff, cutoff)

    seen: set[str] = set()
    newest = int(state.get("watermark") or 0)
    for raw in client.iter_recorded_tours():
        start = parse_iso(raw.get("date"))
        if start is not None and stop_before is not None and start < stop_before:
            break
        rec = upsert_provider_record(db, "komoot", raw, stats)
        if rec is not None:
            seen.add(rec.external_id)
            newest = max(newest, int(rec.start_time.timestamp()))
    db.flush()

    if full:
        stats.deleted += _mark_missing(db, "komoot", seen, history_start)
        state["last_full"] = utcnow().isoformat()
    state["watermark"] = newest
    state["last_import"] = utcnow().isoformat()
    store.set_value(db, "komoot.import", state)
    return stats


def _mark_missing(db: Session, provider: str, seen: set[str], since: datetime | None) -> int:
    q = select(ProviderActivity).where(
        ProviderActivity.provider == provider, ProviderActivity.deleted.is_(False)
    )
    if since is not None:
        q = q.where(ProviderActivity.start_time >= since)
    count = 0
    for rec in db.scalars(q):
        if rec.external_id not in seen:
            rec.deleted = True
            count += 1
            if rec.activity_id:
                refresh_activity(db, rec.activity_id)
    return count


# ── matching / dedup ─────────────────────────────────────────────────────────


def _compatible(rec: ProviderActivity, act: Activity, dist_tol: float) -> float | None:
    """Score how likely rec belongs to act (lower is better), or None if it cannot."""
    dt = abs((rec.start_time - act.start_time).total_seconds())
    score = dt / 60.0
    a, b = rec.distance_m or 0, act.distance_m or 0
    if a > 200 and b > 200:
        diff = abs(a - b) / max(a, b)
        if diff > dist_tol:
            return None
        score += diff * 20
    elif dt > 120:
        return None  # without distances only near-identical start times count
    if sports.family(sports.canonical(rec.provider, rec.sport)) != act.family:
        score += 2
    return score


def match_record(db: Session, rec: ProviderActivity, prefs: dict) -> bool:
    """Attach an unlinked record to an existing Activity or create one. True if it merged."""
    # 1) RoutePass created this record: link to the job's activity.
    job = db.scalar(
        select(SyncJob).where(
            SyncJob.target_provider == rec.provider,
            SyncJob.target_id == rec.external_id,
        )
    )
    if job is not None:
        rec.activity_id = job.activity_id
        rec.created_by_sync = True
        return True

    # 2) Same activity already known from another provider.
    tol = timedelta(minutes=prefs["matching"]["time_tolerance_min"])
    dist_tol = prefs["matching"]["distance_tolerance_pct"] / 100.0
    candidates = db.scalars(
        select(Activity).where(
            Activity.start_time >= rec.start_time - tol, Activity.start_time <= rec.start_time + tol
        )
    ).all()
    best: tuple[float, Activity] | None = None
    for act in candidates:
        taken = any(s.provider == rec.provider and not s.deleted and s.id != rec.id for s in act.sources)
        if taken:
            continue
        score = _compatible(rec, act, dist_tol)
        if score is not None and (best is None or score < best[0]):
            best = (score, act)
    if best is not None:
        rec.activity_id = best[1].id
        return True

    # 3) New activity.
    canonical_sport = sports.canonical(rec.provider, rec.sport)
    act = Activity(
        start_time=rec.start_time,
        name=rec.name,
        sport=canonical_sport,
        family=sports.family(canonical_sport),
    )
    db.add(act)
    db.flush()
    rec.activity_id = act.id
    return False


def match_unlinked(db: Session) -> int:
    prefs = store.get_preferences(db)
    linked = 0
    pending = db.scalars(
        select(ProviderActivity)
        .where(ProviderActivity.activity_id.is_(None), ProviderActivity.deleted.is_(False))
        .order_by(ProviderActivity.start_time)
    ).all()
    touched: set[int] = set()
    for rec in pending:
        if match_record(db, rec, prefs):
            linked += 1
        db.flush()
        touched.add(rec.activity_id)
    for act_id in touched:
        refresh_activity(db, act_id)
    return linked


# ── canonical activity fields ────────────────────────────────────────────────


def _primary(sources: list[ProviderActivity]) -> ProviderActivity | None:
    live = [s for s in sources if not s.deleted]
    if not live:
        return None
    # The original recording wins over a copy RoutePass made; Strava wins ties (richer data).
    return sorted(live, key=lambda s: (s.created_by_sync, s.provider != "strava", s.first_seen))[0]


def refresh_activity(db: Session, activity_id: int) -> Activity | None:
    act = db.get(Activity, activity_id)
    if act is None:
        return None
    db.refresh(act, ["sources"])
    live = [s for s in act.sources if not s.deleted]
    if not live:
        # All provider records are gone → the activity no longer exists anywhere.
        db.delete(act)
        db.flush()
        return None
    primary = _primary(act.sources)
    strava = next((s for s in live if s.provider == "strava"), None)
    komoot = next((s for s in live if s.provider == "komoot"), None)
    sr = strava.raw if strava else {}
    kr = komoot.raw if komoot else {}

    act.name = primary.name
    act.start_time = primary.start_time
    act.sport = sports.canonical(primary.provider, primary.sport)
    act.family = sports.family(act.sport)
    act.distance_m = primary.distance_m
    act.moving_time_s = primary.moving_time_s
    act.elapsed_time_s = sr.get("elapsed_time") or kr.get("duration") or primary.moving_time_s
    act.elevation_gain_m = primary.elevation_gain_m
    act.elevation_loss_m = kr.get("elevation_down")
    act.elevation_max_m = sr.get("elev_high")
    act.avg_speed_ms = sr.get("average_speed") or (
        act.distance_m / act.moving_time_s if act.distance_m and act.moving_time_s else None
    )
    act.max_speed_ms = sr.get("max_speed")
    act.avg_hr = sr.get("average_heartrate")
    act.max_hr = sr.get("max_heartrate")
    act.avg_power = sr.get("average_watts")
    act.normalized_power = sr.get("weighted_average_watts")
    act.max_power = sr.get("max_watts")
    act.avg_cadence = sr.get("average_cadence")
    act.avg_temp = sr.get("average_temp")
    act.work_kj = sr.get("kilojoules")
    act.trainer = bool(sr.get("trainer"))
    act.commute = bool(sr.get("commute"))
    act.gear = sr.get("gear_id")
    act.timezone = sr.get("timezone")
    act.start_local = parse_iso(sr.get("start_date_local")) if sr.get("start_date_local") else None

    if sr.get("start_latlng"):
        act.start_lat, act.start_lng = sr["start_latlng"][:2]
    elif kr.get("start_point"):
        act.start_lat, act.start_lng = kr["start_point"].get("lat"), kr["start_point"].get("lng")
    if sr.get("end_latlng"):
        act.end_lat, act.end_lng = sr["end_latlng"][:2]
    if sr.get("summary_polyline"):
        act.polyline = sr["summary_polyline"]

    track = db.get(Track, act.id)
    if track is not None:
        _apply_track_summary(db, act, track)
    else:
        prefs = store.get_preferences(db)["profile"]
        act.load, act.load_method, act.intensity = trk.compute_load(
            family=act.family,
            moving_s=act.moving_time_s,
            np_power=act.normalized_power,
            avg_hr=act.avg_hr,
            ftp=prefs["ftp"],
            hr_max=prefs["hr_max"],
            hr_rest=prefs["hr_rest"],
        )
    db.flush()
    return act


def _apply_track_summary(db: Session, act: Activity, track: Track) -> None:
    s = track.detail.get("summary", {})
    # Provider totals stay authoritative (Strava uses barometric data); the track fills gaps.
    for col, key in (
        ("distance_m", "distance_m"),
        ("moving_time_s", "moving_time_s"),
        ("elapsed_time_s", "elapsed_time_s"),
        ("elevation_gain_m", "elevation_gain_m"),
        ("avg_speed_ms", "avg_speed_ms"),
        ("avg_hr", "avg_hr"),
        ("max_hr", "max_hr"),
        ("avg_power", "avg_power"),
        ("max_power", "max_power"),
        ("avg_cadence", "avg_cadence"),
        ("avg_temp", "avg_temp"),
        ("work_kj", "work_kj"),
        ("start_lat", "start_lat"),
        ("start_lng", "start_lng"),
        ("end_lat", "end_lat"),
        ("end_lng", "end_lng"),
    ):
        if getattr(act, col) in (None, 0) and s.get(key) is not None:
            setattr(act, col, s[key])
    for col, key in (
        ("elevation_loss_m", "elevation_loss_m"),
        ("elevation_max_m", "elevation_max_m"),
        ("max_speed_ms", "max_speed_ms"),
        ("normalized_power", "normalized_power"),
        ("load", "load"),
        ("load_method", "load_method"),
        ("intensity", "intensity"),
    ):
        if s.get(key) is not None:
            setattr(act, col, s[key])
    if not act.polyline and track.points:
        pts = [(p["lat"], p["lon"]) for p in trk.unpack_points(track.points) if p.get("lat") is not None]
        if pts:
            act.polyline = encode_polyline(simplify(pts, 400))
    act.has_track = True
    act.track_provider = track.provider


# ── tracks ───────────────────────────────────────────────────────────────────


def store_track(db: Session, act: Activity, provider: str, normalized: trk.NormalizedTrack) -> Track:
    profile = store.get_preferences(db)["profile"]
    result = trk.compute(
        normalized,
        family=act.family,
        ftp=profile["ftp"],
        hr_max=profile["hr_max"],
        hr_rest=profile["hr_rest"],
    )
    track = db.get(Track, act.id)
    if track is None:
        track = Track(activity_id=act.id, provider=provider, data=b"")
        db.add(track)
    track.provider = provider
    track.data = normalized.pack()
    track.points = trk.pack_points(result.points)
    track.detail = {**result.detail, "summary": result.summary}
    track.channels = result.channels
    track.computed_at = utcnow()
    db.execute(delete(Effort).where(Effort.activity_id == act.id))
    for kind, key, value in result.efforts:
        db.add(Effort(activity_id=act.id, kind=kind, key=int(key), value=float(value)))
    db.flush()
    refresh_activity(db, act.id)
    return track


def recompute_tracks(db: Session) -> int:
    """Re-run metrics over every stored track (after profile changes)."""
    count = 0
    for track in db.scalars(select(Track)).all():
        act = db.get(Activity, track.activity_id)
        if act is not None:
            store_track(db, act, track.provider, trk.NormalizedTrack.unpack(track.data))
            count += 1
    for act in db.scalars(select(Activity).where(Activity.has_track.is_(False))).all():
        refresh_activity(db, act.id)
    return count


def _track_source(act: Activity) -> ProviderActivity | None:
    live = [s for s in act.sources if not s.deleted and s.track_status not in ("none", "error")]
    # Strava streams carry HR/power/cadence; Komoot only position + altitude.
    live.sort(key=lambda s: (s.provider != "strava", s.created_by_sync))
    return live[0] if live else None


def fetch_tracks(db: Session, budget_s: float = 240.0, limit: int = 200) -> dict[str, int]:
    """Download recordings for activities without a track, newest first."""
    started = time.monotonic()
    done = failed = 0
    rows = db.scalars(
        select(Activity)
        .where(Activity.has_track.is_(False))
        .order_by(Activity.start_time.desc())
        .limit(limit)
    ).all()
    strava: StravaClient | None = None
    komoot: KomootClient | None = None
    strava_blocked = False
    try:
        for act in rows:
            if time.monotonic() - started > budget_s:
                break
            src = _track_source(act)
            if src is None:
                continue
            try:
                if src.provider == "strava":
                    if strava_blocked:
                        continue
                    if not src.raw.get("summary_polyline") and src.raw.get("manual"):
                        src.track_status = "none"
                        continue
                    strava = strava or strava_client(db, background=True)
                    normalized = trk.from_strava_streams(strava.streams(src.external_id))
                else:
                    komoot = komoot or komoot_client(db)
                    normalized = trk.from_komoot_coordinates(komoot.coordinates(src.external_id))
                    time.sleep(0.5)
                if normalized is None:
                    src.track_status = "none"
                    continue
                store_track(db, act, src.provider, normalized)
                src.track_status = "done"
                done += 1
                db.commit()
            except RateLimited:
                strava_blocked = True
            except (StravaError, KomootError) as exc:
                logger.warning("Track fetch failed for %s %s: %s", src.provider, src.external_id, exc)
                src.track_status = "error"
                failed += 1
    finally:
        if strava:
            strava.close()
        if komoot:
            komoot.close()
    return {"fetched": done, "failed": failed, "rate_limited": int(strava_blocked)}


def polyline_points(act: Activity) -> list[tuple[float, float]]:
    return decode_polyline(act.polyline) if act.polyline else []

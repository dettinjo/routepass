"""Operations shared by the REST API and the MCP server."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from routepass import store
from routepass.analysis import insights
from routepass.analysis.track import unpack_points
from routepass.api import serialize
from routepass.engine import ingest, sync
from routepass.engine import rules as rule_engine
from routepass.engine.clients import connected
from routepass.models import Activity, ProviderActivity, SyncJob, SyncRule, SyncRun, Track
from routepass.providers import sports
from routepass.providers.strava import RATE
from routepass.timeutil import utcnow

SORTS = {
    "date": Activity.start_time,
    "distance": Activity.distance_m,
    "duration": Activity.moving_time_s,
    "elevation": Activity.elevation_gain_m,
    "speed": Activity.avg_speed_ms,
    "load": Activity.load,
    "hr": Activity.avg_hr,
    "power": Activity.avg_power,
    "name": Activity.name,
}


class NotFound(Exception):
    pass


def list_activities(
    db: Session,
    *,
    q: str | None = None,
    sport: list[str] | None = None,
    family: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    presence: str | None = None,  # both | strava_only | komoot_only | synced
    min_km: float | None = None,
    max_km: float | None = None,
    sort: str = "date",
    order: str = "desc",
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    f = insights.Filters(start=start, end=end, families=family, sports=sport)
    query = f.apply(select(Activity))
    if q:
        query = query.where(Activity.name.ilike(f"%{q}%"))
    if min_km is not None:
        query = query.where(Activity.distance_m >= min_km * 1000)
    if max_km is not None:
        query = query.where(Activity.distance_m <= max_km * 1000)
    if presence:
        live = select(ProviderActivity.activity_id).where(ProviderActivity.deleted.is_(False))
        on_s = live.where(ProviderActivity.provider == "strava")
        on_k = live.where(ProviderActivity.provider == "komoot")
        if presence == "both":
            query = query.where(Activity.id.in_(on_s), Activity.id.in_(on_k))
        elif presence == "strava_only":
            query = query.where(Activity.id.in_(on_s), Activity.id.not_in(on_k))
        elif presence == "komoot_only":
            query = query.where(Activity.id.in_(on_k), Activity.id.not_in(on_s))
        elif presence == "synced":
            query = query.where(Activity.id.in_(live.where(ProviderActivity.created_by_sync.is_(True))))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    col = SORTS.get(sort, Activity.start_time)
    query = query.order_by(col.desc().nulls_last() if order == "desc" else col.asc().nulls_last())
    per_page = max(1, min(per_page, 500))
    rows = db.scalars(
        query.options(selectinload(Activity.sources)).offset((page - 1) * per_page).limit(per_page)
    ).all()
    return {
        "items": [serialize.activity_row(a) for a in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


def get_activity(db: Session, activity_id: int) -> Activity:
    act = db.get(Activity, activity_id)
    if act is None:
        raise NotFound(f"activity {activity_id} not found")
    return act


def activity_detail(db: Session, activity_id: int) -> dict[str, Any]:
    act = get_activity(db, activity_id)
    out = serialize.activity_detail(act)
    track = db.get(Track, act.id)
    out["analysis"] = (
        {k: v for k, v in track.detail.items() if k != "summary"} | {"channels": track.channels}
        if track
        else None
    )
    jobs = db.scalars(select(SyncJob).where(SyncJob.activity_id == act.id).order_by(SyncJob.id)).all()
    out["sync_jobs"] = [serialize.job(j) for j in jobs]
    prefs = store.get_preferences(db)
    out["sync_status"] = {
        d: sync.blocker(act, d, prefs, utcnow() + timedelta(days=365)) for d in rule_engine.DIRECTION_TARGET
    }
    # Neighbouring activities for keyboard navigation in the UI.
    prev_id = db.scalar(
        select(Activity.id)
        .where(Activity.start_time < act.start_time)
        .order_by(Activity.start_time.desc())
        .limit(1)
    )
    next_id = db.scalar(
        select(Activity.id).where(Activity.start_time > act.start_time).order_by(Activity.start_time).limit(1)
    )
    out["prev_id"], out["next_id"] = prev_id, next_id
    return out


def activity_track(db: Session, activity_id: int) -> dict[str, Any]:
    act = get_activity(db, activity_id)
    track = db.get(Track, act.id)
    if track is None:
        return {"points": [], "channels": [], "provider": None}
    return {"points": unpack_points(track.points), "channels": track.channels, "provider": track.provider}


def similar_activities(db: Session, activity_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Same sport, similar distance, starting nearby — e.g. repeats of the same loop."""
    act = get_activity(db, activity_id)
    if not act.distance_m or act.start_lat is None:
        return []
    q = (
        select(Activity)
        .where(
            Activity.id != act.id,
            Activity.family == act.family,
            Activity.distance_m.between(act.distance_m * 0.9, act.distance_m * 1.1),
            Activity.start_lat.between(act.start_lat - 0.01, act.start_lat + 0.01),
            Activity.start_lng.between(act.start_lng - 0.015, act.start_lng + 0.015),
        )
        .order_by(Activity.start_time.desc())
        .limit(limit)
    )
    return [serialize.activity_row(a) for a in db.scalars(q.options(selectinload(Activity.sources)))]


def status(db: Session, running: bool) -> dict[str, Any]:
    conn = connected(db)
    last = db.scalar(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))
    job_counts = dict(db.execute(select(SyncJob.status, func.count()).group_by(SyncJob.status)).all())
    pending_tracks = db.scalar(select(func.count()).where(Activity.has_track.is_(False)))
    from routepass.config import get_settings

    return {
        "public_url": get_settings().public_url or None,
        "connections": {
            "strava": {"connected": conn["strava"], "athlete": store.get_value(db, "strava.athlete")},
            "komoot": {"connected": conn["komoot"], "account": store.get_value(db, "komoot.account")},
        },
        "running": running,
        "last_run": serialize.run(last) if last else None,
        "jobs": job_counts,
        "activities": db.scalar(select(func.count()).select_from(Activity)),
        "tracks_pending": pending_tracks,
        "coverage": insights.coverage(db),
        "strava_rate": RATE.as_dict(),
        "imports": {
            "strava": store.get_value(db, "strava.import"),
            "komoot": store.get_value(db, "komoot.import"),
        },
    }


# ── activity edits ───────────────────────────────────────────────────────────


def set_sync_lock(db: Session, activity_id: int, locked: bool) -> dict[str, Any]:
    act = get_activity(db, activity_id)
    act.sync_locked = locked
    db.flush()
    return serialize.activity_row(act)


def unlink_source(db: Session, activity_id: int, source_id: int) -> dict[str, Any]:
    """Split a provider record into its own activity (wrong automatic match)."""
    act = get_activity(db, activity_id)
    rec = next((s for s in act.sources if s.id == source_id), None)
    if rec is None:
        raise NotFound("source not part of this activity")
    if len([s for s in act.sources if not s.deleted]) < 2:
        raise ValueError("activity has only one source")
    canonical = sports.canonical(rec.provider, rec.sport)
    new = Activity(start_time=rec.start_time, name=rec.name, sport=canonical, family=sports.family(canonical))
    db.add(new)
    db.flush()
    rec.activity_id = new.id
    rec.match_locked = True
    db.execute(Track.__table__.delete().where(Track.activity_id == act.id, Track.provider == rec.provider))
    db.flush()
    ingest.refresh_activity(db, act.id)
    ingest.refresh_activity(db, new.id)
    return {"activity_id": act.id, "new_activity_id": new.id}


def merge_activities(db: Session, activity_id: int, other_id: int) -> dict[str, Any]:
    """Merge other into activity (both are the same real-world activity)."""
    act, other = get_activity(db, activity_id), get_activity(db, other_id)
    providers = {s.provider for s in act.sources if not s.deleted}
    clash = [s for s in other.sources if not s.deleted and s.provider in providers]
    if clash:
        raise ValueError("both activities already have a record on " + ", ".join(s.provider for s in clash))
    for s in list(other.sources):
        s.activity_id = act.id
        s.match_locked = True
    db.execute(SyncJob.__table__.update().where(SyncJob.activity_id == other.id).values(activity_id=act.id))
    db.flush()
    other_track = db.get(Track, other.id)
    if other_track is not None and db.get(Track, act.id) is None:
        other_track.activity_id = act.id
    db.flush()
    db.delete(db.get(Activity, other.id))
    db.flush()
    ingest.refresh_activity(db, act.id)
    return serialize.activity_detail(get_activity(db, act.id))


def refetch_track(db: Session, activity_id: int) -> dict[str, Any]:
    act = get_activity(db, activity_id)
    for s in act.sources:
        if s.track_status in ("error", "done"):
            s.track_status = "pending"
    act.has_track = False
    track = db.get(Track, act.id)
    if track is not None:
        db.delete(track)
    db.flush()
    return {"queued": True}


def sync_activity(db: Session, activity_id: int, direction: str) -> dict[str, Any]:
    act = get_activity(db, activity_id)
    if direction not in rule_engine.DIRECTION_TARGET:
        raise ValueError("unknown direction")
    db.execute(
        SyncJob.__table__.delete().where(
            SyncJob.activity_id == act.id,
            SyncJob.direction == direction,
            SyncJob.status.in_(("skipped", "failed")),
        )
    )
    result = sync.plan(db, activity_ids=[act.id], force=True)
    job = db.scalar(
        select(SyncJob)
        .where(SyncJob.activity_id == act.id, SyncJob.direction == direction)
        .order_by(SyncJob.id.desc())
        .limit(1)
    )
    if job is None:
        prefs = store.get_preferences(db)
        reason = sync.blocker(act, direction, prefs, utcnow() + timedelta(days=365))
        raise ValueError(f"cannot sync: {reason or 'not eligible'}")
    db.commit()
    if job.status == "queued":
        sync.run_jobs(db, job_ids=[job.id])
    db.refresh(job)
    return {"plan": result, "job": serialize.job(job)}


# ── rules ────────────────────────────────────────────────────────────────────


def list_rules(db: Session, direction: str | None = None) -> list[dict[str, Any]]:
    q = select(SyncRule).order_by(SyncRule.direction, SyncRule.priority, SyncRule.id)
    if direction:
        q = q.where(SyncRule.direction == direction)
    return [serialize.rule(r) for r in db.scalars(q)]


def save_rule(db: Session, data: dict[str, Any], rule_id: int | None = None) -> dict[str, Any]:
    if rule_id is not None:
        r = db.get(SyncRule, rule_id)
        if r is None:
            raise NotFound(f"rule {rule_id} not found")
    else:
        r = SyncRule(name="", direction=data.get("direction", ""))
        db.add(r)
    for key in ("name", "direction", "enabled", "priority", "conditions", "actions"):
        if key in data and data[key] is not None:
            setattr(r, key, data[key])
    if not r.name:
        raise ValueError("name is required")
    if r.priority is None:
        r.priority = 100
    rule_engine.validate(r.direction, r.conditions or {}, r.actions or {})
    db.flush()
    return serialize.rule(r)


def delete_rule(db: Session, rule_id: int) -> None:
    r = db.get(SyncRule, rule_id)
    if r is None:
        raise NotFound(f"rule {rule_id} not found")
    db.delete(r)
    db.flush()


def reorder_rules(db: Session, ids: list[int]) -> list[dict[str, Any]]:
    for i, rid in enumerate(ids):
        r = db.get(SyncRule, rid)
        if r is not None:
            r.priority = (i + 1) * 10
    db.flush()
    return list_rules(db)


def list_jobs(db: Session, status: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    q = select(SyncJob, Activity).join(Activity, Activity.id == SyncJob.activity_id, isouter=True)
    cq = select(func.count()).select_from(SyncJob)
    if status:
        statuses = status.split(",")
        q = q.where(SyncJob.status.in_(statuses))
        cq = cq.where(SyncJob.status.in_(statuses))
    rows = db.execute(q.order_by(SyncJob.updated_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [serialize.job(j, a) for j, a in rows], "total": db.scalar(cq)}


def reevaluate_skipped(db: Session) -> dict[str, int]:
    """Forget rule-skipped decisions so the next plan applies the current rules."""
    n = db.execute(SyncJob.__table__.delete().where(SyncJob.status == "skipped")).rowcount
    db.flush()
    return {"cleared": n, **sync.plan(db)}


def search_names(db: Session, text: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Activity)
        .where(or_(Activity.name.ilike(f"%{text}%"), Activity.description.ilike(f"%{text}%")))
        .order_by(Activity.start_time.desc())
        .limit(limit)
        .options(selectinload(Activity.sources))
    )
    return [serialize.activity_row(a) for a in rows]


# ── Strava webhooks ──────────────────────────────────────────────────────────

WEBHOOK_PATH = "/api/v1/webhooks/strava"


def _webhook_config(db: Session) -> tuple[str, str, str, str]:
    from routepass.config import get_settings
    from routepass.engine.clients import strava_app

    settings = get_settings()
    client_id, client_secret = strava_app(db)
    if not settings.public_url:
        raise ValueError("ROUTEPASS_PUBLIC_URL is not set — Strava cannot reach this instance")
    if not settings.strava_webhook_verify_token:
        raise ValueError("ROUTEPASS_STRAVA_WEBHOOK_VERIFY_TOKEN is not set")
    callback = settings.public_url.rstrip("/") + WEBHOOK_PATH
    return client_id, client_secret, callback, settings.strava_webhook_verify_token


def strava_webhook_status(db: Session) -> dict[str, Any]:
    from routepass.providers import strava

    client_id, client_secret, callback, _ = _webhook_config(db)
    subs = strava.list_push_subscriptions(client_id, client_secret)
    return {
        "callback_url": callback,
        "subscriptions": subs,
        "active": any(s.get("callback_url") == callback for s in subs),
        "last_event": store.get_value(db, "strava.last_webhook"),
    }


def strava_webhook_enable(db: Session) -> dict[str, Any]:
    """Subscribe this instance to Strava push events (replacing a subscription to another URL)."""
    from routepass.providers import strava

    client_id, client_secret, callback, verify = _webhook_config(db)
    for sub in strava.list_push_subscriptions(client_id, client_secret):
        if sub.get("callback_url") == callback:
            return {"active": True, "subscription": sub}
        strava.delete_push_subscription(client_id, client_secret, sub["id"])
    return {
        "active": True,
        "subscription": strava.create_push_subscription(client_id, client_secret, callback, verify),
    }


def strava_webhook_disable(db: Session) -> dict[str, Any]:
    from routepass.providers import strava

    client_id, client_secret, _, _ = _webhook_config(db)
    subs = strava.list_push_subscriptions(client_id, client_secret)
    for sub in subs:
        strava.delete_push_subscription(client_id, client_secret, sub["id"])
    return {"active": False, "removed": len(subs)}


def handle_strava_event(db: Session, event: dict[str, Any]) -> dict[str, Any]:
    """Strava push event → schedule a sync cycle (the cycle does the actual work)."""
    from routepass.engine import runner
    from routepass.engine.clients import STRAVA_ATHLETE, STRAVA_TOKENS

    athlete = store.get_value(db, STRAVA_ATHLETE) or {}
    if not athlete.get("id") or str(event.get("owner_id")) != str(athlete["id"]):
        return {"accepted": False, "reason": "unknown athlete"}
    store.set_value(db, "strava.last_webhook", {**event, "received_at": utcnow().isoformat()})
    if event.get("object_type") == "athlete" and (event.get("updates") or {}).get("authorized") == "false":
        store.delete_value(db, STRAVA_TOKENS)
        return {"accepted": True, "action": "deauthorized"}
    delay_min = store.get_preferences(db)["sync"].get("delay_minutes", 10)
    runner.trigger_soon()  # import the change now
    if event.get("aspect_type") == "create":
        runner.trigger_soon((delay_min + 1) * 60)  # and sync it once the settle delay has passed
    return {"accepted": True, "action": "sync scheduled"}


# ── multi-activity operations ────────────────────────────────────────────────


def bulk_sync(db: Session, activity_ids: list[int], direction: str) -> dict[str, Any]:
    """Queue and run copies for a hand-picked set (ignores start date and settle delay)."""
    if direction not in rule_engine.DIRECTION_TARGET:
        raise ValueError("unknown direction")
    ids = sorted(set(activity_ids))[:200]
    db.execute(
        SyncJob.__table__.delete().where(
            SyncJob.activity_id.in_(ids),
            SyncJob.direction == direction,
            SyncJob.status.in_(("skipped", "failed")),
        )
    )
    max_id = db.scalar(select(func.max(SyncJob.id))) or 0
    sync.plan(db, activity_ids=ids, force=True)
    jobs = db.scalars(select(SyncJob).where(SyncJob.id > max_id, SyncJob.direction == direction)).all()
    db.commit()
    blocked = {}
    prefs = store.get_preferences(db)
    planned = {j.activity_id for j in jobs}
    for aid in ids:
        if aid not in planned and (act := db.get(Activity, aid)) is not None:
            blocked[aid] = (
                sync.blocker(act, direction, prefs, utcnow() + timedelta(days=365)) or "not eligible"
            )
    queued = [j.id for j in jobs if j.status == "queued"]
    return {
        "queued": len(queued),
        "skipped_by_rules": sum(1 for j in jobs if j.status == "skipped"),
        "not_eligible": blocked,
        "job_ids": queued,
    }


def trip_analysis(db: Session, activity_ids: list[int]) -> dict[str, Any]:
    """Combine several activities (e.g. the days of a multi-day tour) into one overview."""
    acts = sorted(
        (a for a in (db.get(Activity, i) for i in set(activity_ids)) if a is not None),
        key=lambda a: a.start_time,
    )
    if len(acts) < 2:
        raise ValueError("select at least two activities")
    days: dict[str, dict[str, Any]] = {}
    for a in acts:
        d = (a.start_local or a.start_time).date().isoformat()
        day = days.setdefault(
            d,
            {
                "date": d,
                "activities": 0,
                "distance_m": 0.0,
                "moving_time_s": 0.0,
                "elevation_m": 0.0,
                "load": 0.0,
            },
        )
        day["activities"] += 1
        day["distance_m"] += a.distance_m or 0
        day["moving_time_s"] += a.moving_time_s or 0
        day["elevation_m"] += a.elevation_gain_m or 0
        day["load"] += a.load or 0
    total = {
        k: round(sum(d[k] for d in days.values()), 1)
        for k in ("distance_m", "moving_time_s", "elevation_m", "load")
    }
    first, last = acts[0], acts[-1]
    span_s = (last.start_time - first.start_time).total_seconds() + (
        last.elapsed_time_s or last.moving_time_s or 0
    )
    longest = max(days.values(), key=lambda d: d["distance_m"])
    hardest = max(days.values(), key=lambda d: d["elevation_m"])
    return {
        "activities": [serialize.activity_row(a) for a in acts],
        "days": [
            {**d, **{k: round(v, 1) for k, v in d.items() if isinstance(v, float)}} for d in days.values()
        ],
        "totals": {
            **total,
            "count": len(acts),
            "days": len(days),
            "span_days": round(span_s / 86400, 1),
            "avg_per_day_m": round(total["distance_m"] / len(days), 1),
            "avg_speed_ms": round(total["distance_m"] / total["moving_time_s"], 3)
            if total["moving_time_s"]
            else None,
        },
        "longest_day": longest["date"],
        "most_climbing_day": hardest["date"],
        "sports": sorted({a.sport for a in acts}),
    }

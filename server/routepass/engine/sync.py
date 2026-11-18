"""Plan and execute cross-provider copies without ever creating duplicates."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from routepass import store
from routepass.analysis import track as trk
from routepass.engine import rules as rule_engine
from routepass.engine.clients import komoot_client, strava_client
from routepass.engine.ingest import SYNC_EXTERNAL_PREFIX, refresh_activity, store_track
from routepass.models import Activity, ProviderActivity, SyncJob, SyncRule, Track
from routepass.providers.gpx import track_to_gpx
from routepass.providers.komoot import KomootAuthError, KomootClient, KomootError
from routepass.providers.strava import RateLimited, StravaAuthError, StravaClient, StravaError
from routepass.timeutil import utcnow

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BACKOFF = (timedelta(minutes=15), timedelta(hours=1), timedelta(hours=4), timedelta(hours=12))
OPEN_STATES = ("queued", "running", "done")
_DUPLICATE_RE = re.compile(r"duplicate of .*?/activities/(\d+)", re.IGNORECASE)


# ── eligibility ──────────────────────────────────────────────────────────────


def _live_source(act: Activity, provider: str) -> ProviderActivity | None:
    return next((s for s in act.sources if s.provider == provider and not s.deleted), None)


def blocker(act: Activity, direction: str, prefs: dict, now: datetime) -> str | None:
    """Why this activity cannot be synced in this direction right now (None = eligible)."""
    src_provider = rule_engine.DIRECTION_SOURCE[direction]
    target = rule_engine.DIRECTION_TARGET[direction]
    src = _live_source(act, src_provider)
    if src is None:
        return f"not on {src_provider}"
    if _live_source(act, target) is not None:
        return f"already on {target}"
    if src.created_by_sync:
        return "is itself a RoutePass copy"
    if act.sync_locked:
        return "sync locked"
    if start := prefs["sync"].get("start_date"):
        if act.start_time.date() < datetime.fromisoformat(start).date():
            return f"before sync start date {start}"
    delay = timedelta(minutes=prefs["sync"].get("delay_minutes", 10))
    if src.first_seen > now - delay:
        return "waiting for settle delay"
    if src_provider == "strava" and not src.raw.get("summary_polyline"):
        return "no GPS track (indoor or manual activity)"
    return None


def plan(db: Session, *, activity_ids: list[int] | None = None, force: bool = False) -> dict[str, int]:
    """Create queued jobs for eligible activities. force=True ignores start date, delay and lock."""
    prefs = store.get_preferences(db)
    rules = db.scalars(select(SyncRule)).all()
    now = utcnow()
    created = skipped = 0
    q = select(Activity)
    if activity_ids is not None:
        q = q.where(Activity.id.in_(activity_ids))
    elif start := prefs["sync"].get("start_date"):
        q = q.where(Activity.start_time >= datetime.fromisoformat(start))
    for direction in rule_engine.DIRECTION_TARGET:
        dprefs = prefs["sync"][direction]
        if not dprefs.get("enabled") and not force:
            continue
        existing = {
            a
            for (a,) in db.execute(
                select(SyncJob.activity_id).where(
                    SyncJob.direction == direction,
                    SyncJob.status.in_(OPEN_STATES + (("skipped",) if not force else ())),
                )
            )
        }
        for act in db.scalars(q):
            if act.id in existing:
                continue
            reason = blocker(act, direction, prefs, now)
            if reason and force and reason in ("sync locked", "waiting for settle delay"):
                reason = None
            if reason and force and reason.startswith("before sync start date"):
                reason = None
            if reason:
                continue
            src = _live_source(act, rule_engine.DIRECTION_SOURCE[direction])
            decision = rule_engine.decide(
                act, direction, rules, dprefs, description=src.raw.get("description", "") or ""
            )
            job = SyncJob(
                activity_id=act.id,
                direction=direction,
                source_provider=src.provider,
                source_id=src.external_id,
                target_provider=rule_engine.DIRECTION_TARGET[direction],
                rule_id=decision.rule_id,
                plan=decision.plan,
                reason=decision.reason,
                status="queued" if decision.sync else "skipped",
                next_attempt_at=now,
            )
            db.add(job)
            if decision.rule_id:
                rule = db.get(SyncRule, decision.rule_id)
                rule.match_count += 1
                rule.last_matched_at = now
            if decision.sync:
                created += 1
            else:
                skipped += 1
    db.flush()
    return {"queued": created, "skipped": skipped}


def preview(db: Session, direction: str, limit: int = 200) -> list[dict[str, Any]]:
    """Dry run: what the current rules would do with recent activities in a direction."""
    prefs = store.get_preferences(db)
    rules = db.scalars(select(SyncRule)).all()
    now = utcnow()
    out = []
    for act in db.scalars(select(Activity).order_by(Activity.start_time.desc()).limit(limit)):
        src = _live_source(act, rule_engine.DIRECTION_SOURCE[direction])
        if src is None:
            continue
        block = blocker(act, direction, prefs, now)
        decision = rule_engine.decide(
            act, direction, rules, prefs["sync"][direction], src.raw.get("description", "") or ""
        )
        out.append(
            {
                "activity_id": act.id,
                "name": act.name,
                "sport": act.sport,
                "start_time": act.start_time.isoformat() + "Z",
                "distance_m": act.distance_m,
                "would_sync": decision.sync and block is None,
                "blocked_by": block,
                "rule_id": decision.rule_id,
                "reason": decision.reason,
                "plan": decision.plan,
            }
        )
    return out


# ── execution ────────────────────────────────────────────────────────────────


def _komoot_to_strava(db: Session, job: SyncJob, komoot: KomootClient, strava: StravaClient) -> str:
    gpx = komoot.gpx(job.source_id)
    p = job.plan
    external_id = f"{SYNC_EXTERNAL_PREFIX}komoot-{job.source_id}"
    upload_id = strava.upload_gpx(gpx, p["name"], p.get("description", ""), p["sport"], external_id)
    try:
        activity_id = strava.wait_for_upload(upload_id)
    except StravaError as exc:
        dup = _DUPLICATE_RE.search(str(exc))
        if not dup:
            raise
        # Strava already has this recording: link instead of failing.
        job.reason = f"{job.reason}; Strava already had it"
        return dup.group(1)
    if updates := {k: v for k, v in (p.get("strava") or {}).items() if v is not None}:
        strava.update_activity(activity_id, **updates)
    return activity_id


def _strava_to_komoot(db: Session, job: SyncJob, strava: StravaClient, komoot: KomootClient) -> str:
    act = db.get(Activity, job.activity_id)
    stored = db.get(Track, act.id)
    if stored is not None and stored.provider == "strava":
        normalized = trk.NormalizedTrack.unpack(stored.data)
    else:
        normalized = trk.from_strava_streams(strava.streams(job.source_id))
        if normalized is not None:
            store_track(db, act, "strava", normalized)
    if normalized is None or not normalized.has_gps:
        raise StravaError("Strava activity has no GPS stream")
    gpx = track_to_gpx(normalized, job.plan["name"], job.plan["sport"], act.start_time)
    tour_id = komoot.upload_gpx(gpx, job.plan["name"], job.plan["sport"])
    visibility = (job.plan.get("komoot") or {}).get("visibility")
    if visibility:
        try:
            komoot.update_tour(tour_id, status=visibility, name=job.plan["name"])
        except KomootError as exc:
            logger.warning("Could not set Komoot visibility for %s: %s", tour_id, exc)
    return tour_id


def _record_copy(db: Session, job: SyncJob, target_id: str) -> None:
    act = db.get(Activity, job.activity_id)
    rec = db.scalar(
        select(ProviderActivity).where(
            ProviderActivity.provider == job.target_provider, ProviderActivity.external_id == target_id
        )
    )
    if rec is None:
        rec = ProviderActivity(
            provider=job.target_provider,
            external_id=target_id,
            name=job.plan.get("name", act.name),
            sport=job.plan.get("sport", act.sport),
            start_time=act.start_time,
            distance_m=act.distance_m,
            moving_time_s=act.moving_time_s,
            elevation_gain_m=act.elevation_gain_m,
            raw={"id": target_id},
            created_by_sync=True,
            track_status="none",
        )
        db.add(rec)
    rec.activity_id = act.id
    rec.created_by_sync = True
    rec.deleted = False
    db.flush()
    refresh_activity(db, act.id)


def run_jobs(db: Session, limit: int = 25, job_ids: list[int] | None = None) -> dict[str, int]:
    now = utcnow()
    q = select(SyncJob).where(SyncJob.status == "queued").order_by(SyncJob.created_at)
    if job_ids:
        q = q.where(SyncJob.id.in_(job_ids))
    else:
        q = q.where((SyncJob.next_attempt_at.is_(None)) | (SyncJob.next_attempt_at <= now))
    jobs = db.scalars(q.limit(limit)).all()
    stats = {"done": 0, "failed": 0, "deferred": 0}
    if not jobs:
        return stats
    strava = komoot = None
    try:
        for job in jobs:
            act = db.get(Activity, job.activity_id)
            if act is None or _live_source(act, job.target_provider) is not None:
                job.status = "skipped"
                job.reason = f"already on {job.target_provider}"
                continue
            job.status = "running"
            job.attempts += 1
            db.commit()
            try:
                strava = strava or strava_client(db)
                komoot = komoot or komoot_client(db)
                if job.direction == "komoot_to_strava":
                    target_id = _komoot_to_strava(db, job, komoot, strava)
                else:
                    target_id = _strava_to_komoot(db, job, strava, komoot)
                job.target_id = target_id
                job.status = "done"
                job.error = None
                _record_copy(db, job, target_id)
                stats["done"] += 1
            except RateLimited as exc:
                job.status = "queued"
                job.attempts -= 1
                job.next_attempt_at = exc.retry_at.replace(tzinfo=None)
                stats["deferred"] += 1
                db.commit()
                break
            except (StravaAuthError, KomootAuthError) as exc:
                job.status = "failed"
                job.error = f"Authentication failed — reconnect in Settings: {exc}"
                stats["failed"] += 1
            except Exception as exc:  # noqa: BLE001 — any provider failure is retried later
                logger.exception("Sync job %s failed", job.id)
                job.error = str(exc)[:2000]
                if job.attempts >= MAX_ATTEMPTS:
                    job.status = "failed"
                else:
                    job.status = "queued"
                    job.next_attempt_at = utcnow() + BACKOFF[min(job.attempts - 1, len(BACKOFF) - 1)]
                stats["failed"] += 1
            db.commit()
    finally:
        if strava:
            strava.close()
        if komoot:
            komoot.close()
    return stats


def retry(db: Session, job_id: int) -> SyncJob | None:
    job = db.get(SyncJob, job_id)
    if job is None or job.status not in ("failed", "skipped", "queued"):
        return job
    if job.status == "skipped":
        # Re-plan from scratch with the current rules (honours a changed rule set).
        act_id = job.activity_id
        db.delete(job)
        db.flush()
        plan(db, activity_ids=[act_id], force=True)
        return None
    job.status = "queued"
    job.attempts = 0
    job.next_attempt_at = utcnow()
    job.error = None
    db.flush()
    return job

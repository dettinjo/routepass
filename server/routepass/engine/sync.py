"""Plan and execute cross-provider copies without ever creating duplicates."""

from __future__ import annotations

import logging
import re
import time
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
    if src_provider == "strava" and not src.raw.get("summary_polyline"):
        if src.raw.get("trainer") or src.raw.get("manual") or src.track_status == "none":
            return "no GPS track (indoor or manual activity)"
        if src.raw.get("source") != "web" and not act.polyline:
            return "no GPS track (indoor or manual activity)"
    # soft blockers below can be overridden by a manual / all-time sync
    if act.sync_locked:
        return "sync locked"
    if start := prefs["sync"].get("start_date"):
        if act.start_time.date() < datetime.fromisoformat(start).date():
            return f"before sync start date {start}"
    delay = timedelta(minutes=prefs["sync"].get("delay_minutes", 10))
    if src.first_seen > now - delay:
        return "waiting for settle delay"
    return None


def plan(
    db: Session,
    *,
    activity_ids: list[int] | None = None,
    force: bool = False,
    prefs_override: dict | None = None,
    directions: list[str] | None = None,
    ignore_rules: bool = False,
    honour_lock: bool = False,
) -> dict[str, int]:
    """Create queued jobs for eligible activities. force=True ignores start date, delay and lock."""
    prefs = prefs_override or store.get_preferences(db)
    rules = [] if ignore_rules else db.scalars(select(SyncRule)).all()
    now = utcnow()
    created = skipped = 0
    q = select(Activity)
    if activity_ids is not None:
        q = q.where(Activity.id.in_(activity_ids))
    elif start := prefs["sync"].get("start_date"):
        q = q.where(Activity.start_time >= datetime.fromisoformat(start))
    for direction in directions or rule_engine.DIRECTION_TARGET:
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
            overridable = (
                ("waiting for settle delay",) if honour_lock else ("sync locked", "waiting for settle delay")
            )
            if reason and force and reason in overridable:
                reason = None
            if reason and force and reason.startswith("before sync start date"):
                reason = None
            if reason:
                continue
            src = _live_source(act, rule_engine.DIRECTION_SOURCE[direction])
            decision = rule_engine.decide(
                act,
                direction,
                rules,
                dprefs,
                description=src.raw.get("description", "") or "",
                places=prefs.get("places"),
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
            act,
            direction,
            rules,
            prefs["sync"][direction],
            src.raw.get("description", "") or "",
            prefs.get("places"),
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


def _upload_komoot_photos(
    komoot: KomootClient,
    strava: StravaClient,
    tour_id: str,
    strava_activity_id: str,
    already_synced_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Download photos from a Komoot tour and upload unseen ones to a Strava activity."""
    seen = set(already_synced_ids or ())
    photos = komoot.tour_photos(tour_id)
    uploaded_ids: list[str] = []
    skipped_existing = 0
    errors: list[str] = []

    for idx, ph in enumerate(photos, start=1):
        pid = ph["id"]
        if pid in seen:
            skipped_existing += 1
            continue
        try:
            img_bytes, ctype = komoot.download_photo(ph["url"])
            ext = "png" if "png" in ctype else ("webp" if "webp" in ctype else "jpg")
            strava.upload_photo(
                strava_activity_id,
                img_bytes,
                filename=f"komoot-{tour_id}-{idx}.{ext}",
                content_type=ctype,
                caption=ph.get("caption") or "",
            )
            uploaded_ids.append(pid)
            seen.add(pid)
        except (KomootError, StravaError) as exc:
            errors.append(str(exc))
            # If Strava Web Session is missing or rejected auth, stop trying remaining photos.
            if "Web Session" in str(exc) or isinstance(exc, StravaAuthError):
                break

    return {
        "photos_found": len(photos),
        "photos_uploaded": len(uploaded_ids),
        "photos_skipped_existing": skipped_existing,
        "uploaded_ids": uploaded_ids,
        "errors": errors,
    }


def _komoot_to_strava(db: Session, job: SyncJob, komoot: KomootClient, strava: StravaClient) -> str:
    gpx = komoot.gpx(job.source_id)
    p = job.plan
    name = p["name"]
    description = p.get("description", "") or ""

    # Komoot's tour list often omits full descriptions; fetch tour details if description is empty.
    if not description:
        try:
            details = komoot.tour_details(job.source_id)
            if details.get("description"):
                description = details["description"]
            if not name and details.get("name"):
                name = details["name"]
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not fetch Komoot tour details for %s: %s", job.source_id, exc)

    external_id = f"{SYNC_EXTERNAL_PREFIX}komoot-{job.source_id}"
    upload_id = strava.upload_gpx(gpx, name, description, p["sport"], external_id)
    try:
        activity_id = strava.wait_for_upload(upload_id)
    except StravaError as exc:
        dup = _DUPLICATE_RE.search(str(exc))
        if not dup:
            raise
        # Strava already has this recording: link instead of failing.
        job.reason = f"{job.reason}; Strava already had it"
        return dup.group(1)

    updates = {k: v for k, v in (p.get("strava") or {}).items() if v is not None}
    if description:
        updates.setdefault("description", description)
    if updates:
        try:
            strava.update_activity(activity_id, **updates)
        except StravaError as exc:
            logger.warning("Could not apply post-upload updates on Strava %s: %s", activity_id, exc)

    prefs = store.get_preferences(db)
    if prefs.get("sync", {}).get("komoot_to_strava", {}).get("sync_photos", True):
        try:
            ph_res = _upload_komoot_photos(komoot, strava, job.source_id, activity_id)
            if ph_res["photos_uploaded"]:
                job.reason = f"{job.reason}; {ph_res['photos_uploaded']} photo(s) synced"
            elif ph_res["errors"]:
                logger.info("Skipped Komoot→Strava photo sync for %s: %s", job.source_id, ph_res["errors"][0])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Komoot→Strava photo sync failed for %s: %s", job.source_id, exc)

    return activity_id


def sync_komoot_media_to_strava(
    db: Session,
    act: Activity,
    *,
    sync_title: bool = True,
    sync_description: bool = True,
    sync_photos: bool = True,
) -> dict[str, Any]:
    """Push title, description, and/or photos from Komoot to the linked Strava activity."""
    komoot_src = _live_source(act, "komoot")
    strava_src = _live_source(act, "strava")
    if komoot_src is None:
        raise ValueError("This activity has no Komoot record")
    if strava_src is None:
        raise ValueError("This activity is not on Strava yet — copy it to Strava first")

    komoot = komoot_client(db)
    strava = strava_client(db)
    if komoot is None:
        raise ValueError("Komoot is not connected")
    if strava is None:
        raise ValueError("Strava is not connected")

    title_synced = False
    description_synced = False
    warnings: list[str] = []
    photo_stats: dict[str, Any] = {
        "photos_found": 0,
        "photos_uploaded": 0,
        "photos_skipped_existing": 0,
        "errors": [],
    }

    with komoot, strava:
        details = komoot.tour_details(komoot_src.external_id)
        k_title = details.get("name") or komoot_src.name or act.name or ""
        k_desc = details.get("description") or (komoot_src.raw or {}).get("description") or ""

        updates: dict[str, Any] = {}
        if sync_title and k_title:
            updates["name"] = k_title[:250]
        if sync_description and k_desc:
            updates["description"] = k_desc

        if updates:
            strava.update_activity(strava_src.external_id, **updates)
            if "name" in updates:
                title_synced = True
                strava_src.name = updates["name"]
                act.name = updates["name"]
            if "description" in updates:
                description_synced = True
                k_raw = dict(komoot_src.raw or {})
                k_raw["description"] = k_desc
                komoot_src.raw = k_raw
                s_raw = dict(strava_src.raw or {})
                s_raw["description"] = k_desc
                strava_src.raw = s_raw
        elif sync_description and not k_desc and not sync_title:
            warnings.append("No description found on this Komoot tour.")

        if sync_photos:
            existing_ids = set((strava_src.raw or {}).get("synced_komoot_photo_ids") or [])
            photo_stats = _upload_komoot_photos(
                komoot,
                strava,
                komoot_src.external_id,
                strava_src.external_id,
                already_synced_ids=existing_ids,
            )
            if photo_stats["uploaded_ids"]:
                s_raw = dict(strava_src.raw or {})
                s_raw["synced_komoot_photo_ids"] = sorted(existing_ids | set(photo_stats["uploaded_ids"]))
                strava_src.raw = s_raw
            if photo_stats["errors"]:
                warnings.extend(photo_stats["errors"])

    db.flush()
    return {
        "activity_id": act.id,
        "komoot_id": komoot_src.external_id,
        "strava_id": strava_src.external_id,
        "title_synced": title_synced,
        "description_synced": description_synced,
        "photos_found": photo_stats["photos_found"],
        "photos_uploaded": photo_stats["photos_uploaded"],
        "photos_skipped_existing": photo_stats["photos_skipped_existing"],
        "warnings": warnings,
    }


def _strava_to_komoot(db: Session, job: SyncJob, strava_getter, komoot: KomootClient) -> str:
    act = db.get(Activity, job.activity_id)
    stored = db.get(Track, act.id)
    if stored is not None and stored.provider == "strava":
        # Recording already stored (Strava API earlier, or the user's own Strava archive).
        normalized = trk.NormalizedTrack.unpack(stored.data)
    else:
        normalized = trk.from_strava_streams(strava_getter().streams(job.source_id))
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
                komoot = komoot or komoot_client(db)

                def get_strava() -> StravaClient:
                    nonlocal strava
                    strava = strava or strava_client(db)
                    return strava

                if job.direction == "komoot_to_strava":
                    target_id = _komoot_to_strava(db, job, komoot, get_strava())
                else:
                    target_id = _strava_to_komoot(db, job, get_strava, komoot)
                    time.sleep(1.0)  # Komoot has no published limits; stay polite on long backlogs
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

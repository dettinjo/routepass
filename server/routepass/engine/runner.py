"""One sync cycle (import → dedup → plan → upload → tracks) and the background scheduler."""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from routepass import store
from routepass.config import get_settings
from routepass.db import session_scope
from routepass.engine import ingest, sync
from routepass.engine.clients import NotConnected, connected, komoot_client, strava_client
from routepass.models import ProviderActivity, SyncJob, SyncRun
from routepass.timeutil import utcnow

logger = logging.getLogger(__name__)

_lock = threading.Lock()
BACKLOG_INTERVAL_S = 120  # how often queued copies are worked off between scheduled syncs
POLL_CHOICES_MIN = (30, 60, 120, 360)  # automatic sync intervals; 0 = manual only
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None


def is_running() -> bool:
    return _lock.locked()


def run_cycle(trigger: str = "manual", *, full: bool = False, tracks: bool = True) -> dict[str, Any]:
    """Run a complete cycle. Returns the run summary; concurrent calls are rejected."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", "message": "A sync cycle is already running"}
    try:
        return _cycle(trigger, full, tracks)
    finally:
        _lock.release()


def _cycle(trigger: str, full: bool, tracks: bool) -> dict[str, Any]:
    with session_scope() as db:
        run = SyncRun(trigger=trigger)
        db.add(run)
        db.flush()
        run_id = run.id
    stats: dict[str, Any] = {}
    log: list[str] = []
    status = "ok"

    def note(msg: str) -> None:
        logger.info(msg)
        log.append(f"{utcnow():%H:%M:%S} {msg}")

    with session_scope() as db:
        conn = connected(db)
        prefs = store.get_preferences(db)

    for provider in ("strava", "komoot"):
        if not conn[provider]:
            continue
        try:
            with session_scope() as db:
                if provider == "strava":
                    with strava_client(db) as client:
                        result = ingest.import_strava(db, client, full=full)
                else:
                    with komoot_client(db) as client:
                        result = ingest.import_komoot(db, client, full=full)
            stats[f"import_{provider}"] = result.as_dict()
            with session_scope() as db:
                store.delete_value(db, f"{provider}.error")
            note(f"{provider}: {result.new} new, {result.updated} updated, {result.deleted} removed")
        except NotConnected:
            pass
        except Exception as exc:  # noqa: BLE001 — one provider failing must not stop the other
            status = "partial"
            note(f"{provider} import failed: {exc}")
            logger.exception("%s import failed", provider)
            with session_scope() as db:
                store.set_value(
                    db,
                    f"{provider}.error",
                    {
                        "message": str(exc)[:400],
                        "at": utcnow().isoformat() + "Z",
                        "hint": _error_hint(provider, str(exc)),
                    },
                )

    with session_scope() as db:
        stats["linked"] = ingest.match_unlinked(db)
        note(f"matching: {stats['linked']} records merged into existing activities")

    with session_scope() as db:
        has_strava_records = (
            db.scalar(
                select(func.count())
                .select_from(ProviderActivity)
                .where(ProviderActivity.provider == "strava")
            )
            or 0
        )
        strava_api_ok = conn["strava"] and not _strava_blocked(db)
    directions = [
        d
        for d, ok in (("strava_to_komoot", bool(has_strava_records)), ("komoot_to_strava", strava_api_ok))
        if ok
    ]
    if conn["komoot"] and directions:
        try:
            with session_scope() as db:
                if prefs["sync"]["auto"]:
                    stats["planned"] = sync.plan(db, directions=directions)
                    note(
                        f"planned: {stats['planned']['queued']} to sync, {stats['planned']['skipped']} skipped by rules"
                    )
            stats["jobs"] = _drain_jobs()
            if any(stats["jobs"].values()):
                note(
                    f"sync: {stats['jobs']['done']} done, {stats['jobs']['failed']} failed, "
                    f"{stats['jobs']['deferred']} deferred"
                )
        except Exception as exc:  # noqa: BLE001
            status = "partial"
            note(f"sync failed: {exc}")
            logger.exception("sync failed")

    if tracks:
        try:
            with session_scope() as db:
                stats["tracks"] = ingest.fetch_tracks(db)
                note(f"tracks: {stats['tracks']['fetched']} downloaded")
        except Exception as exc:  # noqa: BLE001
            status = "partial"
            note(f"track download failed: {exc}")
            logger.exception("track download failed")

    try:
        from routepass.analysis import training

        with session_scope() as db:
            t_stats = training.sync_active_plans_after_ingest(db, prefs)
        if t_stats["plans"] > 0:
            stats["training"] = t_stats
            note(
                f"training: {t_stats['matched']} matched, {t_stats['missed']} missed, {t_stats['adapted']} adapted"
            )
    except Exception as exc:  # noqa: BLE001
        note(f"training sync failed: {exc}")
        logger.exception("training sync failed")

    with session_scope() as db:
        run = db.get(SyncRun, run_id)
        run.finished_at = utcnow()
        run.status = status
        run.stats = stats
        run.log = log
    return {"status": status, "run_id": run_id, "stats": stats, "log": log}


JOB_BUDGET_S = 600  # per cycle; a large backlog (all-time sync) continues in the next cycle


def _drain_jobs() -> dict[str, int]:
    """Work off due jobs in batches until none are left, a rate limit hits, or the budget is used."""
    started = time.monotonic()
    total = {"done": 0, "failed": 0, "deferred": 0}
    while time.monotonic() - started < JOB_BUDGET_S:
        with session_scope() as db:
            batch = sync.run_jobs(db, limit=20)
        for k in total:
            total[k] += batch[k]
        if batch["deferred"] or not (batch["done"] + batch["failed"]):
            break
    return total


def backlog() -> int:
    with session_scope() as db:
        return (
            db.scalar(
                select(func.count())
                .select_from(SyncJob)
                .where(SyncJob.status == "queued", SyncJob.next_attempt_at <= utcnow() + timedelta(minutes=5))
            )
            or 0
        )


def _strava_blocked(db) -> bool:
    """Strava refuses API access for the whole application (unless a web session is connected)."""
    if store.get_value(db, "strava.web_session") is not None:
        return False
    err = store.get_value(db, "strava.error") or {}
    return "Inactive" in (err.get("message") or "")


def _error_hint(provider: str, message: str) -> str:
    if provider == "strava" and "Inactive" in message:
        return (
            "Strava has deactivated this API application (since June 2026 the app owner needs a paid "
            "subscription at strava.com/settings/api). To sync for free without a subscription, connect "
            "a Strava web session cookie in Settings → Strava → Web session, or import your Strava data export."
        )
    if "401" in message or "Authentication" in message or "rejected" in message or "expired" in message:
        return f"{provider.title()} rejected the login — reconnect it in Settings."
    if "429" in message or "rate limit" in message.lower():
        return "Rate limit reached — RoutePass continues automatically later."
    return f"{provider.title()} could not be reached; RoutePass retries on the next sync."


def last_run() -> SyncRun | None:
    with session_scope() as db:
        return db.scalar(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))


def trigger_soon(delay_s: float = 0) -> None:
    """Wake the scheduler now, or after delay_s (e.g. once a webhook's settle delay has passed)."""
    if delay_s <= 0:
        _wake.set()
        return
    timer = threading.Timer(delay_s, _wake.set)
    timer.daemon = True
    timer.start()


_reschedule = threading.Event()


def reschedule() -> None:
    """Recompute the next scheduled run (after a settings change) without syncing now."""
    _reschedule.set()
    _wake.set()


def poll_interval_min() -> int:
    """Minutes between automatic syncs; 0 means manual only."""
    with session_scope() as db:
        value = store.get_preferences(db).get("poll_interval_minutes")
    if value is None:
        value = get_settings().poll_interval_minutes
    value = int(value)
    if value <= 0:
        return 0
    return max(POLL_CHOICES_MIN[0], value)


def drain_backlog() -> dict[str, int] | None:
    """Work off queued copies without polling the platforms (respects the cycle lock)."""
    if not _lock.acquire(blocking=False):
        return None
    try:
        return _drain_jobs()
    finally:
        _lock.release()


def _loop() -> None:
    _stop.wait(15)  # let the app finish starting
    last_cycle = 0.0
    while not _stop.is_set():
        woken = _wake.is_set() and not _reschedule.is_set()
        _wake.clear()
        _reschedule.clear()
        interval_s = poll_interval_min() * 60
        due = bool(interval_s) and time.monotonic() - last_cycle >= interval_s
        try:
            if woken or due:
                # explicit triggers (webhook, new connection, settings change) and the schedule
                run_cycle("schedule" if due and not woken else "trigger")
                last_cycle = time.monotonic()
            elif backlog():
                drain_backlog()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler step crashed")
        if backlog():
            timeout = BACKLOG_INTERVAL_S
        elif interval_s:
            timeout = max(5.0, interval_s - (time.monotonic() - last_cycle))
        else:
            timeout = 3600.0  # manual only: sleep until something wakes us
        _wake.wait(timeout)


def start_scheduler() -> None:
    global _thread
    if _thread is not None or not get_settings().scheduler_enabled:
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="routepass-scheduler", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    global _thread
    _stop.set()
    _wake.set()
    _thread = None

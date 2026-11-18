"""One-off "everything, all time" sync: import full history on both platforms, merge, and copy
every activity that is missing on the other side. Copies are queued as normal jobs and worked
off by the scheduler within the rate limits."""

from __future__ import annotations

import logging
import threading
from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from routepass import store
from routepass.db import session_scope
from routepass.engine import ingest, sync
from routepass.engine import rules as rule_engine
from routepass.engine.clients import komoot_client, strava_client
from routepass.models import Activity, SyncJob, SyncRule
from routepass.timeutil import iso, parse_iso, utcnow

logger = logging.getLogger(__name__)
STATE_KEY = "fullsync"
_lock = threading.Lock()


def state(db: Session) -> dict[str, Any]:
    st = store.get_value(db, STATE_KEY) or {"phase": "idle"}
    if st.get("phase") == "running" and st.get("started_at"):
        q = (
            select(SyncJob.status, func.count())
            .where(SyncJob.created_at >= parse_iso(st["started_at"]))
            .group_by(SyncJob.status)
        )
        counts = dict(db.execute(q).all())
        st["progress"] = {k: counts.get(k, 0) for k in ("queued", "running", "done", "failed", "skipped")}
        if not counts.get("queued") and not counts.get("running"):
            st["phase"] = "finished"
            st["finished_at"] = iso(utcnow())
            store.set_value(db, STATE_KEY, {k: v for k, v in st.items() if k != "progress"})
    return st


def _set(**fields: Any) -> None:
    with session_scope() as db:
        st = store.get_value(db, STATE_KEY) or {}
        st.update(fields)
        store.set_value(db, STATE_KEY, st)


def _preview(db: Session, directions: list[str], apply_rules: bool) -> dict[str, Any]:
    prefs = store.get_preferences(db)
    prefs = {**prefs, "sync": {**prefs["sync"], "start_date": None}}
    far = utcnow().replace(year=utcnow().year + 1)
    rules = db.scalars(select(SyncRule)).all() if apply_rules else []
    out: dict[str, Any] = {}
    acts = db.scalars(select(Activity)).all()
    for direction in directions:
        missing = 0
        blocked: Counter[str] = Counter()
        skipped = 0
        for act in acts:
            reason = sync.blocker(act, direction, prefs, far)
            if reason is None:
                missing += 1
                dprefs = (
                    {**prefs["sync"][direction], "default_action": "sync"}
                    if not apply_rules
                    else prefs["sync"][direction]
                )
                if not rule_engine.decide(act, direction, rules, dprefs).sync:
                    skipped += 1
            elif not reason.startswith("not on") and not reason.startswith("already on"):
                blocked[reason] += 1
        out[direction] = {
            "to_copy": missing - skipped,
            "skipped_by_rules": skipped,
            "cannot_copy": dict(blocked),
        }
    return out


def analyse(directions: list[str], apply_rules: bool) -> None:
    """Background: full all-time import of both platforms, merge, then compute the preview."""
    if not _lock.acquire(blocking=False):
        return
    try:
        _set(
            phase="importing",
            directions=directions,
            apply_rules=apply_rules,
            error=None,
            started_at=None,
            analysed_at=None,
            preview=None,
        )
        imported = {}
        with session_scope() as db, strava_client(db) as client:
            imported["strava"] = ingest.import_strava(db, client, all_time=True).as_dict()
        with session_scope() as db, komoot_client(db) as client:
            imported["komoot"] = ingest.import_komoot(db, client, all_time=True).as_dict()
        with session_scope() as db:
            merged = ingest.match_unlinked(db)
            counts = {
                "activities": db.scalar(select(func.count()).select_from(Activity)),
                "merged": merged,
            }
            preview = _preview(db, directions, apply_rules)
        _set(phase="ready", imported=imported, counts=counts, preview=preview, analysed_at=iso(utcnow()))
    except Exception as exc:  # noqa: BLE001
        logger.exception("full sync analysis failed")
        _set(phase="error", error=str(exc)[:500])
    finally:
        _lock.release()


def start(db: Session) -> dict[str, Any]:
    st = store.get_value(db, STATE_KEY) or {}
    if st.get("phase") != "ready":
        raise ValueError("run the analysis first")
    started = utcnow()
    directions = st.get("directions") or list(rule_engine.DIRECTION_TARGET)
    totals = {"queued": 0, "skipped": 0}
    prefs = store.get_preferences(db)
    for direction in directions:
        # temporarily treat the direction as enabled and ignore the start date for this one plan
        patched = {
            **prefs,
            "sync": {
                **prefs["sync"],
                "start_date": None,
                direction: {
                    **prefs["sync"][direction],
                    "enabled": True,
                    **({} if st.get("apply_rules", True) else {"default_action": "sync"}),
                },
            },
        }
        result = sync.plan(
            db,
            force=True,
            prefs_override=patched,
            directions=[direction],
            ignore_rules=not st.get("apply_rules", True),
            honour_lock=True,
        )
        totals["queued"] += result["queued"]
        totals["skipped"] += result["skipped"]
    store.set_value(db, STATE_KEY, {**st, "phase": "running", "started_at": iso(started), "planned": totals})
    return state(db)


def cancel(db: Session) -> dict[str, Any]:
    st = store.get_value(db, STATE_KEY) or {}
    removed = 0
    if st.get("started_at"):
        removed = db.execute(
            SyncJob.__table__.delete().where(
                SyncJob.status == "queued", SyncJob.created_at >= parse_iso(st["started_at"])
            )
        ).rowcount
    store.set_value(db, STATE_KEY, {"phase": "idle", "cancelled_jobs": removed})
    return {"phase": "idle", "cancelled_jobs": removed}

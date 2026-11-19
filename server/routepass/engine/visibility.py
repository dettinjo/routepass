"""Who can see an activity on each platform, in one vocabulary: public | friends | private.

Strava calls these everyone / followers_only / only_me, Komoot public / friends / private.
Copies RoutePass makes take the original's visibility, and when the original's visibility changes
later the copy follows. Two independent recordings of the same activity are never changed
automatically; the UI shows the mismatch and offers to align them.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from routepass.models import Activity, ProviderActivity

logger = logging.getLogger(__name__)

LEVELS = ("public", "friends", "private")
_FROM_STRAVA = {"everyone": "public", "followers_only": "friends", "only_me": "private"}
_TO_STRAVA = {v: k for k, v in _FROM_STRAVA.items()}
SYNCED_FROM = "_visibility_from_original"  # on a copy's raw: the original's level it was last aligned to


def level_of(rec: ProviderActivity | None) -> str | None:
    if rec is None or not rec.raw:
        return None
    raw = rec.raw
    if rec.provider == "strava":
        if raw.get("visibility") in _FROM_STRAVA:
            return _FROM_STRAVA[raw["visibility"]]
        if raw.get("private") is not None:
            return "private" if raw["private"] else "public"
        return None
    status = raw.get("status")
    return status if status in LEVELS else None


def to_strava(level: str) -> str:
    return _TO_STRAVA[level]


def _remember(rec: ProviderActivity, level: str, original: str | None = None) -> None:
    raw = dict(rec.raw or {})  # new dict so the JSON column is marked changed
    if rec.provider == "strava":
        raw["visibility"] = to_strava(level)
        raw["private"] = level == "private"
    else:
        raw["status"] = level
    if original is not None:
        raw[SYNCED_FROM] = original
    rec.raw = raw


def push(db: Session, rec: ProviderActivity, level: str) -> None:
    """Set visibility on the platform, then remember it locally."""
    from routepass.engine.clients import komoot_client, strava_client

    if level not in LEVELS:
        raise ValueError("visibility must be public, friends or private")
    if rec.provider == "strava":
        client = strava_client(db)
        try:
            client.update_activity(rec.external_id, visibility=to_strava(level), private=level == "private")
        finally:
            close = getattr(client, "close", None)
            if close:
                close()
    else:
        komoot_client(db).update_tour(rec.external_id, status=level)
    _remember(rec, level)


def summary(act: Activity) -> dict[str, Any]:
    live = [s for s in act.sources if not s.deleted]
    per = {s.provider: level_of(s) for s in live}
    known = {v for v in per.values() if v}
    return {"by_provider": per, "mismatch": len(known) > 1}


def set_for_activity(
    db: Session, act: Activity, level: str, providers: list[str] | None = None
) -> dict[str, Any]:
    errors: dict[str, str] = {}
    for rec in [s for s in act.sources if not s.deleted and (providers is None or s.provider in providers)]:
        try:
            push(db, rec, level)
            original = next(
                (o for o in act.sources if not o.deleted and not o.created_by_sync and o.id != rec.id), None
            )
            if rec.created_by_sync and original is not None:
                _remember(rec, level, original=level)
        except Exception as exc:  # noqa: BLE001
            errors[rec.provider] = str(exc)[:300]
    db.flush()
    return {**summary(act), "errors": errors}


def propagate(db: Session, limit: int = 20) -> int:
    """Copies follow their original: when the original's visibility differs from what the copy was
    last aligned to, the copy is updated. Returns how many copies changed."""
    changed = 0
    acts = db.scalars(
        select(Activity)
        .join(ProviderActivity, ProviderActivity.activity_id == Activity.id)
        .where(ProviderActivity.created_by_sync.is_(True), ProviderActivity.deleted.is_(False))
        .options(selectinload(Activity.sources))
        .execution_options(populate_existing=True)
    ).unique()
    for act in acts:
        live = [s for s in act.sources if not s.deleted]
        original = next((s for s in live if not s.created_by_sync), None)
        want = level_of(original)
        if want is None:
            continue
        for copy in (s for s in live if s.created_by_sync):
            aligned_to = (copy.raw or {}).get(SYNCED_FROM)
            if aligned_to == want or (aligned_to is None and level_of(copy) == want):
                if aligned_to is None:
                    _remember(copy, want, original=want)
                continue
            if changed >= limit:
                return changed
            try:
                push(db, copy, want)
                _remember(copy, want, original=want)
                changed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Could not align visibility of %s %s: %s", copy.provider, copy.external_id, exc
                )
    db.flush()
    return changed

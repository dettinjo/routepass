"""Photos (and Strava videos) of an activity, from Strava and Komoot.

Lists are fetched on demand and cached for a few hours; the images themselves are loaded by the
browser straight from the platforms' CDNs. Photos RoutePass copied from Komoot to Strava would show
twice, so the original record's photos come first and a copy's are only added when the original has
none."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from sqlalchemy.orm import Session

from routepass.models import Activity, ProviderActivity

logger = logging.getLogger(__name__)
TTL_S = 6 * 3600
_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}
_lock = threading.Lock()


def _fetch(db: Session, rec: ProviderActivity) -> list[dict[str, Any]]:
    from routepass.engine.clients import komoot_client, strava_client

    key = (rec.provider, rec.external_id)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
    if rec.provider == "komoot":
        photos = komoot_client(db).tour_photos(rec.external_id)
        items = [
            {**p, "thumb": p["url"].replace("width=2048&height=2048", "width=480&height=480")} for p in photos
        ]
    else:
        client = strava_client(db)
        try:
            items = client.activity_photos(rec.external_id)
        finally:
            close = getattr(client, "close", None)
            if close:
                close()
    items = [{**p, "provider": rec.provider} for p in items]
    with _lock:
        _cache[key] = (time.time(), items)
    return items


def activity_media(db: Session, act: Activity, refresh: bool = False) -> dict[str, Any]:
    live = sorted((s for s in act.sources if not s.deleted), key=lambda s: s.created_by_sync)
    if refresh:
        with _lock:
            for s in live:
                _cache.pop((s.provider, s.external_id), None)
    photos: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    counts: dict[str, int] = {}
    for rec in live:
        if rec.created_by_sync and photos:
            continue  # the original's photos already shown; the copy carries the same ones
        try:
            items = _fetch(db, rec)
        except Exception as exc:  # noqa: BLE001
            logger.info("Photos of %s %s unavailable: %s", rec.provider, rec.external_id, exc)
            errors[rec.provider] = str(exc)[:200]
            continue
        counts[rec.provider] = len(items)
        photos.extend(items)
    return {"photos": photos, "counts": counts, "errors": errors}

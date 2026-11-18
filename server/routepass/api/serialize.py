from __future__ import annotations

from typing import Any

from routepass.models import Activity, ProviderActivity, SyncJob, SyncRule, SyncRun
from routepass.providers import sports
from routepass.timeutil import iso


def provider_url(provider: str, external_id: str) -> str:
    if provider == "strava":
        return f"https://www.strava.com/activities/{external_id}"
    return f"https://www.komoot.com/tour/{external_id}"


def source(s: ProviderActivity) -> dict[str, Any]:
    return {
        "id": s.id,
        "provider": s.provider,
        "external_id": s.external_id,
        "url": provider_url(s.provider, s.external_id),
        "name": s.name,
        "sport": s.sport,
        "start_time": iso(s.start_time),
        "distance_m": s.distance_m,
        "created_by_sync": s.created_by_sync,
        "match_locked": s.match_locked,
        "deleted": s.deleted,
        "track_status": s.track_status,
        "visibility": s.raw.get("visibility") or s.raw.get("status"),
    }


def activity_row(a: Activity) -> dict[str, Any]:
    live = [s for s in a.sources if not s.deleted]
    return {
        "id": a.id,
        "name": a.name,
        "sport": a.sport,
        "sport_label": sports.label(a.sport),
        "family": a.family,
        "start_time": iso(a.start_time),
        "start_local": a.start_local.isoformat() if a.start_local else None,
        "distance_m": a.distance_m,
        "moving_time_s": a.moving_time_s,
        "elevation_gain_m": a.elevation_gain_m,
        "avg_speed_ms": a.avg_speed_ms,
        "avg_hr": a.avg_hr,
        "avg_power": a.avg_power,
        "load": a.load,
        "has_track": a.has_track,
        "trainer": a.trainer,
        "commute": a.commute,
        "polyline": a.polyline,
        "providers": sorted({s.provider for s in live}),
        "copies": sorted({s.provider for s in live if s.created_by_sync}),
        "sync_locked": a.sync_locked,
    }


ACTIVITY_DETAIL_FIELDS = [
    "description",
    "elapsed_time_s",
    "elevation_loss_m",
    "elevation_max_m",
    "max_speed_ms",
    "max_hr",
    "normalized_power",
    "max_power",
    "avg_cadence",
    "avg_temp",
    "calories",
    "work_kj",
    "load_method",
    "intensity",
    "start_lat",
    "start_lng",
    "end_lat",
    "end_lng",
    "timezone",
    "device",
    "gear",
    "track_provider",
]


def activity_detail(a: Activity) -> dict[str, Any]:
    out = activity_row(a)
    for f in ACTIVITY_DETAIL_FIELDS:
        out[f] = getattr(a, f)
    out["sources"] = [source(s) for s in a.sources]
    return out


def job(j: SyncJob, activity: Activity | None = None) -> dict[str, Any]:
    out = {
        "id": j.id,
        "activity_id": j.activity_id,
        "direction": j.direction,
        "source_provider": j.source_provider,
        "source_id": j.source_id,
        "target_provider": j.target_provider,
        "target_id": j.target_id,
        "target_url": provider_url(j.target_provider, j.target_id) if j.target_id else None,
        "status": j.status,
        "rule_id": j.rule_id,
        "plan": j.plan,
        "reason": j.reason,
        "error": j.error,
        "attempts": j.attempts,
        "next_attempt_at": iso(j.next_attempt_at),
        "created_at": iso(j.created_at),
        "updated_at": iso(j.updated_at),
    }
    if activity is not None:
        out["activity"] = {
            "name": activity.name,
            "sport": activity.sport,
            "start_time": iso(activity.start_time),
            "distance_m": activity.distance_m,
        }
    return out


def rule(r: SyncRule) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "direction": r.direction,
        "enabled": r.enabled,
        "priority": r.priority,
        "conditions": r.conditions,
        "actions": r.actions,
        "match_count": r.match_count,
        "last_matched_at": iso(r.last_matched_at),
        "created_at": iso(r.created_at),
        "updated_at": iso(r.updated_at),
    }


def run(r: SyncRun) -> dict[str, Any]:
    return {
        "id": r.id,
        "trigger": r.trigger,
        "status": r.status,
        "started_at": iso(r.started_at),
        "finished_at": iso(r.finished_at),
        "stats": r.stats,
        "log": r.log,
    }

from __future__ import annotations

import secrets
import threading
from datetime import date
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from routepass import auth, services, store
from routepass.analysis import insights
from routepass.analysis import track as trk
from routepass.api import serialize
from routepass.config import get_settings
from routepass.db import get_session
from routepass.engine import ingest, runner, sync
from routepass.engine.clients import (
    KOMOOT_ACCOUNT,
    KOMOOT_CREDENTIALS,
    STRAVA_APP,
    STRAVA_ATHLETE,
    STRAVA_TOKENS,
    STRAVA_WEB_SESSION,
    strava_app,
    strava_client,
)
from routepass.engine.rules import RuleError
from routepass.models import SyncRun, Track
from routepass.providers import komoot, sports, strava, strava_userscript
from routepass.providers.gpx import track_to_gpx
from routepass.timeutil import utcnow

Direction = Literal["strava_to_komoot", "komoot_to_strava"]


def require_token(request: Request) -> None:
    identity = auth.identify(request)
    if identity is None:
        raise HTTPException(401, "Sign in or send the API token", headers={"WWW-Authenticate": "Bearer"})
    request.state.identity = identity


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])
public = APIRouter(prefix="/api/v1")


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except services.NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, RuleError) as exc:
        raise HTTPException(422, str(exc)) from exc


def _filters(
    start: date | None = None,
    end: date | None = None,
    family: list[str] | None = Query(None),
    sport: list[str] | None = Query(None),
) -> insights.Filters:
    return insights.Filters(start=start, end=end, families=family or None, sports=sport or None)


# ── system ───────────────────────────────────────────────────────────────────


@public.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/status", tags=["system"])
def get_status(db: Session = Depends(get_session)) -> dict[str, Any]:
    return services.status(db, runner.is_running())


class RunRequest(BaseModel):
    full: bool = Field(False, description="Re-scan complete provider history (detects deletions)")
    wait: bool = Field(False, description="Block until the cycle finishes")


@router.post("/sync/run", tags=["sync"])
def run_sync(body: RunRequest = RunRequest()) -> dict[str, Any]:
    if runner.is_running():
        return {"status": "busy"}
    if body.wait:
        return runner.run_cycle("api", full=body.full)
    threading.Thread(target=runner.run_cycle, args=("api",), kwargs={"full": body.full}, daemon=True).start()
    return {"status": "started"}


@router.get("/sync/runs", tags=["sync"])
def list_runs(limit: int = 20, db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [serialize.run(r) for r in db.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(limit))]


@router.get("/sync/jobs", tags=["sync"])
def list_jobs(
    status: str | None = None, limit: int = 100, offset: int = 0, db: Session = Depends(get_session)
) -> dict[str, Any]:
    return services.list_jobs(db, status, limit, offset)


@router.post("/sync/jobs/{job_id}/retry", tags=["sync"])
def retry_job(job_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
    job = sync.retry(db, job_id)
    db.commit()
    if job is not None and job.status == "queued":
        threading.Thread(target=_run_jobs, args=([job.id],), daemon=True).start()
    return {"ok": True}


def _run_jobs(ids: list[int]) -> None:
    from routepass.db import session_scope

    with session_scope() as db:
        sync.run_jobs(db, job_ids=ids)


@router.delete("/sync/jobs/{job_id}", tags=["sync"])
def delete_job(job_id: int, db: Session = Depends(get_session)) -> dict[str, bool]:
    from routepass.models import SyncJob

    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if job.status == "done":
        raise HTTPException(422, "completed jobs are history and cannot be removed")
    db.delete(job)
    return {"ok": True}


@router.post("/sync/reevaluate", tags=["sync"])
def reevaluate(db: Session = Depends(get_session)) -> dict[str, int]:
    return services.reevaluate_skipped(db)


@router.get("/sync/preview", tags=["sync"])
def preview(
    direction: Direction, limit: int = 100, db: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    return sync.preview(db, direction, limit)


# ── rules ────────────────────────────────────────────────────────────────────


class RuleBody(BaseModel):
    name: str | None = None
    direction: Direction | None = None
    enabled: bool | None = None
    priority: int | None = None
    conditions: dict[str, Any] | None = None
    actions: dict[str, Any] | None = None


@router.get("/rules", tags=["rules"])
def list_rules(
    direction: Direction | None = None, db: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    return services.list_rules(db, direction)


@router.post("/rules", tags=["rules"], status_code=201)
def create_rule(body: RuleBody, db: Session = Depends(get_session)) -> dict[str, Any]:
    return _call(services.save_rule, db, body.model_dump(exclude_none=True))


@router.put("/rules/{rule_id}", tags=["rules"])
def update_rule(rule_id: int, body: RuleBody, db: Session = Depends(get_session)) -> dict[str, Any]:
    return _call(services.save_rule, db, body.model_dump(exclude_none=True), rule_id)


@router.delete("/rules/{rule_id}", tags=["rules"])
def delete_rule(rule_id: int, db: Session = Depends(get_session)) -> dict[str, bool]:
    _call(services.delete_rule, db, rule_id)
    return {"ok": True}


class ReorderBody(BaseModel):
    ids: list[int]


@router.post("/rules/reorder", tags=["rules"])
def reorder_rules(body: ReorderBody, db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return services.reorder_rules(db, body.ids)


@router.get("/meta/sports", tags=["rules"])
def sport_meta() -> dict[str, Any]:
    return {
        "strava": [
            {"key": s, "label": sports.label(s), "family": sports.family(s)}
            for s in sports.all_strava_sports()
        ],
        "komoot": [{"key": s, "label": sports.label(s)} for s in sports.all_komoot_sports()],
        "families": ["ride", "run", "walk", "winter", "water", "other"],
    }


# ── activities ───────────────────────────────────────────────────────────────


@router.get("/activities", tags=["activities"])
def list_activities(
    q: str | None = None,
    sport: list[str] | None = Query(None),
    family: list[str] | None = Query(None),
    start: date | None = None,
    end: date | None = None,
    presence: Literal["both", "strava_only", "komoot_only", "synced"] | None = None,
    min_km: float | None = None,
    max_km: float | None = None,
    sort: str = "date",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    return services.list_activities(
        db,
        q=q,
        sport=sport,
        family=family,
        start=start,
        end=end,
        presence=presence,
        min_km=min_km,
        max_km=max_km,
        sort=sort,
        order=order,
        page=page,
        per_page=per_page,
    )


class BulkSyncBody(BaseModel):
    activity_ids: list[int] = Field(..., max_length=200)
    direction: Direction


@router.post("/activities/bulk-sync", tags=["activities"])
def bulk_sync(body: BulkSyncBody, db: Session = Depends(get_session)) -> dict[str, Any]:
    result = _call(services.bulk_sync, db, body.activity_ids, body.direction)
    if result["job_ids"]:
        threading.Thread(target=_run_jobs, args=(result["job_ids"],), daemon=True).start()
    return result


class TripBody(BaseModel):
    activity_ids: list[int] = Field(..., min_length=2, max_length=100)


@router.post("/activities/trip", tags=["activities"])
def trip(body: TripBody, db: Session = Depends(get_session)) -> dict[str, Any]:
    out = _call(services.trip_analysis, db, body.activity_ids)
    return out


@router.get("/activities/duplicates", tags=["activities"])
def duplicates(
    limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    """Activities that look like the same recording but were not merged automatically."""
    return services.duplicate_candidates(db, limit)


class DismissBody(BaseModel):
    other_id: int


@router.post("/activities/{activity_id}/dismiss-duplicate", tags=["activities"])
def dismiss_duplicate(
    activity_id: int, body: DismissBody, db: Session = Depends(get_session)
) -> dict[str, bool]:
    return services.dismiss_duplicate(db, activity_id, body.other_id)


@router.get("/activities/export.csv", tags=["activities"])
def export_csv(
    q: str | None = None,
    sport: list[str] | None = Query(None),
    family: list[str] | None = Query(None),
    start: date | None = None,
    end: date | None = None,
    presence: Literal["both", "strava_only", "komoot_only", "synced"] | None = None,
    db: Session = Depends(get_session),
) -> Response:
    text = services.export_activities_csv(
        db, q=q, sport=sport, family=family, start=start, end=end, presence=presence
    )
    return Response(
        text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="routepass-activities-{date.today()}.csv"'},
    )


@router.get("/activities/{activity_id}", tags=["activities"])
def activity_detail(activity_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
    return _call(services.activity_detail, db, activity_id)


@router.get("/activities/{activity_id}/track", tags=["activities"])
def activity_track(activity_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
    return _call(services.activity_track, db, activity_id)


@router.get("/activities/{activity_id}/similar", tags=["activities"])
def similar(activity_id: int, db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return _call(services.similar_activities, db, activity_id)


@router.get("/activities/{activity_id}/gpx", tags=["activities"])
def activity_gpx(activity_id: int, db: Session = Depends(get_session)) -> Response:
    act = _call(services.get_activity, db, activity_id)
    track = db.get(Track, act.id)
    if track is None:
        raise HTTPException(404, "no track stored for this activity")
    gpx = track_to_gpx(trk.NormalizedTrack.unpack(track.data), act.name, act.sport, act.start_time)
    filename = f"{act.start_time:%Y-%m-%d}-{act.id}.gpx"
    return Response(
        gpx,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ActivityPatch(BaseModel):
    sync_locked: bool


@router.patch("/activities/{activity_id}", tags=["activities"])
def patch_activity(
    activity_id: int, body: ActivityPatch, db: Session = Depends(get_session)
) -> dict[str, Any]:
    return _call(services.set_sync_lock, db, activity_id, body.sync_locked)


class SyncBody(BaseModel):
    direction: Direction


@router.post("/activities/{activity_id}/sync", tags=["activities"])
def sync_activity(activity_id: int, body: SyncBody, db: Session = Depends(get_session)) -> dict[str, Any]:
    return _call(services.sync_activity, db, activity_id, body.direction)


class UnlinkBody(BaseModel):
    source_id: int


@router.post("/activities/{activity_id}/unlink", tags=["activities"])
def unlink(activity_id: int, body: UnlinkBody, db: Session = Depends(get_session)) -> dict[str, Any]:
    return _call(services.unlink_source, db, activity_id, body.source_id)


class MergeBody(BaseModel):
    other_id: int


@router.post("/activities/{activity_id}/merge", tags=["activities"])
def merge(activity_id: int, body: MergeBody, db: Session = Depends(get_session)) -> dict[str, Any]:
    return _call(services.merge_activities, db, activity_id, body.other_id)


@router.post("/activities/{activity_id}/refetch-track", tags=["activities"])
def refetch(activity_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
    result = _call(services.refetch_track, db, activity_id)
    db.commit()
    with_session_fetch = threading.Thread(target=_fetch_tracks, daemon=True)
    with_session_fetch.start()
    return result


def _fetch_tracks() -> None:
    from routepass.db import session_scope

    with session_scope() as db:
        ingest.fetch_tracks(db, budget_s=60, limit=20)


# ── insights ─────────────────────────────────────────────────────────────────


@router.get("/insights/dashboard", tags=["insights"])
def dashboard(family: list[str] | None = Query(None), db: Session = Depends(get_session)) -> dict[str, Any]:
    today = date.today()
    fam = family or None
    return {
        "periods": insights.period_comparison(db, today, fam),
        "load": insights.training_load(db, today, days=90, families=fam),
        "weekly": insights.timeseries(
            db, insights.Filters(start=date(today.year - 1, today.month, 1), end=today, families=fam), "week"
        ),
        "streaks": insights.habits(db, insights.Filters(families=fam))["streaks"],
        "recent": services.list_activities(db, family=fam, per_page=8)["items"],
        "coverage": insights.coverage(db),
    }


@router.get("/insights/totals", tags=["insights"])
def totals(f: insights.Filters = Depends(_filters), db: Session = Depends(get_session)) -> dict[str, Any]:
    return insights.totals(db, f)


@router.get("/insights/timeseries", tags=["insights"])
def timeseries(
    grain: Literal["day", "week", "month", "year"] = "week",
    group: Literal["family", "sport", "all"] = "family",
    f: insights.Filters = Depends(_filters),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    return insights.timeseries(db, f, grain, group)


@router.get("/insights/calendar", tags=["insights"])
def calendar(
    f: insights.Filters = Depends(_filters), db: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    return insights.calendar(db, f)


@router.get("/insights/cumulative", tags=["insights"])
def cumulative(
    metric: Literal["distance_m", "moving_time_s", "elevation_m", "count"] = "distance_m",
    f: insights.Filters = Depends(_filters),
    db: Session = Depends(get_session),
) -> dict[str, list]:
    return insights.cumulative_by_year(db, f, metric)


@router.get("/insights/load", tags=["insights"])
def load(
    days: int = Query(365, ge=14, le=3650),
    end: date | None = None,
    family: list[str] | None = Query(None),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    return insights.training_load(db, end or date.today(), days, family or None)


@router.get("/insights/records", tags=["insights"])
def records(f: insights.Filters = Depends(_filters), db: Session = Depends(get_session)) -> dict[str, Any]:
    return insights.records(db, f)


@router.get("/insights/power-curve", tags=["insights"])
def power_curve(
    f: insights.Filters = Depends(_filters), db: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    return insights.power_curve(db, f)


@router.get("/insights/habits", tags=["insights"])
def habits(f: insights.Filters = Depends(_filters), db: Session = Depends(get_session)) -> dict[str, Any]:
    return insights.habits(db, f)


@router.get("/insights/eddington", tags=["insights"])
def eddington(
    unit: Literal["km", "mi"] = "km",
    f: insights.Filters = Depends(_filters),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    return insights.eddington(db, f, 1.0 if unit == "km" else 1.609344)


@router.get("/insights/heatmap", tags=["insights"])
def heatmap(
    f: insights.Filters = Depends(_filters), db: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    return insights.heatmap(db, f)


@router.get("/insights/tiles", tags=["insights"])
def tiles(f: insights.Filters = Depends(_filters), db: Session = Depends(get_session)) -> dict[str, Any]:
    """Explorer tiles (zoom 14): total, max square, max cluster, new tiles per year."""
    return insights.explorer_tiles(db, f)


@router.get("/insights/zones", tags=["insights"])
def zones(
    grain: Literal["week", "month", "year"] = "month",
    f: insights.Filters = Depends(_filters),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Time in heart-rate and power zones plus polarisation (low / threshold / high)."""
    return insights.zone_distribution(db, f, grain)


@router.get("/insights/efficiency", tags=["insights"])
def efficiency(
    f: insights.Filters = Depends(_filters), db: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    """Aerobic efficiency factor (speed or power per heartbeat) and decoupling per activity."""
    return insights.efficiency_trend(db, f)


@router.get("/insights/goals", tags=["insights"])
def goals(family: list[str] | None = Query(None), db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return insights.goals_progress(db, date.today(), store.get_preferences(db), family or None)


@router.get("/insights/gear", tags=["insights"])
def gear(f: insights.Filters = Depends(_filters), db: Session = Depends(get_session)) -> dict[str, Any]:
    return insights.gear_stats(db, f, store.get_preferences(db))


@router.get("/insights/coverage", tags=["insights"])
def coverage(db: Session = Depends(get_session)) -> dict[str, Any]:
    return insights.coverage(db)


# ── settings ─────────────────────────────────────────────────────────────────


@router.get("/settings", tags=["settings"])
def get_preferences(db: Session = Depends(get_session)) -> dict[str, Any]:
    return store.get_preferences(db)


@router.patch("/settings", tags=["settings"])
def patch_preferences(patch: dict[str, Any], db: Session = Depends(get_session)) -> dict[str, Any]:
    if "poll_interval_minutes" in patch:
        value = patch["poll_interval_minutes"]
        if value is not None and value not in (0, *runner.POLL_CHOICES_MIN):
            raise HTTPException(
                422,
                f"poll_interval_minutes must be 0 (manual only) or one of {list(runner.POLL_CHOICES_MIN)}",
            )
    before = store.get_preferences(db)
    prefs = store.update_preferences(db, patch)
    if prefs["profile"] != before["profile"]:
        db.commit()
        threading.Thread(target=_recompute, daemon=True).start()
    if prefs["matching"] != before["matching"]:
        ingest.match_unlinked(db)
    if prefs.get("poll_interval_minutes") != before.get("poll_interval_minutes") or prefs["sync"].get(
        "delay_minutes"
    ) != before["sync"].get("delay_minutes"):
        runner.reschedule()
    return prefs


def _recompute() -> None:
    from routepass.db import session_scope

    with session_scope() as db:
        ingest.recompute_tracks(db)


@router.post("/settings/recompute", tags=["settings"])
def recompute() -> dict[str, str]:
    threading.Thread(target=_recompute, daemon=True).start()
    return {"status": "started"}


# ── connections ──────────────────────────────────────────────────────────────


class StravaAppBody(BaseModel):
    client_id: str
    client_secret: str


@router.put("/connections/strava/app", tags=["connections"])
def set_strava_app(body: StravaAppBody, db: Session = Depends(get_session)) -> dict[str, bool]:
    store.set_secret(db, STRAVA_APP, body.model_dump())
    return {"ok": True}


def _redirect_uri() -> str:
    settings = get_settings()
    base = settings.public_url or settings.base_url
    return settings.strava_redirect_uri or base.rstrip("/") + "/api/v1/connections/strava/callback"


def _ui(path: str) -> str:
    # The callback may arrive on the public API host; the UI lives on base_url.
    return get_settings().base_url.rstrip("/") + path


@router.get("/connections/strava/authorize", tags=["connections"])
def strava_authorize(db: Session = Depends(get_session)) -> dict[str, str]:
    client_id, client_secret = strava_app(db)
    if not client_id or not client_secret:
        raise HTTPException(422, "Set the Strava API application (client id + secret) first")
    state = secrets.token_urlsafe(16)
    store.set_value(db, "strava.oauth_state", state)
    return {"url": strava.authorize_url(client_id, _redirect_uri(), state), "redirect_uri": _redirect_uri()}


def _finish_strava(db: Session, code: str) -> dict[str, Any]:
    client_id, client_secret = strava_app(db)
    try:
        data = strava.exchange_code(client_id, client_secret, code)
    except strava.StravaAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    store.set_secret(
        db,
        STRAVA_TOKENS,
        {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_at": data["expires_at"],
            "scope": data.get("scope"),
        },
    )
    athlete = data.get("athlete") or {}
    store.set_value(
        db,
        STRAVA_ATHLETE,
        {
            "id": athlete.get("id"),
            "name": f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip(),
            "profile": athlete.get("profile_medium"),
            "connected_at": utcnow().isoformat(),
        },
    )
    runner.trigger_soon()
    return {"ok": True}


@public.get("/connections/strava/callback", tags=["connections"], include_in_schema=False)
def strava_callback(
    state: str = "", code: str = "", error: str = "", db: Session = Depends(get_session)
) -> RedirectResponse:
    expected = store.get_value(db, "strava.oauth_state")
    if error or not code or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse(_ui(f"/settings?strava=error&reason={error or 'state'}"))
    store.delete_value(db, "strava.oauth_state")
    _finish_strava(db, code)
    return RedirectResponse(_ui("/settings?strava=connected"))


class CodeBody(BaseModel):
    code: str


@router.post("/connections/strava/code", tags=["connections"])
def strava_code(body: CodeBody, db: Session = Depends(get_session)) -> dict[str, Any]:
    """Finish OAuth by pasting the `code` from the redirect URL (when the redirect can't reach this host)."""
    return _finish_strava(db, body.code.strip())


class StravaSessionBody(BaseModel):
    cookie: str
    remember_token: str = ""


def _save_strava_web_session(db: Session, cookies: dict[str, str], athlete: dict[str, Any]) -> None:
    store.set_secret(db, STRAVA_WEB_SESSION, {"cookies": cookies})
    existing = store.get_value(db, STRAVA_ATHLETE) or {}
    store.set_value(
        db,
        STRAVA_ATHLETE,
        {
            **existing,
            "id": athlete.get("id") or existing.get("id"),
            "name": athlete.get("name")
            or f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip(),
            "connected_at": existing.get("connected_at") or utcnow().isoformat(),
            "mode": "web",
            "has_remember_token": "strava_remember_token" in cookies,
        },
    )
    store.delete_value(db, "strava.error")
    runner.trigger_soon()


@router.put("/connections/strava/session", tags=["connections"])
def strava_session_connect(body: StravaSessionBody, db: Session = Depends(get_session)) -> dict[str, Any]:
    """Connect Strava using a browser session cookie (`_strava4_session` / `strava_remember_token`)."""
    try:
        cookies = strava.parse_web_cookies(body.cookie, body.remember_token)
        with strava.StravaWebClient(cookies) as client:
            athlete = client.athlete()
            cookies = dict(client.cookies)
    except strava.StravaAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except strava.StravaError as exc:
        raise HTTPException(502, str(exc)) from exc
    _save_strava_web_session(db, cookies, athlete)
    return {
        "ok": True,
        "athlete": {"id": athlete.get("id"), "name": athlete.get("name") or athlete.get("firstname")},
        "has_remember_token": "strava_remember_token" in cookies,
    }


class StravaHandoffBody(BaseModel):
    token: str
    cookies: dict[str, str] | str


def _public_ui_origin(request: Request) -> str:
    """Resolve the HTTPS UI origin behind reverse proxies (e.g. tailscale serve)."""
    configured = get_settings().base_url.rstrip("/")
    if configured and configured not in ("http://localhost:8000", "http://127.0.0.1:8000"):
        return configured
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        return f"{proto}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")


@router.get("/connections/strava/userscript.user.js", tags=["connections"])
def strava_userscript_download(request: Request) -> Response:
    """Serve a personalized 1-click Tampermonkey/Userscript that auto-syncs Strava cookies."""
    origin = _public_ui_origin(request)
    token = strava_userscript.issue_handoff_token()
    script = strava_userscript.render_userscript(origin, token)
    return Response(
        content=script,
        media_type="application/javascript; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="routepass-strava.user.js"',
            "Cache-Control": "no-store",
        },
    )


@public.post("/connections/strava/session/handoff", tags=["connections"])
def strava_session_handoff(body: StravaHandoffBody, db: Session = Depends(get_session)) -> dict[str, Any]:
    """Accept Strava session cookies from the installed userscript using its scoped HMAC token."""
    if not strava_userscript.verify_handoff_token(body.token):
        raise HTTPException(
            401, "Invalid or expired Strava handoff token — reinstall the userscript in Settings"
        )
    try:
        cookies = strava.parse_web_cookies(body.cookies)
        with strava.StravaWebClient(cookies) as client:
            athlete = client.athlete()
            cookies = dict(client.cookies)
    except strava.StravaAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except strava.StravaError as exc:
        raise HTTPException(502, str(exc)) from exc
    _save_strava_web_session(db, cookies, athlete)
    return {
        "ok": True,
        "athlete": {"id": athlete.get("id"), "name": athlete.get("name") or athlete.get("firstname")},
        "has_remember_token": "strava_remember_token" in cookies,
    }


@router.delete("/connections/strava/session", tags=["connections"])
def strava_session_disconnect(db: Session = Depends(get_session)) -> dict[str, bool]:
    store.delete_value(db, STRAVA_WEB_SESSION)
    if store.get_value(db, STRAVA_TOKENS) is None:
        store.delete_value(db, STRAVA_ATHLETE)
    return {"ok": True}


@router.delete("/connections/strava", tags=["connections"])
def strava_disconnect(db: Session = Depends(get_session)) -> dict[str, bool]:
    store.delete_value(db, STRAVA_TOKENS)
    store.delete_value(db, STRAVA_WEB_SESSION)
    store.delete_value(db, STRAVA_ATHLETE)
    store.delete_value(db, "strava.error")
    return {"ok": True}


@router.get("/connections/strava/check", tags=["connections"])
def strava_check(db: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        with strava_client(db) as client:
            athlete = client.athlete()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "athlete": {"id": athlete.get("id"), "name": athlete.get("firstname")}}


class KomootBody(BaseModel):
    email: str
    password: str


@router.put("/connections/komoot", tags=["connections"])
def komoot_connect(body: KomootBody, db: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        account = komoot.login(body.email.strip(), body.password)
    except komoot.KomootAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except komoot.KomootError as exc:
        raise HTTPException(502, str(exc)) from exc
    store.set_secret(
        db, KOMOOT_CREDENTIALS, {"email": body.email.strip(), "password": body.password, **account}
    )
    store.set_value(
        db, KOMOOT_ACCOUNT, {**account, "email": body.email.strip(), "connected_at": utcnow().isoformat()}
    )
    runner.trigger_soon()
    return {"ok": True, "account": account}


@router.delete("/connections/komoot", tags=["connections"])
def komoot_disconnect(db: Session = Depends(get_session)) -> dict[str, bool]:
    store.delete_value(db, KOMOOT_CREDENTIALS)
    store.delete_value(db, KOMOOT_ACCOUNT)
    return {"ok": True}


# ── Strava webhooks ──────────────────────────────────────────────────────────


@public.get("/webhooks/strava", tags=["webhooks"])
def strava_webhook_verify(request: Request) -> dict[str, str]:
    q = request.query_params
    expected = get_settings().strava_webhook_verify_token
    if not expected or not secrets.compare_digest(q.get("hub.verify_token", ""), expected):
        raise HTTPException(403, "verify token mismatch")
    return {"hub.challenge": q.get("hub.challenge", "")}


@public.post("/webhooks/strava", tags=["webhooks"])
def strava_webhook_event(event: dict[str, Any], db: Session = Depends(get_session)) -> dict[str, Any]:
    return services.handle_strava_event(db, event)


@router.get("/connections/strava/webhook", tags=["connections"])
def strava_webhook_status(db: Session = Depends(get_session)) -> dict[str, Any]:
    return _call(_provider(services.strava_webhook_status), db)


@router.put("/connections/strava/webhook", tags=["connections"])
def strava_webhook_enable(db: Session = Depends(get_session)) -> dict[str, Any]:
    return _call(_provider(services.strava_webhook_enable), db)


@router.delete("/connections/strava/webhook", tags=["connections"])
def strava_webhook_disable(db: Session = Depends(get_session)) -> dict[str, Any]:
    return _call(_provider(services.strava_webhook_disable), db)


def _provider(fn):
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except strava.StravaError as exc:
            raise HTTPException(502, str(exc)) from exc

    return wrapped


# ── all-time sync ────────────────────────────────────────────────────────────


class FullSyncBody(BaseModel):
    directions: list[Direction] = ["komoot_to_strava", "strava_to_komoot"]
    apply_rules: bool = Field(True, description="Rules still decide; False copies everything that is missing")


@router.get("/sync/full-history", tags=["sync"])
def full_history_state(db: Session = Depends(get_session)) -> dict[str, Any]:
    from routepass.engine import fullsync

    return fullsync.state(db)


@router.post("/sync/full-history/analyse", tags=["sync"])
def full_history_analyse(body: FullSyncBody = FullSyncBody()) -> dict[str, str]:
    """Import the complete history of both platforms, merge duplicates and preview what would be copied."""
    from routepass.engine import fullsync

    threading.Thread(
        target=fullsync.analyse, args=(list(body.directions), body.apply_rules), daemon=True
    ).start()
    return {"phase": "importing"}


@router.post("/sync/full-history/start", tags=["sync"])
def full_history_start(db: Session = Depends(get_session)) -> dict[str, Any]:
    """Queue every missing copy found by the analysis; the scheduler works the queue off."""
    from routepass.engine import fullsync

    result = _call(fullsync.start, db)
    db.commit()
    runner.trigger_soon()
    return result


@router.post("/sync/full-history/cancel", tags=["sync"])
def full_history_cancel(db: Session = Depends(get_session)) -> dict[str, Any]:
    from routepass.engine import fullsync

    return fullsync.cancel(db)


# ── sign-in ──────────────────────────────────────────────────────────────────


@public.get("/auth/me", tags=["auth"])
def auth_me(request: Request) -> dict[str, Any]:
    identity = auth.identify(request)
    return {
        "authenticated": identity is not None,
        "email": identity.email if identity else None,
        "name": identity.name if identity else None,
        "picture": identity.picture if identity else None,
        "method": identity.method if identity else None,
        "methods": {
            "google": auth.google_configured(),
            "tailscale": get_settings().trust_tailscale_headers,
            "token": bool(get_settings().api_token),
        },
    }


@public.get("/auth/google/start", tags=["auth"], include_in_schema=False)
def google_start() -> RedirectResponse:
    if not auth.google_configured():
        raise HTTPException(404, "Google sign-in is not configured")
    return RedirectResponse(auth.google_start_url())


@public.get("/auth/google/callback", tags=["auth"], include_in_schema=False)
def google_callback(code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    """Arrives on the public URL; hands the identity to the private UI host with a one-time code."""
    if error or not code:
        return RedirectResponse(_ui(f"/login?error={error or 'cancelled'}"))
    try:
        identity = auth.google_finish(code, state)
    except auth.LoginError as exc:
        from urllib.parse import quote

        return RedirectResponse(_ui(f"/login?error={quote(str(exc))}"))
    return RedirectResponse(_ui(f"/api/v1/auth/complete?code={auth.handoff_code(identity)}"))


@public.get("/auth/complete", tags=["auth"], include_in_schema=False)
def auth_complete(request: Request, code: str = "") -> RedirectResponse:
    if auth.is_public_listener(request.scope):
        raise HTTPException(404)
    identity = auth.redeem_handoff(code)
    if identity is None:
        return RedirectResponse("/login?error=The%20sign-in%20link%20expired")
    resp = RedirectResponse("/")
    resp.set_cookie(auth.SESSION_COOKIE, auth.session_cookie(identity), **auth.cookie_kwargs())
    return resp


class TokenLogin(BaseModel):
    token: str


@public.post("/auth/token-login", tags=["auth"])
def token_login(body: TokenLogin, request: Request) -> Response:
    from routepass.security import token_ok

    if (
        auth.is_public_listener(request.scope)
        or not get_settings().api_token
        or not token_ok(body.token.strip())
    ):
        raise HTTPException(401, "Wrong access token")
    resp = Response('{"ok":true}', media_type="application/json")
    resp.set_cookie(
        auth.SESSION_COOKIE,
        auth.session_cookie(auth.Identity(email=next(iter(auth.allowed_emails()), None), method="token")),
        **auth.cookie_kwargs(),
    )
    return resp


@public.post("/auth/logout", tags=["auth"])
def logout() -> Response:
    resp = Response('{"ok":true}', media_type="application/json")
    resp.delete_cookie(auth.SESSION_COOKIE, path="/")
    return resp


# ── Strava data export (archive) ─────────────────────────────────────────────


@router.get("/import/strava-archive", tags=["import"])
def strava_archive_state(db: Session = Depends(get_session)) -> dict[str, Any]:
    from routepass.engine import strava_archive

    return {
        **strava_archive.state(db),
        "available": sorted(p.name for p in strava_archive.archive_dir().glob("*.zip")),
    }


@router.post("/import/strava-archive", tags=["import"])
async def strava_archive_upload(request: Request) -> dict[str, Any]:
    """Upload Strava's 'Download your account' zip as the raw request body (streamed to disk), then import."""
    from routepass.engine import strava_archive

    target = strava_archive.archive_dir() / f"strava-export-{utcnow():%Y%m%d-%H%M%S}.zip"
    size = 0
    with target.open("wb") as fh:
        async for chunk in request.stream():
            size += len(chunk)
            fh.write(chunk)
    import zipfile

    if size == 0 or not zipfile.is_zipfile(target):
        target.unlink(missing_ok=True)
        raise HTTPException(
            422, "That is not a zip file — upload the archive Strava e-mailed you, unchanged."
        )
    strava_archive.start(target)
    return {"phase": "queued", "file": target.name, "bytes": size}


class ArchiveFile(BaseModel):
    file: str = Field(..., description="Name of a zip in the data directory's imports/ folder")


@router.post("/import/strava-archive/file", tags=["import"])
def strava_archive_from_file(body: ArchiveFile) -> dict[str, Any]:
    from routepass.engine import strava_archive

    path = strava_archive.archive_dir() / Path(body.file).name
    if not path.is_file():
        raise HTTPException(404, f"{path.name} not found in imports/")
    strava_archive.start(path)
    return {"phase": "queued", "file": path.name}

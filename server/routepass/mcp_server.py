"""MCP server: the same operations as the REST API, as tools for AI assistants."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from routepass import services, store
from routepass.analysis import insights, trail
from routepass.db import session_scope
from routepass.engine import runner, sync

Direction = Literal["strava_to_komoot", "komoot_to_strava"]
Family = Literal["ride", "run", "walk", "winter", "water", "other"]

mcp = MCPServer(
    name="RoutePass",
    instructions=(
        "RoutePass keeps one deduplicated activity history built from Strava and Komoot and copies "
        "activities between them according to sync rules. Every activity appears once even if it exists "
        "on both platforms (see `providers`). Distances are metres, durations seconds, speeds m/s, "
        "dates ISO 8601. Sports use Strava sport_type names (Ride, Run, Hike, EBikeRide…); families group "
        "them (ride, run, walk, winter, water, other). Training load is on the TSS scale. "
        "For 50k / ultra trail-running coaching, start with `get_trail_training_brief` to inspect race "
        "countdown, training phase, weekly distance/vertical/effort-km, back-to-back long runs, ACWR "
        "injury risk, long-run aerobic durability, climbing VAM, shoe mileage, and coaching flags; use "
        "`analyze_trail_activity` for deep dives and `plan_trail_race_gpx` for GPX race pacing & fueling."
    ),
)


def _f(start: str | None, end: str | None, families: list[Family] | None, sports: list[str] | None):
    return insights.Filters(
        start=date.fromisoformat(start) if start else None,
        end=date.fromisoformat(end) if end else None,
        families=list(families) if families else None,
        sports=sports or None,
    )


# ── overview ─────────────────────────────────────────────────────────────────


@mcp.tool()
def get_status() -> dict[str, Any]:
    """Connection state, last sync run, job counts, dedup coverage and Strava rate-limit usage."""
    with session_scope() as db:
        return services.status(db, runner.is_running())


@mcp.tool()
def run_sync(full: bool = False) -> dict[str, Any]:
    """Run a sync cycle now (import both providers, dedupe, apply rules, upload, fetch tracks) and wait
    for it. full=True re-reads the complete history and detects deleted activities."""
    return runner.run_cycle("mcp", full=full)


# ── activities ───────────────────────────────────────────────────────────────


@mcp.tool()
def list_activities(
    query: str | None = None,
    start: str | None = None,
    end: str | None = None,
    families: list[Family] | None = None,
    sports: list[str] | None = None,
    presence: Literal["both", "strava_only", "komoot_only", "synced"] | None = None,
    min_km: float | None = None,
    max_km: float | None = None,
    sort: Literal[
        "date", "distance", "duration", "elevation", "speed", "load", "hr", "power", "name"
    ] = "date",
    order: Literal["asc", "desc"] = "desc",
    page: int = 1,
    per_page: int = 25,
) -> dict[str, Any]:
    """Search the deduplicated activity list. start/end are YYYY-MM-DD (end inclusive).
    presence filters by which platforms hold the activity."""
    with session_scope() as db:
        result = services.list_activities(
            db,
            q=query,
            start=date.fromisoformat(start) if start else None,
            end=date.fromisoformat(end) if end else None,
            family=list(families) if families else None,
            sport=sports,
            presence=presence,
            min_km=min_km,
            max_km=max_km,
            sort=sort,
            order=order,
            page=page,
            per_page=min(per_page, 100),
        )
    for item in result["items"]:
        item.pop("polyline", None)
    return result


@mcp.tool()
def get_activity(activity_id: int) -> dict[str, Any]:
    """Full detail of one activity: metrics, provider records (Strava/Komoot links), sync history,
    and track analysis (HR/power zones, splits, climbs, best efforts, decoupling)."""
    with session_scope() as db:
        out = services.activity_detail(db, activity_id)
    out.pop("polyline", None)
    return out


@mcp.tool()
def get_activity_streams(activity_id: int, max_points: int = 200) -> dict[str, Any]:
    """Downsampled recording: per point t (s), d (m), ele, hr, pw (W), cad, v (m/s), temp, lat, lon."""
    with session_scope() as db:
        data = services.activity_track(db, activity_id)
    pts = data["points"]
    if len(pts) > max_points:
        step = len(pts) / max_points
        pts = [pts[int(i * step)] for i in range(max_points)]
    return {**data, "points": pts}


@mcp.tool()
def find_similar_activities(activity_id: int) -> list[dict[str, Any]]:
    """Other activities of the same family with similar distance starting nearby (repeats of a route)."""
    with session_scope() as db:
        rows = services.similar_activities(db, activity_id)
    for r in rows:
        r.pop("polyline", None)
    return rows


@mcp.tool()
def sync_activity(activity_id: int, direction: Direction) -> dict[str, Any]:
    """Copy one activity to the other platform now (applies matching rules, ignores start date)."""
    with session_scope() as db:
        return services.sync_activity(db, activity_id, direction)


@mcp.tool()
def set_activity_sync_lock(activity_id: int, locked: bool) -> dict[str, Any]:
    """Lock an activity so automatic sync never copies it (or unlock it)."""
    with session_scope() as db:
        return services.set_sync_lock(db, activity_id, locked)


@mcp.tool()
def merge_activities(activity_id: int, duplicate_id: int) -> dict[str, Any]:
    """Merge duplicate_id into activity_id when auto-matching missed that they are the same activity."""
    with session_scope() as db:
        return services.merge_activities(db, activity_id, duplicate_id)


@mcp.tool()
def unlink_activity_source(activity_id: int, source_id: int) -> dict[str, Any]:
    """Split a wrongly matched provider record (source id from get_activity) into its own activity."""
    with session_scope() as db:
        return services.unlink_source(db, activity_id, source_id)


# ── insights ─────────────────────────────────────────────────────────────────


@mcp.tool()
def get_totals(
    start: str | None = None,
    end: str | None = None,
    families: list[Family] | None = None,
    sports: list[str] | None = None,
) -> dict[str, Any]:
    """Totals (count, distance, moving time, elevation, load, active days) overall, per family and per sport."""
    with session_scope() as db:
        return insights.totals(db, _f(start, end, families, sports))


@mcp.tool()
def compare_periods(families: list[Family] | None = None) -> dict[str, Any]:
    """This week, month and year to date compared with the same span of the previous period."""
    with session_scope() as db:
        return insights.period_comparison(db, date.today(), list(families) if families else None)


@mcp.tool()
def get_timeseries(
    grain: Literal["day", "week", "month", "year"] = "month",
    group: Literal["family", "sport", "all"] = "family",
    start: str | None = None,
    end: str | None = None,
    families: list[Family] | None = None,
    sports: list[str] | None = None,
) -> dict[str, Any]:
    """Volume per day/week/month/year, split by family or sport."""
    with session_scope() as db:
        return insights.timeseries(db, _f(start, end, families, sports), grain, group)


@mcp.tool()
def get_training_load(days: int = 90, families: list[Family] | None = None) -> dict[str, Any]:
    """Daily fitness (CTL, 42-day), fatigue (ATL, 7-day), form (TSB) and load for the last `days` days."""
    with session_scope() as db:
        return insights.training_load(db, date.today(), days, list(families) if families else None)


@mcp.tool()
def get_records(
    start: str | None = None,
    end: str | None = None,
    families: list[Family] | None = None,
) -> dict[str, Any]:
    """Personal records per family: longest, most climbing, fastest, best times per distance, biggest climb."""
    with session_scope() as db:
        return insights.records(db, _f(start, end, families, None))


@mcp.tool()
def get_power_curve(start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
    """Best mean power for 5 s … 2 h across all activities in the range."""
    with session_scope() as db:
        return insights.power_curve(db, _f(start, end, None, None))


@mcp.tool()
def get_habits(
    start: str | None = None, end: str | None = None, families: list[Family] | None = None
) -> dict[str, Any]:
    """When and how you train: weekday×hour grid, per-weekday totals, distance histogram, streaks."""
    with session_scope() as db:
        return insights.habits(db, _f(start, end, families, None))


@mcp.tool()
def get_eddington(families: list[Family] | None = None, unit: Literal["km", "mi"] = "km") -> dict[str, Any]:
    """Eddington number: the largest E with E days of at least E km (or miles)."""
    with session_scope() as db:
        return insights.eddington(db, _f(None, None, families, None), 1.0 if unit == "km" else 1.609344)


@mcp.tool()
def get_year_over_year(
    metric: Literal["distance_m", "moving_time_s", "elevation_m", "count"] = "distance_m",
    families: list[Family] | None = None,
) -> dict[str, Any]:
    """Cumulative metric per year, sampled at month ends (for year-over-year comparison)."""
    with session_scope() as db:
        data = insights.cumulative_by_year(db, _f(None, None, families, None), metric)
    month_end_doy = [31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365]
    return {
        year: [series[min(d, len(series)) - 1] for d in month_end_doy if d <= len(series)]
        for year, series in data.items()
    }


# ── sync configuration ───────────────────────────────────────────────────────


@mcp.tool()
def get_settings() -> dict[str, Any]:
    """Sync directions (enabled, default action, defaults), start date, delay, matching tolerances,
    athlete profile (ftp, hr_max, hr_rest, weight_kg) and import window."""
    with session_scope() as db:
        return store.get_preferences(db)


@mcp.tool()
def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge a partial settings object, e.g. {"sync": {"komoot_to_strava": {"enabled": true}}}
    or {"profile": {"ftp": 260}}. Returns the full settings."""
    with session_scope() as db:
        return store.update_preferences(db, patch)


@mcp.tool()
def list_rules(direction: Direction | None = None) -> list[dict[str, Any]]:
    """Sync rules, ordered by priority (first match wins)."""
    with session_scope() as db:
        return services.list_rules(db, direction)


@mcp.tool()
def save_rule(
    name: str,
    direction: Direction,
    conditions: dict[str, Any],
    actions: dict[str, Any],
    enabled: bool = True,
    priority: int = 100,
    rule_id: int | None = None,
) -> dict[str, Any]:
    """Create (rule_id omitted) or update a sync rule.

    conditions (AND): sports, exclude_sports, families (lists); distance_km, elevation_m, duration_min
    ({"min","max"}); name_contains; name_regex; weekdays (0=Mon); date {"from","to"}; commute, trainer,
    has_heartrate, has_power (bool).
    actions: skip (bool); name / description (templates with {name} {sport} {sport_label}
    {distance_km} {elevation_m} {duration_min} {moving_time} {date} {time} {weekday} {source});
    append_description; sport (target platform sport key); strava {hide_from_home, commute, trainer,
    gear_id}; komoot {visibility: private|friends|public}."""
    data = {
        "name": name,
        "direction": direction,
        "conditions": conditions,
        "actions": actions,
        "enabled": enabled,
        "priority": priority,
    }
    with session_scope() as db:
        return services.save_rule(db, data, rule_id)


@mcp.tool()
def delete_rule(rule_id: int) -> dict[str, bool]:
    """Delete a sync rule."""
    with session_scope() as db:
        services.delete_rule(db, rule_id)
    return {"ok": True}


@mcp.tool()
def preview_rules(direction: Direction, limit: int = 50) -> list[dict[str, Any]]:
    """Dry run over recent activities: would each be synced, which rule decides, the resulting
    name/sport, or what blocks it (already on target, before start date, no GPS…)."""
    with session_scope() as db:
        return sync.preview(db, direction, limit)


@mcp.tool()
def list_sync_jobs(
    status: Literal["queued", "running", "done", "failed", "skipped"] | None = None, limit: int = 50
) -> dict[str, Any]:
    """Sync job history and queue."""
    with session_scope() as db:
        return services.list_jobs(db, status, limit)


@mcp.tool()
def retry_sync_job(job_id: int) -> dict[str, Any]:
    """Retry a failed job, or re-plan a skipped one with the current rules."""
    with session_scope() as db:
        sync.retry(db, job_id)
        db.commit()
        return sync.run_jobs(db, job_ids=[job_id])


@mcp.tool()
def reevaluate_skipped() -> dict[str, int]:
    """Forget rule-skipped decisions and re-plan everything with the current rules."""
    with session_scope() as db:
        return services.reevaluate_skipped(db)


@mcp.tool()
def strava_webhook(action: Literal["status", "enable", "disable"] = "status") -> dict[str, Any]:
    """Strava push events (instant sync on new/edited activities): show, create or remove the
    subscription. Needs ROUTEPASS_PUBLIC_URL reachable from the internet."""
    fn = {
        "status": services.strava_webhook_status,
        "enable": services.strava_webhook_enable,
        "disable": services.strava_webhook_disable,
    }[action]
    with session_scope() as db:
        return fn(db)


@mcp.tool()
def bulk_sync_activities(activity_ids: list[int], direction: Direction) -> dict[str, Any]:
    """Copy a hand-picked set of activities (max 200) to the other platform now. Rules still apply;
    the sync start date and settle delay are ignored. Reports which ones are not eligible and why."""
    with session_scope() as db:
        result = services.bulk_sync(db, activity_ids, direction)
        if result["job_ids"]:
            result["run"] = sync.run_jobs(db, limit=len(result["job_ids"]), job_ids=result["job_ids"])
        return result


@mcp.tool()
def analyse_trip(activity_ids: list[int]) -> dict[str, Any]:
    """Combine several activities (e.g. the stages of a multi-day tour) into one overview:
    totals, per-day breakdown, longest and hilliest day."""
    with session_scope() as db:
        out = services.trip_analysis(db, activity_ids)
    for a in out["activities"]:
        a.pop("polyline", None)
    return out


@mcp.tool()
def full_history_sync(
    action: Literal["status", "analyse", "start", "cancel"] = "status",
    directions: list[Direction] | None = None,
    apply_rules: bool = True,
) -> dict[str, Any]:
    """Bring both platforms fully up to date, all time. `analyse` imports the complete history of
    Strava and Komoot, merges duplicates and previews what is missing on each side (runs in the
    background — poll `status`); `start` queues all those copies (worked off within rate limits);
    `cancel` drops copies that have not run yet."""
    import threading

    from routepass.engine import fullsync

    if action == "analyse":
        dirs = list(directions or ["komoot_to_strava", "strava_to_komoot"])
        threading.Thread(target=fullsync.analyse, args=(dirs, apply_rules), daemon=True).start()
        return {"phase": "importing"}
    with session_scope() as db:
        if action == "start":
            out = fullsync.start(db)
            db.commit()
            runner.trigger_soon()
            return out
        if action == "cancel":
            return fullsync.cancel(db)
        return fullsync.state(db)


@mcp.tool()
def strava_archive_import(file: str | None = None) -> dict[str, Any]:
    """Import Strava's own data export ("Download your account" zip). Without `file`: show progress and the
    zips available in the server's imports/ folder. With `file`: start importing that zip in the background.
    This is the way to get Strava history when the Strava API is unavailable."""
    from pathlib import Path

    from routepass.engine import strava_archive

    with session_scope() as db:
        st = strava_archive.state(db)
    if file:
        path = strava_archive.archive_dir() / Path(file).name
        if not path.is_file():
            return {
                "error": f"{path.name} not found",
                "available": sorted(p.name for p in strava_archive.archive_dir().glob("*.zip")),
            }
        strava_archive.start(path)
        return {"phase": "queued", "file": path.name}
    return {**st, "available": sorted(p.name for p in strava_archive.archive_dir().glob("*.zip"))}


@mcp.tool()
def get_explorer_tiles(
    start: str | None = None, end: str | None = None, families: list[Family] | None = None
) -> dict:
    """Explorer tiles (zoom-14 map squares visited): total, max square, max cluster and new tiles per year."""
    with session_scope() as db:
        out = insights.explorer_tiles(db, _f(start, end, families, None))
    return {k: v for k, v in out.items() if k != "tiles"}


@mcp.tool()
def get_zone_distribution(
    grain: Literal["week", "month", "year"] = "month",
    start: str | None = None,
    end: str | None = None,
    families: list[Family] | None = None,
) -> dict:
    """Time in heart-rate and power zones across activities plus polarisation (low/threshold/high %)."""
    with session_scope() as db:
        return insights.zone_distribution(db, _f(start, end, families, None), grain)


@mcp.tool()
def get_efficiency_trend(
    start: str | None = None, end: str | None = None, families: list[Family] | None = None
) -> list:
    """Aerobic efficiency factor (power or speed per heartbeat) and decoupling per activity, oldest first."""
    with session_scope() as db:
        return insights.efficiency_trend(db, _f(start, end, families, None))


@mcp.tool()
def get_goals(families: list[Family] | None = None) -> list:
    """Progress against the weekly/monthly/yearly goals set in settings, with on-track projection."""
    with session_scope() as db:
        return insights.goals_progress(
            db, date.today(), store.get_preferences(db), list(families) if families else None
        )


@mcp.tool()
def get_gear(start: str | None = None, end: str | None = None) -> dict:
    """Distance, time and climbing per gear and recording device, with service-interval status."""
    with session_scope() as db:
        return insights.gear_stats(db, _f(start, end, None, None), store.get_preferences(db))


@mcp.tool()
def test_rule(direction: str, conditions: dict, rule_id: int | None = None, limit: int = 200) -> dict:
    """Dry-run rule conditions before saving: how many recent activities they match in a direction
    ('komoot_to_strava' or 'strava_to_komoot'), how many an earlier rule already decides, and samples.
    Same condition keys as create_rule."""
    with session_scope() as db:
        return sync.test_rule(db, direction, conditions, rule_id, limit)


@mcp.tool()
def get_data_quality() -> dict:
    """How much recent training load is measured (power / heart rate) rather than estimated, which profile
    values are missing, and values (max HR, FTP) suggested from the recorded data. Set them with
    update_settings to make load, zones and race predictions more accurate."""
    with session_scope() as db:
        return insights.data_quality(db)


@mcp.tool()
def list_duplicate_candidates(limit: int = 30) -> list:
    """Activities that look like the same recording but were not merged. Merge with merge_activities or
    dismiss with dismiss_duplicate_candidate."""
    with session_scope() as db:
        rows = services.duplicate_candidates(db, limit)
    for r in rows:
        r["activity"].pop("polyline", None)
        r["candidate"].pop("polyline", None)
    return rows


@mcp.tool()
def dismiss_duplicate_candidate(activity_id: int, other_id: int) -> dict:
    """Mark a suggested duplicate pair as different activities so it is not suggested again."""
    with session_scope() as db:
        return services.dismiss_duplicate(db, activity_id, other_id)


# ── 50k / ultra trail-running coach ──────────────────────────────────────────


@mcp.tool()
def get_trail_training_brief(weeks: int = 8) -> dict[str, Any]:
    """Complete 50k / trail-running coaching dossier for AI analysis and training recommendations.
    Includes target race countdown & phase (base/build/peak/taper), weekly distance/vertical/ITRA
    effort-km, biggest back-to-back weekends, CTL/ATL/TSB + ACWR injury-risk status, recent long-run
    aerobic durability (GAP + HR decoupling), median GAP & climbing VAM, trail shoe mileage, and
    automated coaching flags."""
    with session_scope() as db:
        return trail.trail_readiness(db, store.get_preferences(db), weeks=max(4, min(weeks, 26)))


@mcp.tool()
def set_trail_race_goal(
    name: str | None = None,
    date: str | None = None,
    distance_km: float | None = None,
    elevation_gain_m: float | None = None,
    weekly_km_target: float | None = None,
    weekly_vert_target: float | None = None,
    target_carbs_g_per_h: float | None = None,
) -> dict[str, Any]:
    """Configure or update the target trail race (e.g. 50k date, distance, vertical gain, weekly targets).
    date should be YYYY-MM-DD (or empty string to clear). Only supplied fields are changed."""
    patch: dict[str, Any] = {}
    if name is not None:
        patch["name"] = name
    if date is not None:
        patch["date"] = date or None
    if distance_km is not None:
        patch["distance_km"] = distance_km
    if elevation_gain_m is not None:
        patch["elevation_gain_m"] = elevation_gain_m
    if weekly_km_target is not None:
        patch["weekly_km_target"] = weekly_km_target
    if weekly_vert_target is not None:
        patch["weekly_vert_target"] = weekly_vert_target
    if target_carbs_g_per_h is not None:
        patch["target_carbs_g_per_h"] = target_carbs_g_per_h
    with session_scope() as db:
        prefs = store.update_preferences(db, {"trail_race": patch})
        return prefs["trail_race"]


@mcp.tool()
def analyze_trail_activity(activity_id: int) -> dict[str, Any]:
    """Trail-specific deep dive for one activity: Grade-Adjusted Pace (GAP), ITRA effort-km, vertical
    specificity vs target race (m/km), detected climbs with VAM and grade, km splits with +m/-m/GAP/HR,
    HR zones, and aerobic decoupling."""
    with session_scope() as db:
        return trail.analyze_trail_activity(db, activity_id, store.get_preferences(db))


@mcp.tool()
def plan_trail_race_gpx(
    gpx_xml: str,
    aid_stations_km: list[float] | None = None,
    fade_pct: float = 8.0,
    carbs_g_per_h: float = 70.0,
    fluid_ml_per_h: float = 600.0,
    base_gap_speed_ms: float | None = None,
) -> dict[str, Any]:
    """Predict 50k / ultra trail race splits, finish time, major climbs, and carb/fluid fueling from a
    GPX route using the athlete's real historical GAP and Minetti grade cost."""
    with session_scope() as db:
        return trail.plan_gpx_race(
            db,
            gpx_xml.encode("utf-8"),
            aid_stations_km=aid_stations_km,
            fade_pct=fade_pct,
            carbs_g_per_h=carbs_g_per_h,
            fluid_ml_per_h=fluid_ml_per_h,
            base_gap_speed_ms=base_gap_speed_ms,
        )


@mcp.prompt()
def trail_coach_review(focus: str = "weekly review and next-week plan") -> str:
    """Structured prompt for an AI trail-running coach reviewing 50k preparation."""
    return (
        "You are an experienced 50k / ultra trail-running coach. "
        "Call `get_trail_training_brief(weeks=8)` first (and `analyze_trail_activity` on the most recent "
        "long run if available). Then provide a concise, actionable coaching report covering:\n"
        "1. Readiness & Training Phase (weeks to race, volume vs targets, vertical specificity m/km).\n"
        "2. Load & Injury Risk (CTL/ATL/TSB, ACWR, and back-to-back weekend progression).\n"
        "3. Aerobic Durability & Climbing (long-run decoupling, GAP trend, climbing VAM, shoe mileage).\n"
        "4. Concrete Next-Week Plan (key sessions, target km & D+, fueling practice, and recovery advice).\n"
        f"Additional focus from athlete: {focus}"
    )


@mcp.tool()
def get_training_plan(plan_id: int | None = None) -> dict[str, Any]:
    """Return the active (or specified) multi-sport training plan with alignment score, race finish-time
    prediction, CTL trajectory graph, upcoming sessions, and recent AI adaptations."""
    from sqlalchemy import select

    from routepass.analysis import training
    from routepass.models import TrainingPlan

    with session_scope() as db:
        plan = (
            db.get(TrainingPlan, plan_id)
            if plan_id is not None
            else db.scalar(
                select(TrainingPlan).where(TrainingPlan.status == "active").order_by(TrainingPlan.id.desc())
            )
        )
        if plan is None:
            return {
                "active_plan": None,
                "message": "No active training plan yet. Call create_training_plan to create one.",
            }
        return training.serialize_plan_detail(db, plan, store.get_preferences(db))


@mcp.tool()
def create_training_plan(
    name: str,
    plan_type: str,
    event_date: str,
    run_km: float | None = None,
    run_elev_m: float | None = None,
    bike_km: float | None = None,
    bike_elev_m: float | None = None,
    swim_km: float | None = None,
    target_time_s: int | None = None,
    max_weekly_hours: float = 8.0,
    preferred_slot: str = "evening",
    use_ai: bool = True,
) -> dict[str, Any]:
    """Create a multi-sport adaptive training plan (`trail_run`, `road_run`, `cycling`, `triathlon`,
    `duathlon`, or `base_build`) ending on `event_date` (YYYY-MM-DD)."""
    from routepass.analysis import training

    targets: dict[str, Any] = {}
    if run_km is not None:
        targets["run_km"] = run_km
    if run_elev_m is not None:
        targets["run_elev_m"] = run_elev_m
    if bike_km is not None:
        targets["bike_km"] = bike_km
    if bike_elev_m is not None:
        targets["bike_elev_m"] = bike_elev_m
    if swim_km is not None:
        targets["swim_km"] = swim_km
    goal_spec: dict[str, Any] = {"targets": targets}
    if target_time_s is not None:
        goal_spec["target_time_s"] = target_time_s

    with session_scope() as db:
        prefs = store.get_preferences(db)
        plan = training.create_plan(
            db,
            prefs,
            {
                "name": name,
                "plan_type": plan_type,
                "event_date": event_date,
                "goal_spec": goal_spec,
                "schedule_prefs": {"max_weekly_hours": max_weekly_hours, "preferred_slot": preferred_slot},
            },
            use_ai=use_ai,
        )
        return training.serialize_plan_detail(db, plan, prefs)


@mcp.tool()
def adapt_training_plan(plan_id: int | None = None, user_note: str = "") -> dict[str, Any]:
    """Match recorded activities to the active training plan and adapt upcoming 14 days using Gemini AI
    (or deterministic fallback if budget/key unavailable)."""
    from sqlalchemy import select

    from routepass.analysis import training
    from routepass.models import TrainingPlan

    with session_scope() as db:
        plan = (
            db.get(TrainingPlan, plan_id)
            if plan_id is not None
            else db.scalar(
                select(TrainingPlan).where(TrainingPlan.status == "active").order_by(TrainingPlan.id.desc())
            )
        )
        if plan is None:
            return {"error": "No active training plan found"}
        return training.adapt_plan(
            db, plan, store.get_preferences(db), trigger="mcp", user_note=user_note, force=True
        )


@mcp.tool()
def update_training_session(
    session_id: int,
    status: str | None = None,
    scheduled_date: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Update a planned training session (mark completed/skipped or move to a new YYYY-MM-DD date)."""
    from routepass.models import TrainingSession

    with session_scope() as db:
        s = db.get(TrainingSession, session_id)
        if s is None:
            return {"error": f"Session {session_id} not found"}
        if scheduled_date:
            s.scheduled_date = scheduled_date[:10]
            if not status:
                s.status = "moved"
        if status:
            s.status = status
        if note:
            s.adaptation_note = note[:300]
        db.flush()
        return {"id": s.id, "scheduled_date": s.scheduled_date, "status": s.status, "note": s.adaptation_note}

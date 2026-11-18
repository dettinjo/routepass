# Architecture

## Goals

One person, one homelab, two platforms. Sync Strava and Komoot in configurable directions by
rules, never create duplicates, and analyse the combined history as if every activity existed
exactly once. Small and fast: one container, one SQLite file, no queue or cache services.

## Runtime

```
┌────────────── routepass container (uvicorn, one process) ──────────────┐
│  /            React SPA (static)                                       │
│  /api/v1/*    REST (FastAPI, OpenAPI at /api/docs)     ─┐              │
│  /mcp         MCP streamable HTTP (stateless, JSON)    ─┼─ services.py │
│  scheduler    background thread: run_cycle() every N min┘   engine/    │
│                                                             analysis/  │
│  SQLite (WAL) /data/routepass.db  ·  Fernet key /data/secret.key       │
└────────────────────────────────────────────────────────────────────────┘
```

The scheduler and manual/API/MCP triggers share one lock, so cycles never overlap.

## Data model

| Table | Purpose |
|---|---|
| `activities` | The deduplicated activity: canonical sport (Strava `sport_type`), family, totals, HR/power/load, start/end point, simplified polyline |
| `provider_activities` | One row per Strava activity / Komoot tour, linked to an activity. Keeps the slim raw summary, `created_by_sync`, `match_locked`, `deleted`, `track_status` |
| `tracks` | Full-resolution recording (delta-encoded int32 + zlib, ~10–40 KB) + compressed chart series + detail (zones, splits, climbs, decoupling, best efforts) |
| `efforts` | Per-activity best efforts (power curve points, fastest distances, biggest climb) — indexed so records and the all-time power curve are single queries |
| `sync_rules` | Ordered rules per direction: `conditions` and `actions` JSON |
| `sync_jobs` | Every sync decision: queued/running/done/failed/skipped, the rule, the upload plan, target id, retries |
| `sync_runs` | Cycle log (stats + messages) |
| `settings` | Preferences, encrypted credentials, import watermarks |

## Sync cycle (`engine/runner.py`)

1. **Import** Strava (`/athlete/activities`, 200 per page) and Komoot (recorded tours). Incremental
   from a watermark minus 3 days; a full rescan every 24 h marks deleted records.
2. **Match** unlinked records (`engine/ingest.py`): a record RoutePass created is linked to its
   job's activity; otherwise the best candidate activity within ±10 min start, ±15 % distance,
   without a live record from the same provider; else a new activity. Canonical fields come from
   the original recording (Strava preferred), enriched by the track.
3. **Plan** (`engine/sync.py`): for each enabled direction, every activity on or after the sync
   start date that exists on the source, is missing on the target, is not a RoutePass copy, is
   not locked, has GPS, and has been known longer than the settle delay → rules decide → job.
4. **Execute**: Komoot GPX → Strava upload (`external_id = routepass-komoot-<id>`, duplicate
   errors are linked instead of failing); Strava streams → GPX (with HR/cadence/power
   extensions) → Komoot upload + visibility. Backoff 15 min → 12 h, max 5 attempts; rate limits
   defer without counting an attempt.
5. **Tracks**: download recordings newest-first (Strava streams preferred for HR/power; Komoot
   coordinates otherwise) within a time budget; background calls keep 25/15 min and 150/day
   of Strava's limit free.

## Analysis

`analysis/track.py` (numpy, pure): moving time, hysteresis elevation gain, normalized power,
TSS (power) → hrTSS (heart-rate reserve) → duration estimate, HR/power zones, splits, climbs,
best times per distance, mean-maximal power, aerobic decoupling, LTTB downsampling.
`analysis/insights.py` aggregates over `activities` only: totals, period comparison, time
series, calendar, year-over-year, CTL/ATL/TSB, records, power curve, habits, streaks,
Eddington, route heatmap, platform coverage.

Profile changes (FTP, HR max/rest) recompute every stored track in the background.

## Security

Bearer token (`ROUTEPASS_API_TOKEN`) on API, MCP and UI; meant to run on a private network
(the homelab deploys it on the tailnet only). Strava tokens and Komoot credentials are
Fernet-encrypted at rest.

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

The scheduler and manual/API/MCP triggers share one lock, so cycles never overlap. Automatic syncs run every
30 min (or 1/2/6 h, or never — manual only); webhooks and new connections trigger a cycle immediately. Queued
copies (e.g. an all-time sync) are worked off every 2 min between scheduled syncs without re-polling the
platforms, so a backlog never multiplies API traffic.

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

## Deployment shape

The UI is meant for a private network. Optionally a reverse proxy publishes `ROUTEPASS_PUBLIC_URL`
with only these paths: `/api/v1/connections/strava/callback` (OAuth), `/api/v1/webhooks/strava`
(Strava push events → a cycle now and another after the settle delay), `/api/v1/*` and `/mcp`
(bearer token). The homelab does this with Caddy on the public VPS → tailnet → home server.

## Validation on real tracks

Ten public recorded Komoot tours (road/MTB rides up to 142 km, half marathons, an 87 km hike,
ski and mountain tours) were run through the engine: distance within 1–4 % of Komoot, elevation
gain within 0–5 % on clean tracks (Komoot computes its own total from data it does not export, so
provider totals stay authoritative), moving time within 0–3 % except where Komoot counts stops as
motion. Two anonymised tracks are regression fixtures in `server/tests/fixtures`.

## Security

Two listeners in one process (`python -m routepass.serve`): the private port serves the UI and trusts the
Tailscale identity headers that `tailscale serve` sets; the public port (behind the internet-facing proxy)
serves only `/api/v1/*` and `/mcp`, accepts only the API token and never trusts those headers. UI sessions
are HMAC-signed, HttpOnly cookies for the allowed e-mail(s), issued after Tailscale identity, Google sign-in
(callback on the public URL, handed to the private host with a 2-minute one-time code) or the API token.

Bearer token (`ROUTEPASS_API_TOKEN`) on API, MCP and UI; meant to run on a private network
(the homelab deploys it on the tailnet only). Strava tokens and Komoot credentials are
Fernet-encrypted at rest.

## Strava access (status November 2026)

- Since 30 June 2026 a Strava API application in the Standard Tier only works while the account that owns it has
  a paid Strava subscription; otherwise every API call returns `403 {"resource":"Application","field":"Status",
  "code":"Inactive"}` while OAuth keeps working.
- **Option 1 — Web Session Client (`StravaWebClient`, `PUT /api/v1/connections/strava/session`)**: authenticates
  with browser session cookies (`_strava4_session` and optional `strava_remember_token`, accepted as a raw cookie,
  `Cookie:` header, DevTools *Copy as cURL*, *Copy Request Headers*, or cookie table rows — compatible with Strava's
  Email 6-digit One-Time Code, Google, and Apple sign-in flows). Uses `strava.com/dashboard` (CSRF + athlete profile),
  `/athlete/training_activities` (paginated JSON activity list), `/activities/{id}/streams` (with `/export_original`
  and `/export_gpx` fallback), and `/upload/files` + `/upload/progress` + `PATCH /activities/{id}` so continuous
  **Strava ⇄ Komoot** sync works in both directions without a paid Strava subscription. When both OAuth and a web
  session are configured (`mode: "oauth+web"`), `StravaClient` automatically falls back to `StravaWebClient` if the
  v3 API returns `403 Application Status: Inactive`, while persisting rotated session cookies encrypted at rest.
- **Option 2 — Personal Data Export (`engine/strava_archive.py`)**: imports a user's bulk Strava `.zip` export
  (`activities.csv` + FIT/GPX/TCX originals, protected under API Policy §6.6) as `strava` records keyed by Strava's
  activity id, so historical analysis, deduplication and Strava → Komoot copies work offline without the API.
- The Strava API Policy (effective 1 June 2026) limits API data heavily: cache at most 7 days (§6.2), no AI use incl.
  context windows (§5.3), no MCP server exposing Strava Data (§5.16), no persistent indexes (§5.5). These apply to
  data obtained through the API ("Strava Data", API Agreement §2.3). This is not legal advice.

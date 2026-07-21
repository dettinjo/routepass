# GPX Track Analysis — Plan & Status

Comprehensive per-activity, aggregate, and multi-day-trip track metrics with
interactive charts. Compute server-side (Python + numpy), cache, serve JSON;
render client-side (recharts + react-leaflet, both already in the app).

Status: **Phases 1–4 shipped** (metric engine + ingestion + API; activity
detail analysis UI; aggregate overview + training profile; multi-day trip
analysis). Phase 5 below is the remaining training-load work.

## Architecture

Parse & compute on the backend, never in the browser. On ingest/backfill: fetch
rich Strava streams (or parse GPX + Garmin `TrackPointExtension`), compute with
numpy, store aggregate scalars as columns (for cheap SUM/AVG in overview) + a
`metrics_detail` JSON (zones, splits) + a gzipped LTTB-downsampled per-point
series (`track_gz`, lazy-loaded for charts). Multi-tour = combine precomputed
summaries + concatenate downsampled profiles.

## Metric catalog

- **Summary:** distance (total/moving), time (elapsed/moving), avg/max speed &
  pace, elevation gain/loss/min/max, VAM, avg/max HR + HR zones + TRIMP, avg/max
  power + NP + IF + TSS + work(kJ) + power zones, cadence, temperature, calories,
  per-km splits, aerobic decoupling.
- **Per-point (charts):** distance, time, elevation, hr, power, cadence, speed,
  grade, temp, latlng.
- **Overview (all or filtered):** totals, by-sport, trends, distributions, PRs,
  consistency, CTL/ATL/TSB training load.
- **Multi-day trip:** combined totals, per-stage table, cumulative profile,
  day bars, aggregate zones, multi-stage map.

Data richness degrades by source (Strava richest; Komoot routes = geo+ele only).
`metrics_available` drives which UI sections show.

## Technology

| Concern | Choice |
|---|---|
| Metric compute | Python `gpxpy` + **numpy**, server-side |
| Downsampling | **LTTB** → ~1000 pts (`app.services.metrics._lttb_indices`) |
| Elevation gain/loss | hysteresis accumulation (robust dense + sparse) |
| Standard charts | **recharts** (installed) |
| Big synced profile | recharts → **uPlot** upgrade path if needed |
| Map | **react-leaflet** (installed) + metric-colored polyline |
| Chart styling | follow the repo `dataviz` skill |

## Phase 1 (shipped)

- `app/services/metrics.py` — pure engine: `normalize_strava_streams`,
  `parse_gpx` (+ extensions), `compute_metrics` (summary/zones/splits), LTTB
  downsample. Fully unit-tested (`tests/test_metrics.py`).
- `synced_activities` gains metric columns + `metrics_detail` + `track_gz`
  (migration 017).
- Rich Strava stream keys (`StravaClient.STREAM_KEYS`).
- `compute_activity_metrics` ARQ job + `metrics_backfill_scheduler` cron
  (every 5 min, 25/tick, rate-limit-safe) resolving GPX or Strava streams.
- `GET /activities/{id}/metrics` and `/track`.

## Phase 2 (shipped)

- `frontend/app/(dashboard)/activities/activity-analysis.tsx` — lazy-loaded in
  the detail modal (keeps recharts out of the /activities bundle). Stacked
  single-series profile panels (elevation/HR/power/speed/cadence) sharing a
  synced crosshair via recharts `syncId` — never dual-axis; HR/power
  time-in-zone bars (ordinal blue ramp); per-km splits table; enriched metric
  tiles gated on `metrics_available`.
- `frontend/hooks/use-activity-analysis.ts` — metrics/track hooks, poll while
  the backfill cron computes.
- Chart-series + zone-ramp tokens in `globals.css` (dark + light).

Map↔crosshair hover-sync (highlighting the map point under the chart cursor)
is deferred — the map and profile currently render independently.

## Phase 3 (shipped)

- `GET /activities/overview` — totals, per-sport breakdown, and a time trend
  (weekly ≤120d span, else monthly), honouring the same filters as the list.
  Sums the stored metric columns in one scan; profile-independent
  distance/duration/elevation from base columns, calories/TSS/moving-time from
  computed metrics.
- `frontend/app/(dashboard)/activities/activity-overview.tsx` — lazy-loaded
  collapsible panel above the list, reacts to active filters: total tiles +
  distance-by-sport bars + distance-per-period trend bars (single-hue
  magnitude, recharts).
- **Training profile**: `users.ftp` / `users.hr_max` (migration 018), edited on
  the settings page, returned by `/auth/me`, threaded into `compute_metrics`
  (unlocks TSS + proper power/HR zones). Changing them invalidates
  (`metrics_computed_at → NULL`) and re-enqueues recompute for the user's
  HR/power activities only.

## Phase 4 (shipped)

- `POST /activities/analysis` — takes `activity_ids` (2–20, any tier), orders
  stages by `started_at`, and returns combined totals, a per-stage table
  (with a `cumulative_distance_start_m` offset per stage), day-bucketed
  distance bars, a concatenated elevation profile (per-point `x` = running
  distance across all stages, in km), multi-stage map polylines (decoded
  from `track_gz`), and HR/power zone-seconds summed position-wise across
  stages.
- `frontend/app/(dashboard)/activities/trip-view.tsx` — modal triggered from
  the existing multi-select bulk-action bar ("Analyze trip", enabled at ≥2
  selected, capped at 20). Totals tiles, `trip-map.tsx` (one polyline per
  stage), a single elevation-profile chart with dashed `ReferenceLine`s at
  stage boundaries, day bars, combined zone bars (reusing `ZoneBar` from
  Phase 2), and a stage table with a categorical color dot per row.
- New **categorical theme** (`--chart-cat-1..8` in `globals.css`, dark +
  light) — the first genuinely categorical palette in the app (Phases 1–3
  are all single-hue sequential). Validated via the dataviz skill against
  both surfaces; worst-case CVD sits in the 8–12 floor band, so identity
  never relies on color alone — every stage also gets a tooltip and a table
  row (the "relief rule"). Stages beyond the 8th slot fold into a neutral
  gray rather than cycling hues.
- Trip analysis is ungated (available to all tiers), consistent with Phases
  1–3.

## Phase 5 (planned)

5. **Training load** (CTL/ATL/TSB, PRs, decoupling) — Pro-gate candidate.

## Open decisions (for the UI phases)

1. Units — metric only vs metric/imperial toggle.
2. Pro-gating — power/TSS and multi-day trip analysis shipped ungated
   (Phases 3–4); training load (Phase 5) remains the pro-gate candidate.
3. ~~Zones/FTP training-profile setting~~ — **done (Phase 3):** `users.ftp` /
   `users.hr_max` unlock TSS + proper zones.

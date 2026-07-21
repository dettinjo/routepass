# GPX Track Analysis — Plan & Status

Comprehensive per-activity, aggregate, and multi-day-trip track metrics with
interactive charts. Compute server-side (Python + numpy), cache, serve JSON;
render client-side (recharts + react-leaflet, both already in the app).

Status: **Phases 1–2 shipped** (metric engine + ingestion + API; activity
detail analysis UI). Phases 3–5 below are the aggregate/trip/training-load work.

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

## Phases 3–5 (planned)

3. **Overview/aggregate** stats wired to the existing activity filters.
4. **Multi-day trip** analysis: multi-select + `POST /activities/analysis` +
   trip view (stage table, cumulative profile, day bars, multi-stage map).
5. **Training load** (CTL/ATL/TSB, PRs, decoupling) — Pro-gate candidate.

## Open decisions (for the UI phases)

1. Units — metric only vs metric/imperial toggle.
2. Pro-gating — gate advanced (power/TSS, training load, multi-day) behind Pro?
3. Zones/FTP — a small "training profile" setting for HR-max/FTP to unlock
   TSS & proper zones (Phase 1 uses observed HR max, no FTP → no TSS yet).

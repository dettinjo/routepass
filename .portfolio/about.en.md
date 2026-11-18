## RoutePass — Strava ⇄ Komoot sync and activity analysis

A self-hosted, single-user service that keeps Strava and Komoot in step and turns the combined
history into one deduplicated training log.

### What it does

- **Rule-based sync in both directions.** Komoot tours can be copied to Strava and Strava
  activities to Komoot. Ordered rules (sport, distance, elevation, duration, name, weekday,
  indoor/commute, HR/power) decide what is copied and how: title and description templates,
  sport mapping, Komoot visibility, Strava feed muting. A dry-run preview shows every decision
  before anything is uploaded.
- **No duplicates.** Every record from both platforms is matched into a single activity by start
  time, distance and sport. Something already on the target is never uploaded again, and a
  settle delay covers devices that upload to both platforms.
- **Analysis.** Fitness/fatigue/form, records and best efforts, power curve, climbs, splits,
  HR and power zones, aerobic decoupling, calendar heatmap, year-over-year progress, habits,
  Eddington number and a map of every route.
- **API and MCP.** Everything is available over a REST API and as MCP tools, so an AI assistant
  can query training data or change sync rules.

### Architecture

One container: FastAPI serves the REST API, an MCP server (streamable HTTP) and the React UI,
while a background thread polls both platforms. Data lives in a single SQLite file; recordings
are stored delta-encoded and compressed (tens of KB per activity). Track metrics are computed
with numpy; the UI uses uPlot and Leaflet and stays under 170 KB gzipped.

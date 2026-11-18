# RoutePass

Self-hosted, single-user **Strava ⇄ Komoot sync** with a deduplicated activity history and
in-depth analysis. One small container: API, MCP server, web UI and background sync, backed by
one SQLite file.

- **Sync in both directions** — Komoot → Strava and Strava → Komoot, each switchable, with
  ordered rules (sport, distance, elevation, duration, name, weekday, date, commute/indoor,
  HR/power) that skip or shape the copy (title/description templates, sport mapping, Komoot
  visibility, Strava feed muting/commute/gear). Dry-run preview before anything is uploaded.
- **No duplicates** — every Strava activity and Komoot tour is matched into one *activity*
  (start time + distance + sport). Something already on the target platform is never copied,
  RoutePass' own uploads are recognised, and a settle delay lets devices that upload to both
  platforms arrive before anything is copied. Wrong matches can be split or merged by hand.
- **Analysis** — dashboard (week/month/year vs previous), weekly/monthly volume by sport,
  year-over-year, calendar heatmap, fitness/fatigue/form (CTL/ATL/TSB), records and best
  efforts, mean-maximal power curve, habits (weekday×hour), streaks, Eddington number, a map of
  every route, and per activity: map with linked stream charts, HR/power zones, splits,
  climbs, best efforts, peak power, aerobic decoupling and repeats of the same route.
  Select several activities to copy them in bulk or to analyse them as one multi-day trip.
- **API & MCP** — everything the UI does is in the REST API (`/api/docs`) and as MCP tools
  (`/mcp`, streamable HTTP) for AI assistants.

## Run

```bash
cp .env.example .env            # set ROUTEPASS_API_TOKEN and your Strava app id/secret
docker compose up --build       # http://localhost:8000
```

Then in **Settings**: connect Strava (OAuth with your own API app from
<https://www.strava.com/settings/api>, callback domain = this host) and Komoot (email +
password, stored Fernet-encrypted). The first import runs immediately; recordings are
downloaded in the background within Strava's rate limits.

| Variable | Default | Meaning |
|---|---|---|
| `ROUTEPASS_API_TOKEN` | *(empty)* | Bearer token for UI, API and MCP. Empty = no auth (trusted network only) |
| `ROUTEPASS_BASE_URL` | `http://localhost:8000` | URL users open; builds the Strava OAuth redirect |
| `ROUTEPASS_STRAVA_CLIENT_ID` / `_SECRET` | | Strava API app (can also be entered in Settings) |
| `ROUTEPASS_PUBLIC_URL` | | Internet-facing URL that exposes only the API paths (OAuth callback, Strava webhook, REST, MCP); used for the Strava redirect and webhook |
| `ROUTEPASS_STRAVA_WEBHOOK_VERIFY_TOKEN` | | Shared secret for Strava push events (instant sync); enable under Settings → Strava |
| `ROUTEPASS_STRAVA_REDIRECT_URI` | | Override the OAuth redirect; paste the returned `code` in Settings |
| `ROUTEPASS_SECRET_KEY` | generated | Fernet key for stored credentials (else `/data/secret.key`) |
| `ROUTEPASS_POLL_INTERVAL_MINUTES` | `30` | How often both platforms are polled |
| `ROUTEPASS_DATA_DIR` | `/data` | SQLite database + key |

## MCP

```json
{ "mcpServers": { "routepass": { "type": "http", "url": "https://<host>/mcp",
  "headers": { "Authorization": "Bearer <ROUTEPASS_API_TOKEN>" } } } }
```

Tools cover status and sync runs, activity search/detail/streams/similar routes, totals,
period comparison, time series, training load, records, power curve, habits, Eddington,
year-over-year, settings, rules (list/save/delete/preview), the job queue, and manual
merge/split/lock/sync of single activities.

## Develop

```bash
cd server && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
pytest && ruff check . && ruff format --check .
ROUTEPASS_DATA_DIR=./data python -m scripts.seed_demo   # optional: 2 years of synthetic data
uvicorn routepass.asgi:app --reload                     # :8000

cd web && npm ci && npm run dev                         # :5173, proxies /api and /mcp
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.

## License

MIT

# RoutePass — instructions for Claude

Single-user, self-hosted Strava ⇄ Komoot sync + activity analysis. Read `docs/ARCHITECTURE.md`
first. Version 2 (Nov 2026) replaced the multi-tenant SaaS (Postgres/Redis/ARQ/Next.js,
billing, admin, docs site) — that code is only in git history (before the v2 merge).

## Layout

```
server/routepass/   FastAPI app (one process): api/routes.py, mcp_server.py, services.py (shared by both),
                    engine/ (ingest+dedup, rules, sync, runner/scheduler), analysis/ (track metrics, insights),
                    providers/ (strava, komoot, gpx, sports), models.py, db.py, store.py (settings/secrets),
                    ai/ (gemini.py client + budget, coach.py background AI coach jobs)
server/tests/       pytest; provider HTTP mocked with respx
server/scripts/     seed_demo.py (synthetic data for UI work)
web/                Vite + React + TanStack Query + uPlot + Leaflet; builds into server/routepass/static
```

## Commands

```bash
cd server && pytest -q && ruff check . && ruff format --check .
cd web && npx tsc -p . --noEmit && npx vite build
```

## Rules

- Every feature goes into `services.py` (or engine/analysis) and is exposed in **both** the REST
  API (`api/routes.py`) and MCP (`mcp_server.py`).
- All Strava calls go through `StravaClient._request` (rate-limit window, background reserve).
  Komoot's API is unofficial: every failure raises `KomootError` and is retried later.
- Dedup invariant: analysis only reads `activities`; never count `provider_activities`.
  The sync engine must never upload when the activity already has a live record on the target.
- Credentials are only stored through `store.set_secret` (Fernet).
- AI coach: Gemini is only called from `ai/coach.py` jobs on its worker thread, never inside a request
  or an open DB transaction (gemini-4 models can take a minute). The code computes every number; the
  model writes text or proposes changes that `training._apply_mutations` checks. Every AI job has a
  built-in-rules or numbers-only fallback, and the reason is stored (`ai_error`) and shown.
- Schema change: bump `SCHEMA_VERSION` in `db.py` and add the ALTER statements to `_MIGRATIONS`.
- Sports: change mappings only in `providers/sports.py`, then bump `SPORTS_VERSION` in `engine/ingest.py`
  so stored activities are remapped once at startup.
- UI is mobile first (styles.css base = phone, `@media (min-width: 900px)` = desktop). Check every page at
  390 px for horizontal overflow; charts use `contain: inline-size` and are created once, then `setData`.
- Charts: one y-axis per chart; categorical colours follow the sport family in fixed order
  (`web/src/lib/colors.ts`), tokens in `styles.css` for light and dark.
- Deploy: push to `main` → GHCR `ghcr.io/dettinjo/routepass:latest` → Komodo stack
  `routepass-local` on the home server (dettinjo/homelab `stacks/home/routepass-local`).

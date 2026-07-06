# RoutePass AI Handoff & Governance

Welcome! If you are an AI assistant taking over this project, read this document carefully before touching the codebase. It contains the workflow rules, architectural constraints, and the precise current project state for **RoutePass** (formerly `komoot-strava-sync`).

---

## 📐 General Code Rules

1. **Python Compatibility**:
   - The runtime is **Python 3.11** (backend venv).
   - All code MUST use `from __future__ import annotations`.
   - Use `X | Y` shorthand is fine; `datetime.UTC` is fine.
   - Backend is in `backend/`.

2. **Frameworks**:
   - Backend API: **FastAPI** (Async)
   - Database ORM: **SQLAlchemy 2.0** with `AsyncSession`.
   - Background Jobs: **ARQ** + **Redis**.
   - External HTTP: `httpx.AsyncClient` only.
   - Settings: **pydantic-settings** (`BaseSettings`).

3. **Architectural Constraints**:
   - Credentials are **always stored encrypted** (AES-256 Fernet via `security.encrypt/decrypt`).
   - Rate limiting is mandatory for Strava: use `RateLimitGuard.call()`.
   - All handlers and services are async; no blocking I/O.
   - ALL Strava OAuth flows route through `RateLimitGuard.pick_least_loaded_app()` to spread load across the app pool.

4. **Important Paths**:
   - Real project root: `/Users/joeldettinger/Documents/Coding/Privat/routepass/`
   - The shell cwd resets to a different path — always use absolute paths in Bash.

---

## 🔄 AI Handoff Workflow

1. Read `backend/CLAUDE.md` for compact architecture reference.
2. View `AI_HANDOFF.md` (this file) for current state.
3. `cd /Users/joeldettinger/Documents/Coding/Privat/routepass && make check` — must pass **86 tests**.
4. Update this **Current State** section before concluding your session.

---

## 📁 Repository Structure

```
.
├── backend/                  # FastAPI SaaS backend
│   ├── app/
│   │   ├── api/v1/           # REST endpoints (auth, sync, activities, connections, pipelines, rules, billing, api-keys, webhooks, export)
│   │   ├── core/             # config, security (JWT + Fernet), rate_limit
│   │   ├── db/models/        # User, StravaApp, StravaToken, Subscription, ApiKey, SyncedActivity, SyncRule,
│   │   │                     # Connection, Pipeline, ConnectionSyncState, UserAuditLog, JobAuditLog
│   │   ├── jobs/             # ARQ: poll_user_sources, process_strava_activity, run_pipeline, source_poll_scheduler
│   │   ├── services/         # KomootClient, StravaClient, SyncService, StorageService, IntervalsIcuClient, RunalyzeClient, audit
│   │   └── main.py           # FastAPI app factory, Scalar docs at /docs
│   ├── alembic/versions/     # 001–011, all applied in dev
│   └── tests/                # 86 tests, all passing
├── frontend/                 # Next.js 15 App Router
└── legacy/                   # Frozen standalone implementation
```

---

## 🧠 Current Project State (as of 2026-05-04)

**Branch**: `feature/implement-plan-phase1`
**Tests**: 103/103 passing (`make check` clean)
**Last 10 commits** (most recent first):

| SHA | Description |
|-----|-------------|
| `b6e6219` | feat: Garmin Connect source (E6) and platform-agnostic rule engine (F6) |
| `060600c` | docs: update AI_HANDOFF with complete implementation plan status |
| `95fdb34` | feat: audit log, constraint fixes, ARQ cleanup (C5/F2/F5/E7) |
| `701ec34` | feat: presigned URL downloads and cascading storage purge (C1/C2) |
| `46e80de` | feat: GPX object storage (A5-ph1) and multi-app OAuth routing (A4) |
| `6f06861` | refactor: platform-agnostic /sync/status response (F3) |
| `c0c4071` | feat: per-connection sync watermarks — ConnectionSyncState table (E5) |
| `9f630f2` | feat: multi-origin CORS via FRONTEND_URLS env var (B5) |
| `009cf14` | feat: implement Strava→Intervals.icu and Strava→Runalyze pipeline handlers (E3/E4) |
| `39b244d` | feat: GDPR data export, improved account deletion, credential isolation (C3/C4) |

---

## ✅ IMPLEMENTATION PLAN STATUS

All tasks in `IMPLEMENTATION_PLAN.md` that are marked **launch-critical** are now complete.

### Area A — Scalability
| Task | Status |
|------|--------|
| A1: Migration 007 multi-destination sync schema | ✅ Done |
| A2: ARQ dedup key + scheduler Redis lock | ✅ Done |
| A3: DB connection pool config | ✅ Done |
| A4: Strava multi-app fan-out via pick_least_loaded_app | ✅ Done |
| A5-ph1: GPX object storage (S3/R2 via aiobotocore, dual-write) | ✅ Done |
| A5-ph2: Drop gpx_data column after migration | ⏳ Deferred — run after A5-ph1 is live for 2+ deploys |

### Area B — Deployment Split
| Task | Status |
|------|--------|
| B1: DEPLOYMENT_MODE config | ✅ Done |
| B2: Deployment guards | ✅ Done |
| B3: /api/v1/instance endpoint | ✅ Done |
| B4: Frontend instance-aware UI | ⏳ Deferred |
| B5: Multi-origin CORS (FRONTEND_URLS) | ✅ Done |
| B6: Deprecate LICENSE_SERVER_URL | ✅ Done |

### Area C — Privacy & Integrity
| Task | Status |
|------|--------|
| C1: Presigned URL GPX downloads (never stream through API) | ✅ Done |
| C2: Cascading storage purge on activity/account delete | ✅ Done |
| C3: GDPR data export + account deletion | ✅ Done |
| C4: Credential isolation hardening | ✅ Done |
| C5: UserAuditLog table + writes on sensitive actions | ✅ Done |

### Area D — Coolify/Hetzner Infra
| Task | Status |
|------|--------|
| D1–D8: Server, Coolify, Docker Compose, Object Storage, CI/CD, Backups, Init container | ⏳ Manual deployment steps — not yet done |

### Area E — Multi-directional Sync
| Task | Status |
|------|--------|
| E1: Fix sync_direction at ingest | ✅ Done |
| E2: Write destination_platform on success | ✅ Done |
| E3: Strava→Intervals.icu handler | ✅ Done |
| E4: Strava→Runalyze handler | ✅ Done |
| E5: Per-connection sync watermarks (ConnectionSyncState) | ✅ Done |
| E6: Garmin Connect source | ✅ Done |
| E7: Remove backward-compat ARQ aliases | ✅ Done |

### Area F — Legacy Komoot Decoupling
| Task | Status |
|------|--------|
| F1: Remove Komoot columns from User model | ✅ Already clean |
| F2: Generalize SyncRule.direction constraint (migration 010) | ✅ Done |
| F3: Platform-agnostic /sync/status | ✅ Done |
| F4: Deprecate POST /sync/rebuild-history (returns 410) | ✅ Done |
| F5: Extend SyncedActivity.source constraint (migration 010) | ✅ Done |
| F6: Platform-agnostic rule engine | ✅ Done |

---

## 📦 Migration Chain

```
001_initial_schema
002_add_connections_and_pipelines
003_drop_legacy_user_columns
004_add_user_name
005_add_activity_source
006_add_gpx_data
007_multi_destination_sync
008_connection_sync_state
009_add_gpx_storage_key
010_extend_source_and_direction_constraints   ← F5 + F2
011_add_user_audit_log                         ← C5
```

Run `make migrate` to apply all pending migrations on a fresh DB.

---

## ✅ FULLY IMPLEMENTED (end-to-end, tested)

### Backend API Endpoints
| Area | Endpoints | Notes |
|---|---|---|
| Auth | POST /register, /login, /refresh, GET /me, PATCH /me | JWT, bcrypt; register/strava/komoot/disconnect/account-delete all write UserAuditLog |
| Social Auth | GET /auth/google, /google/callback, /auth/github, /github/callback | CSRF state cookie |
| Strava OAuth | GET /strava/login, POST /strava/callback, DELETE /strava/disconnect | Multi-app routing via pick_least_loaded_app |
| Komoot credentials | POST /auth/komoot, DELETE /auth/komoot/disconnect | Fernet-encrypted in Connection table |
| Account | DELETE /auth/account | Cascade: purge S3 blobs → delete User row (ON DELETE CASCADE) → audit log survives with user_id=NULL |
| Sync | GET /sync/status, POST /sync/trigger | Platform-agnostic; ConnectionSyncState watermarks |
| Activities | GET /activities, /activities/ids, GET /activities/{id}, DELETE /activities/{id} | Pagination, filtering, GPX purge on delete |
| GPX Download | GET /activities/{id}/gpx | Presigned URL redirect (cloud) or stream from DB column (self-hosted) |
| GPX Import | POST /activities/import, /activities/seed | Dual-write: S3 key or gpx_data column |
| Export | GET /export/me | GDPR Art.20 JSON archive; writes export_requested audit |
| Rules | CRUD /rules | Tier enforcement; direction validated via regex `^[a-z_]+_to_[a-z_]+$` |
| API Keys | CRUD /api-keys | Pro only; writes api_key_created/revoked audit |
| Billing | GET /billing/status, POST /billing/checkout, /portal | Stripe |
| Webhooks | POST /webhooks/strava, /webhooks/stripe | Verified, tested |
| Connections | CRUD /connections | Encrypted credentials blob |
| Pipelines | CRUD /pipelines, POST /pipelines/{id}/sync | Full CRUD + ARQ trigger |
| Instance | GET /api/v1/instance | DEPLOYMENT_MODE, feature flags |

### ARQ Background Jobs
| Job | Status |
|---|---|
| `poll_user_sources` | Phase A: ingests Komoot + Strava via ConnectionSyncState watermarks; Phase B: pushes un-synced activities |
| `process_strava_activity` | Real-time Strava webhook → hub ingestion |
| `source_poll_scheduler` | Cron every 5 min; budget-aware across all active StravaApps |
| `sync_gpx_to_strava` | GPX → Strava upload |
| `sync_activity_to_komoot` | GPX → Komoot upload |
| `run_pipeline` | Komoot→Strava, Komoot/Strava→Intervals.icu, Komoot/Strava→Runalyze |

### New Services / Models Added This Session
| Module | Purpose |
|--------|---------|
| `app/services/storage.py` | S3-compatible GPX blob storage (put/get/delete/presigned_url) |
| `app/services/audit.py` | `write_audit()` helper — non-blocking UserAuditLog writer |
| `app/db/models/audit.py` | `UserAuditLog` model — ON DELETE SET NULL for GDPR compliance |
| `app/db/models/sync.py` | `ConnectionSyncState` added; source + direction constraints updated |

---

## ⚠️ REMAINING / DEFERRED WORK

| Item | Priority | Notes |
|------|----------|-------|
| D1–D8: Coolify/Hetzner deployment | HIGH (pre-launch) | Manual infra setup; see D9 env var reference in IMPLEMENTATION_PLAN.md |
| A5-ph2: Drop gpx_data column | Medium | After A5-ph1 is live for ≥2 deploys and all rows migrated |
| B4: Frontend instance-aware UI | Low | Hide cloud-only features in self-hosted mode |
| Outbound webhooks backend | Medium | `WebhookSubscription` model exists; no dispatch logic yet |
| Test coverage: run_pipeline handlers | Medium | No tests for Intervals.icu/Runalyze pipeline execution |
| Garmin: dedicated garmin_activity_id column | Low | Currently piggybacking `komoot_tour_id` as `garmin_<id>`; clean up with migration once E6 is live |

---

## 🧪 Test Coverage

103 tests passing across:
- `test_activities.py`, `test_activities_import.py`
- `test_activity_record.py` (new — ActivityRecord, _match_condition, _apply_action, platform converters)
- `test_api_keys.py`, `test_auth.py`, `test_auth_accounts.py`, `test_auth_disconnect.py`, `test_auth_social.py`
- `test_billing.py`, `test_connections.py`, `test_pipelines.py`
- `test_integration.py` (full workflow: register → connect → sync → activities → rules → billing → webhooks)
- `test_rules.py`, `test_sync.py`, `test_sync_jobs.py`, `test_sync_status.py`, `test_webhooks.py`

Still missing: `run_pipeline` job execution, `IntervalsIcuClient`, `RunalyzeClient`, end-to-end Garmin ingest.

---

## 🐛 Notable Fixes This Session

| Issue | Fix |
|-------|-----|
| `FakeStravaAppResult` missing `.scalars()` | Updated test to support new A4 multi-app query pattern |
| `FakeDB` missing `.flush()` in api_keys test | Added flush() and type-filtered list query to prevent UserAuditLog polluting ApiKey list |
| `daily_count` undefined in sync_jobs.py | Removed stale format arg from scheduler logger.info call |
| Migration numbering conflict (A5-ph1 vs E5 both wanted 008) | A5-ph1 became 009; combined F2+F5 into 010 |
| SQLite incompatibility with Postgres `~` regex in CHECK constraint | SyncRule model uses SQLite-safe LIKE pattern; migration uses Postgres regex |

---

## 🏗️ Object Storage (A5-ph1)

**Config**: `STORAGE_BACKEND=db` (default, self-hosted) or `s3`/`r2` (cloud).

When `STORAGE_BACKEND != "db"`:
- `POST /activities/import` → upload to S3, set `gpx_storage_key`, clear `gpx_data`
- `GET /activities/{id}/gpx` → generate presigned URL (5 min TTL), return 302 redirect
- `DELETE /activities/{id}` → purge S3 blob before DB delete
- `DELETE /auth/account` → bulk-purge all user's S3 blobs before cascade delete

Bucket must be private + server-side encrypted. Key pattern: `gpx/{user_id}/{activity_id}.gpx`.

---

## 🔐 UserAuditLog (C5)

Actions logged: `account_created`, `account_deleted`, `strava_connected`, `strava_disconnected`,
`komoot_connected`, `komoot_disconnected`, `api_key_created`, `api_key_revoked`, `export_requested`.

- FK `user_id` → `users.id` ON DELETE SET NULL — rows survive account deletion for compliance.
- `write_audit()` is non-blocking: catches and logs any DB errors without aborting the primary operation.
- IP extracted from `X-Forwarded-For` header (proxy-aware) or `request.client.host`.

---

## 🏃 Garmin Connect Source (E6) + Platform-Agnostic Rule Engine (F6)

### ActivityRecord (`app/services/activity_record.py`)
Platform-agnostic dataclass used by the rule engine. Fields mirror `SyncedActivity` where possible.
Converters: `_komoot_tour_to_record(tour)` and `_garmin_activity_to_record(activity_dict)` in `sync.py`.

### Rule Engine
`_match_condition(record: ActivityRecord, conditions: dict)` and `_apply_action(record, actions, user)` now operate on `ActivityRecord` instead of `Tour`. Condition keys supported: `sport_type`, `sport` (alias), `distance_km`, `elevation_m`, `name_contains`. Existing stored rule JSON format is fully preserved.

### GarminClient (`app/services/garmin.py`)
Wraps `garminconnect` SDK via `asyncio.to_thread`. Lazy login on first use. Methods: `get_activities_since(since, limit=100)`, `download_gpx(activity_id)`. Requires `garminconnect>=0.2.0` in requirements.txt.

### DB storage for Garmin
Garmin activities are stored as `source="garmin"`, re-using `komoot_tour_id` as `garmin_<activityId>` to avoid a schema migration until a dedicated column is added. This is a known shortcut — add a `garmin_activity_id` column (new migration) when Garmin ships publicly.

### Credentials format (Garmin Connection)
```json
{"email": "user@example.com", "password": "<encrypted>"}
```
Same Fernet-encrypted credentials blob in the `Connection` table as Komoot.

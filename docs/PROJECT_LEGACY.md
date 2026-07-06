# RoutePass — Project Overview & AI Handoff

> Living document for the project. Read this first when picking up work with any AI tool (Claude Code, Gemini, Codex). Keep it up to date as you implement features.
> Repository was formerly `routepass`. Brand name is now **RoutePass**.

---

## Brand & Domain

| Item | Value |
|------|-------|
| Product name | **RoutePass** |
| Domain | **routepass.online** (registered 2025-04; .io was available but ~5× more expensive — .online chosen for cost) |
| Tagline | *Your routes, everywhere you train* |
| Design system | See `DESIGN.md` |

---

## Project Goal

Build a **dual-mode platform** that automatically syncs Komoot activities to Strava:

1. **Self-hosted standalone tool** (`/app`) — single-user, single Docker container, MIT open source, zero infra. Already fully working.
2. **SaaS backend** (`/backend`) — multi-tenant FastAPI service with PostgreSQL, Redis, Stripe subscriptions, and feature-gating by tier. Being built now.

Both modes can run the `/frontend` Next.js dashboard (not yet started). A self-hosted user can run the full stack with a license key for premium features.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  Self-Hosted Tool                   │
│  /app — Python, SQLite, APScheduler, single user    │
│  docker-compose.yml + Dockerfile                    │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│               SaaS / Self-Hosted Premium            │
│  /backend — FastAPI + PostgreSQL + Redis + ARQ      │
│  /frontend — Next.js dashboard (not started)        │
│  docker-compose.saas.yml           (SaaS)           │
│  docker-compose.selfhosted.yml     (self-hosted)    │
└─────────────────────────────────────────────────────┘
```

### Backend Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI (async) + Uvicorn |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Database | PostgreSQL 16 |
| Migrations | Alembic |
| Queue / cache | Redis 7 + ARQ |
| Auth | JWT (python-jose) + API keys (SHA-256) |
| Encryption | Fernet (cryptography) — Komoot creds + Strava tokens |
| Payments | Stripe |
| HTTP clients | httpx (async) |
| Config | pydantic-settings BaseSettings |
| Testing | pytest + pytest-asyncio + respx |

---

## Implementation Status

### `/app` — Standalone Worker ✅ Feature Complete

- Komoot→Strava sync (polling every N minutes via APScheduler)
- 44 Komoot sport types → Strava `sport_type` mapping
- Komoot unofficial API (`api/v007`), Basic Auth, paginated tour fetch + GPX download
- Strava OAuth token refresh, GPX upload, upload status polling, `hide_from_home=true`
- Duplicate prevention: SQLite `synced_activities` table + Strava `external_id=komoot_{id}`
- Health check HTTP server on :8080 for Docker
- DockerHub CI/CD via GitHub Actions

### `/backend` — SaaS Backend ✅ Core Complete, Frontend Not Started

**`make check` passes: 20/20 tests green, ruff lint clean.**

**Implemented and tested:**
- FastAPI app factory with async lifespan (Redis + ARQ pool)
- All API v1 routes: auth, sync, activities, rules, billing, webhooks, api_keys
- `services/komoot.py` — async Komoot client, tour pagination, GPX download
- `services/strava.py` — async Strava client, upload+poll, token refresh
- `services/sync.py` — SyncService (Komoot→Strava per user, rule evaluation)
- `jobs/worker.py` — ARQ WorkerSettings, 5-min cron scheduler
- `jobs/sync_jobs.py` — `poll_komoot_user`, `process_strava_activity`, `komoot_poll_scheduler`
- Alembic migration `001_initial_schema.py`
- 20 pytest tests covering all major routes and the sync engine
- Makefile with `make check`, `make dev`, `make migrate`, etc.

**Not yet started:**

| Component | Status |
|-----------|--------|
| `/frontend` | ❌ Next.js not started |
| Migration validation | ⚠️ Not validated against real PostgreSQL yet |
| Multi-app Strava pooling | ⚠️ `strava_apps` table exists, logic not implemented |
| Integration tests (real DB) | ⚠️ All tests mock the DB |

### Database Models

See `backend/app/db/models/` — all tables are defined:
- `users` — multi-tenant, encrypted Komoot creds, sync prefs, poll scheduling
- `strava_tokens` — per-user, encrypted, linked to `strava_apps`
- `strava_apps` — multi-app pooling support (for Strava rate limit scaling)
- `subscriptions` — Stripe-linked, tier (free/pro/business), period counters
- `api_keys` — hashed SHA-256, prefix for display, revocation
- `webhook_subscriptions` + `notification_settings` — user notification prefs
- `license_cache` — for self-hosted license validation with grace period
- `synced_activities` — sync history with direction, status, conflict tracking
- `user_sync_state` — per-user polling cursors
- `sync_rules` — user-defined filter rules (Pro+, conditions/actions as JSON)
- `job_audit_log` — every ARQ job with status, timestamps, errors

---

## API Constraints & Capacity Analysis

### Komoot API — Fragile Foundation

- **Unofficial** `https://www.komoot.de/api/v007` — reverse-engineered, no public API exists
- **Auth**: HTTP Basic (email + password) — each user's credentials encrypted with Fernet before storage
- **No webhooks** — polling only. Poll interval configurable per user (`komoot_poll_interval_min`)
- **Rate limits**: Undocumented. Use exponential retry (3 attempts, backoff on 429/5xx).
- **IP-block risk for cloud SaaS**: All polls originate from your server IPs.
  - 100 users polling every 30 min → ~3 req/min from one IP (probably fine)
  - 500 users → ~17 req/min (possible flags)
  - 1000+ users → ~33 req/min (real block risk)
  - Mitigation: jitter poll times, stagger by user ID hash, use multiple egress IPs if needed
- **Self-hosters have no IP-block risk** — each polls from their own home/VPS IP with their own credentials
- **Stability risk**: `v007` has changed before. Keep the API client abstracted so the base URL can be updated in config without code changes. Monitor for elevated error rates.
- **Terms**: Unofficial use violates Komoot ToS. Disclose in docs. Acceptable at small scale; becomes a liability if service becomes prominent enough for Komoot to notice.

### Strava API — Shared Rate Limit Is the Core Scaling Constraint

- **Rate limits**: 100 req/15min + 1,000 req/day **per registered Strava app** — shared across ALL users of that app
- **API calls per Komoot→Strava sync**:
  - 1× `POST /uploads` (upload GPX)
  - 2–3× `GET /uploads/{id}` (poll until activity created — avg 2–3 polls)
  - 1× `PUT /activities/{id}` (set `hide_from_home`)
  - ~0.1× token refresh (amortized — Strava access tokens last 6 hours)
  - **Total: ~4.5 calls per activity synced**
- **Daily capacity** (950 usable calls with headroom): **~210 syncs/day per Strava app**
- **Scaling trigger**: Assume 30% of registered users sync 1 activity/day (realistic average including inactive users). A single Strava app safely serves **~150–200 registered cloud users** before a second app is needed.
- **Second Strava app**: Free to register, but requires a second Strava account. Multi-app round-robin pooling is designed for (`strava_apps` table exists) but not yet implemented.
- **All Strava calls MUST route through `RateLimitGuard`** (`backend/app/core/rate_limit.py`)
- **Free tier suspension**: When daily budget > 800, free-tier sync jobs are skipped (150 calls reserved for Pro users)
- **Webhook**: 1 push subscription per Strava app → all athlete events → route by `owner_id` → `strava_tokens.strava_athlete_id`
- **Token refresh**: implemented in worker paths before Strava API calls; auth callback now stores Strava tokens encrypted with Fernet
- **Initial migration**: rewritten to track the current ORM model layout much more closely; next step is validating it against a real clean PostgreSQL database
- **Visibility**: Cannot set `visibility='only_me'` via API. Only `hide_from_home=true` is available — document this limitation clearly for users.
- **Upload**: GPX only. `external_id=komoot_{tour_id}` prevents Strava-side duplicates automatically.
- **Terms**: Compliant — third-party integrations are explicitly allowed.

### Infrastructure Costs

| Registered cloud users | Setup | Est. monthly (Hetzner) |
|------------------------|-------|------------------------|
| 0–200 | 1× CX21 VPS (2vCPU/4GB RAM) | ~€12–18 |
| 200–1000 | Separate CX31 DB + CX21 app server + Redis | ~€35–60 |
| 1000–5000 | Managed PostgreSQL (DBaaS) + 2× app + LB | ~€80–150 |
| 5000+ | Full managed stack, multi-region | ~€200–400 |

GPX file storage: ~100KB avg per activity × 200 activities/year × 1000 users = ~20GB/year. Negligible (Hetzner Object Storage: €5/month per TB).

**Break-even at €/$/29 per year Pro pricing (roughly equivalent):**

| Paying users | ARR | Monthly cost | Monthly profit |
|-------------|-----|-------------|----------------|
| 7 | $200 | €15 | ~$0 (break-even) |
| 50 | $1,450 | €15 | ~$105/mo |
| 200 | $5,800 | €35 | ~$445/mo |
| 500 | $14,500 | €60 | ~$1,150/mo |
| 1000 | $29,000 | €100 | ~$2,320/mo |

This is a micro-SaaS with very low cost structure. Profitability starts at ~50 paying users.

### Subscription Tiers — Two Only

```
free  = 0  (basic sync, batch delay, 1 rule, 30-day initial history)
pro   = 1  (near-realtime sync, 5 rules, 12-month history, extra integrations)
```

**No "business" tier.** The target audience (recreational cyclists and hikers) has no corporate or team use case worth productising separately. Adding a third tier creates confusion without revenue upside.

Tier enforced via `require_tier("pro")` FastAPI dependency → HTTP 402.

### Self-Hosted — No License Key Required

**Decision: drop the self-hosted paid license entirely.**

Self-hosters provide their own Strava API credentials (bypassing shared rate limits) and poll Komoot from their own IPs (bypassing cloud IP-block risk). They are net-positive for the project, not lost revenue. Charging them creates resentment, is nearly unenforceable under AGPL, and alienates the technical community whose blog posts drive cloud signups.

- `/app` standalone → MIT, free forever, single user
- `/backend` full stack → AGPL v3, free for personal/household use (no user cap restriction enforced)
- Commercial use (running as a paid service for others) → AGPL requires open-sourcing modifications OR purchase a commercial exception license from you

---

## Routes to Implement (`backend/app/api/v1/`)

```
auth.py
  POST   /auth/register                — email/password signup  ✅
  POST   /auth/login                   — return JWT  ✅
  POST   /auth/refresh                 — refresh JWT  ✅
  GET    /auth/strava/connect          — redirect to Strava OAuth
  GET    /auth/strava/callback         — exchange code, store encrypted token
  DELETE /auth/strava/disconnect       — remove Strava connection  ✅
  POST   /auth/komoot/connect          — store encrypted Komoot credentials
  DELETE /auth/komoot/disconnect       ✅

sync.py
  GET    /sync/status                  — UserSyncState + last activity  ✅
  POST   /sync/trigger                 — manual sync (enqueue ARQ job)  ✅

activities.py
  GET    /activities                   — paginated list (user-scoped)  ✅
  GET    /activities/{id}             — activity detail  ✅
  GET    /activities/{id}/gpx         — download GPX  ✅

rules.py  (Pro+)
  GET    /rules                        — list sync rules  ✅
  POST   /rules                        — create rule  ✅
  PUT    /rules/{id}                   — update rule  ✅
  DELETE /rules/{id}                   — delete rule  ✅

billing.py
  GET    /billing/subscription         — current subscription info  ✅
  POST   /billing/checkout             — Stripe checkout session  ✅
  POST   /billing/portal              — Stripe customer portal session  ✅

webhooks.py
  GET    /webhooks/strava              — Strava webhook validation (hub.challenge)
  POST   /webhooks/strava             — Strava push event handler
  POST   /webhooks/stripe             — Stripe event handler

api_keys.py  (Pro+)
  GET    /api-keys                     — list API keys  ✅
  POST   /api-keys                     — create key (returns raw key once)  ✅
  DELETE /api-keys/{id}               — revoke key  ✅
```

---

## Implementation Phases

### Phase 1 — Make Backend Startable ✅ Done
### Phase 2 — Auth & Connections ✅ Done
### Phase 3 — Sync Engine ✅ Done
### Phase 4 — Activities & Billing ✅ Done
### Phase 5 — Pro Features ✅ Done (rules, api_keys); Frontend ❌ Not started

### Phase 6 — Next: Testing & Hardening
- [ ] Validate Alembic migration against a real PostgreSQL database (`make migrate`)
- [ ] Integration tests with a real test DB (pytest + testcontainers or docker-compose.test.yml)
- [ ] Rate limit guard behavior under load
- [ ] Multi-app Strava pooling logic (round-robin across `strava_apps` table)

<<<<<<< Updated upstream
### Phase 7 — Frontend
- [ ] Next.js scaffold (`/frontend`)
- [ ] Dashboard: connection status, sync history, manual trigger
- [ ] Settings: Komoot/Strava connect/disconnect, sync prefs
- [ ] Billing: upgrade/downgrade via Stripe Checkout/Portal
- [ ] Rules editor (Pro)
=======
### Phase 3 — Sync Engine
- [ ] `backend/app/jobs/worker.py` — ARQ WorkerSettings, cron for `komoot_poll_scheduler`
- [ ] `backend/app/jobs/sync_jobs.py` — `poll_komoot_user`, `komoot_poll_scheduler`
- [ ] `backend/app/services/sync.py` — SyncService (orchestrates komoot→strava per user)
- [ ] `sync.py` routes: status, trigger

### Phase 4 — Activities & Billing
- [ ] `activities.py` routes
- [ ] `webhooks.py` — Strava push events + Stripe
- [ ] `billing.py` — Stripe checkout + portal + subscription status

### Phase 5 — Pro Features + Frontend
- [x] `rules.py` — sync rules CRUD ✅
- [x] `api_keys.py` — API key management ✅
- [ ] Next.js frontend scaffold (`/frontend`)
- [ ] License server (minimal service for self-hosted validation)

### Phase 6 — Platform Integrations (Intervals.icu + Runalyze)

**Intervals.icu**
- [ ] `backend/app/services/intervals.py` — async client; `push_activity(api_key, athlete_id, activity_data)` via `POST /api/v1/athlete/{id}/activities`
- [ ] `intervals_icu_api_key_encrypted` + `intervals_icu_athlete_id` columns on `users` (new migration)
- [ ] `/auth/intervals/connect` — store encrypted API key + athlete ID
- [ ] `/auth/intervals/disconnect`
- [ ] Sync job step: after Komoot→Strava upload completes, push to Intervals if user connected
- [ ] `sync_direction` values extended: `komoot_to_intervals`, `strava_to_intervals`

**Runalyze**
- [ ] `backend/app/services/runalyze.py` — async client; `push_activity(token, gpx_bytes)` via `POST /api/v1/activity` (multipart GPX upload)
- [ ] `runalyze_token_encrypted` column on `users` (same migration as above)
- [ ] `/auth/runalyze/connect` — store encrypted personal access token
- [ ] `/auth/runalyze/disconnect`
- [ ] Sync job step: push GPX to Runalyze after Komoot download, if user connected

### Phase 7 — Platform Integrations (Polar + Outdooractive)

**Polar AccessLink** (OAuth 2.0, webhook-driven — no polling needed)
- [ ] `backend/app/services/polar.py` — async client; list exercises, download FIT/GPX
- [ ] `polar_tokens` DB table: `user_id`, `access_token_encrypted`, `refresh_token_encrypted`, `expires_at`, `polar_user_id`
- [ ] Alembic migration for `polar_tokens`
- [ ] `/auth/polar/connect` → redirect to Polar OAuth → `/auth/polar/callback`
- [ ] `/auth/polar/disconnect`
- [ ] `/webhooks/polar` — receive exercise push events, enqueue `process_polar_exercise` ARQ job
- [ ] `process_polar_exercise` job — fetch exercise → upload to Strava + optionally Intervals/Runalyze
- [ ] Register Polar webhook on app startup (`POST /v3/webhooks`)
- [ ] Polar → Strava sport type mapping (exercise sport → Strava `sport_type`)

**Outdooractive** (OAuth 2.0, polled like Komoot)
- [ ] `backend/app/services/outdooractive.py` — async client; search/fetch routes and recorded activities
- [ ] `outdooractive_tokens` DB table (same pattern as `polar_tokens`)
- [ ] Alembic migration for `outdooractive_tokens`
- [ ] `/auth/outdooractive/connect` → `/auth/outdooractive/callback`
- [ ] `/auth/outdooractive/disconnect`
- [ ] `poll_outdooractive_user` ARQ job — same structure as `poll_komoot_user`
- [ ] Scheduler handles Outdooractive polls alongside Komoot polls (shared budget awareness)
- [ ] Outdooractive → Strava sport type mapping

### Phase 8 — Testing & Hardening
- [x] Integration tests (pytest-asyncio, real test DB) ✅
- [ ] Rate limit behaviour under load
- [ ] Multi-app Strava pooling logic
- [ ] Integration tests for Intervals.icu and Runalyze push paths
- [ ] Polar webhook signature verification
- [ ] Outdooractive OAuth flow end-to-end test
>>>>>>> Stashed changes

---

## For AI Agents: Quick Start

Read these files in order before writing any code:

1. **This file** (`PROJECT.md`) — goals, status, decisions
2. `DESIGN.md` — design system, color/font/component tokens, frontend file structure, implementation plan
3. `backend/CLAUDE.md` — compact backend reference with patterns, DB conventions, code templates
4. `AI_HANDOFF.md` — the most current handoff state and recent fixes
5. `CODEX.md` — Codex-specific workflow guardrails
6. `backend/.env.example` — all environment variables, if present in your branch
7. `backend/app/db/models/` — actual schema (3 files)
8. `backend/app/api/deps.py` — auth dependencies pattern

Important: `PROJECT.md`, `AI_HANDOFF.md`, and the actual code may diverge. Treat the code as source of truth when they conflict.

### Key Patterns

```python
# All endpoints: require JWT
user: User = Depends(get_current_user)

# Premium endpoints: require tier
_: None = Depends(require_tier("pro"))

# All Strava API calls: go through rate guard
await rate_limit_guard.call(app_id, user.subscription.tier, fn, *args)

# DB queries: async SQLAlchemy 2.0
result = await db.execute(select(Model).where(Model.user_id == user.id))
row = result.scalar_one_or_none()
```

### Encryption
```python
from app.core.security import encrypt, decrypt
# Komoot password before storing:
user.komoot_password_encrypted = encrypt(raw_password)
# Reading back:
password = decrypt(user.komoot_password_encrypted)
```

---

## Business Model & Subscription Design

### Who the Customer Actually Is

This is a **micro-SaaS** serving a narrow, specific pain: European outdoor athletes (primarily cyclists, secondarily hikers) who use Komoot for route planning and navigation but track fitness on Strava, and want activities to appear on both platforms without manually exporting GPX files after every ride.

**Market size reality check:**
- Komoot: ~40M registered, ~2–5M active, strong in Germany/Netherlands/Austria/Switzerland
- Strava overlap: ~500K–1M users actively on both platforms
- Frustrated enough to seek a sync tool: ~50K–150K
- Would actually pay for a cloud solution: ~2K–8K realistic (1–5% conversion)
- This is **indie developer / hobby SaaS** scale, not VC territory

**Three distinct customer segments:**

**A — Weekend Cyclist (80% of users, primary target)**
- 2–4 rides/week, often 50–150km routes
- Plans on Komoot, social life on Strava (segments, KOMs, club feed)
- Device: phone or Garmin/Wahoo with Komoot loaded
- Pain: 5–10 min manual GPX export ritual breaks post-ride flow
- Already pays: Strava Summit (~$80/yr), Komoot (~€50/yr), possibly Garmin Connect+
- **Willingness to pay: $20–30/year.** At $40+ they hesitate — too many fitness subscriptions already.
- **Top need**: reliability + speed. Wants activity on Strava within 30 min. Doesn't need complex rules.

**B — Hiker (15% of users)**
- 1–4 hikes/month, seasonal
- Less tech-savvy, less Strava-dependent
- **Willingness to pay: $10–20/year max.** Rarely needs rules or fast sync.
- Top need: it just works.

**C — Self-Hoster / Developer (5% of users, high community value)**
- Privacy-conscious, runs Docker at home or on a VPS
- Would rather spend 2 hours setting up than pay $5/month
- **Will not pay for cloud.** Invaluable for bug reports, PRs, word-of-mouth.
- Top need: full control, no third party holding credentials.

---

### Licensing Strategy — One Repository, Split Licenses

- `/app` (standalone worker) → **MIT** — already published, free forever, single user, no dashboard
- `/backend` + `/frontend` → **AGPL v3**

AGPL: source code fully public (important for trust when storing fitness credentials). Anyone can self-host for personal/household use at no cost. Running it as a competing commercial SaaS requires a commercial license from you. Self-hosters who strip the `require_tier()` gate are modifying AGPL-licensed code — they're not lost revenue anyway.

**Why not two repos:** Divergence is expensive. Open-core in one repo is the industry standard (Nextcloud, Plausible, Matomo). Why not BSL/FSL: AGPL is better understood by developers, doesn't expire or convert, and the audience respects it.

---

### Deployment Modes

```
MODE 1 — Standalone (/app, MIT)
  Single user, env-var config, no dashboard, SQLite
  Free forever. Serves the self-hoster who just wants sync to work.

MODE 2 — Self-Hosted Full Stack (/backend + /frontend, AGPL)
  Personal/household use: all features, no license key, no restriction
  Bring your own Strava app credentials → no shared rate limit impact
  Bring your own IPs → no Komoot IP-block risk
  For commercial use of AGPL code: purchase a commercial exception

MODE 3 — Cloud (Stripe subscription)
  Hosted by you. This is where revenue comes from.
  Free tier + Pro tier.
```

---

### Feature Matrix

| Feature | Standalone | Self-Hosted | Cloud Free | Cloud Pro |
|---------|:---:|:---:|:---:|:---:|
| Komoot → Strava sync | ✅ | ✅ | ✅ | ✅ |
| 44 sport type mappings | ✅ | ✅ | ✅ | ✅ |
| Duplicate prevention | ✅ | ✅ | ✅ | ✅ |
| `hide_from_home` default | ✅ | ✅ | ✅ | ✅ |
| Dashboard UI | — | ✅ | ✅ | ✅ |
| Initial history sync | 30 days | unlimited | 30 days | **12 months** |
| Sync speed | every 30 min | configurable | ~2 hour batch | **~10 min** |
| Custom sync rules | — | ✅ (unlimited) | 1 rule | **5 rules** |
| Strava → Komoot (experimental) | — | ✅ | — | ✅ |
| Intervals.icu push | — | ✅ | — | ✅ |
| Runalyze push | — | ✅ | — | ✅ |
| Polar pull (Phase 3) | — | ✅ | — | ✅ |
| Outdooractive pull (Phase 3) | — | ✅ | — | ✅ |
| Activity history in dashboard | — | unlimited | 30 days | 12 months |
| Email support | — | — | — | ✅ |

**Key insight on self-hosted:** Self-hosters get *everything* with no restriction. This is intentional — they provide their own infrastructure and API credentials, removing cost and risk from your side. They are your best advocates, not your lost revenue.

**The two upgrade motivators for cloud users:**
1. **Sync speed** — "I finished my ride and want it on Strava while I'm still at the coffee shop" (emotional urgency)
2. **Historical sync** — "Sync my 3 years of Komoot activities" (one-time but compelling for new sign-ups)

Everything else (rules, integrations) is secondary for the core audience.

---

### Pricing

**Cloud Free:** No payment, no time limit.
- Komoot → Strava sync
- Batch every ~2 hours (acceptable for most users; creates clear upgrade motivation)
- Last 30 days synced on initial setup
- 1 custom rule (enough for simple use cases, creates upgrade path for power users)
- Dashboard access

**Cloud Pro: $3.49/month or $29/year** (~30% annual discount)
- Sync within ~10 minutes of activity upload
- Initial historical sync: 12 months back
- Up to 5 custom rules
- Strava → Komoot bidirectional (experimental)
- Intervals.icu + Runalyze integration
- Email support

**Lifetime option: $79 one-time** (optional, cap at ~200 slots)
- All Pro features, forever
- Good for early adopters who hate subscriptions; generates upfront cash

**Why $29/year and not $39:**
Tapiriik charges $2/year and has steady signups — proves willingness to pay is real but price-sensitive. At $39/year the casual cyclist pauses; at $29 it's an impulse buy comparable to a single Strava month. The annual price is also psychologically below the "$30/year" mental threshold in European markets.

**Why not a "business" tier:** No realistic business/team use case exists for this audience. A cycling club coach might share access but won't pay enterprise prices. Adding a third tier increases UI complexity and support overhead for near-zero revenue upside.

---

### Custom Sync Rules — Design

Rules stored in `sync_rules` as `conditions` (JSON) + `actions` (JSON). Evaluated in `rule_order`; first matching rule wins ("stop" semantics).

**Condition types:**
```
sport_type      — is / is_not  [list of Komoot sport types]
distance_km     — gt / lt / between
elevation_m     — gt / lt
duration_min    — gt / lt
name_contains   — string, case-insensitive
```

**Action types:**
```
skip                 — do not sync this activity
set_sport_type       — override Strava sport_type
name_template        — "{name} · {distance:.0f}km · {elevation}m↑"
append_description   — append text/hashtags after Komoot description
set_hide_from_home   — true / false override
```

**Most common use cases (built as dashboard presets):**
- "Skip indoor activities" → `sport_type is [yoga, indoor_cycling]` → `skip`
- "Only sync rides >10km" → `sport_type is [cycling, *] AND distance_km lt 10` → `skip`
- "Add Komoot attribution" → any → `append_description: "📍 Komoot tour"`
- "Fix hiking sport type" → `sport_type is [hike]` → `set_sport_type: Hike`

---

### Third-Party Integration Roadmap

Priority: no-approval APIs first, EU audience alignment, unique value (not already covered by native platform integrations).

**Now (core product):**
- ✅ Komoot → Strava (standalone, working)
- 🔲 Strava → Komoot (reverse, experimental, Pro-only, uses unofficial Komoot write API)

**Phase 2 — Pro integrations (build after cloud launch):**
- 🔲 **Intervals.icu** — open personal API, no approval, API key auth. Push activities from Komoot/Strava → Intervals for training load analysis. ~1 req/sec safe, no daily cap. Huge EU cycling overlap.
- 🔲 **Runalyze** — personal API token (user must have supporter tier, €1–2/mo). Push activities → Runalyze. 30 req/min limit. German platform, directly overlaps with Komoot's home market.

**Phase 3 — Approval-required (build only after product-market fit):**
- 🔲 **Polar AccessLink** — any developer can register at developer.polar.com, no gating. OAuth 2.0. Webhook push (no polling needed). 50 req/15min/user. Pull Polar activities → Strava/Komoot. Strong in Scandinavia and among triathletes.
- 🔲 **Outdooractive** — register + approval, free tier 100 req/min. Pull routes/activities as a Komoot alternative. Adding this lets the product market as "any route app → Strava" rather than Komoot-only — significant TAM expansion.
- 🔲 **Garmin Connect** — developer approval (slow, enterprise-geared). OAuth 1.0a (legacy). Unique value is Garmin → Komoot only — most Garmin users already have native Strava sync. Low priority.
- 🔲 **Wahoo** — partnership required. Skip.
- 🔲 **TrainingPeaks** — commercial partnership only. Skip until scale justifies it.

**Integration architecture (shared pattern for all new sources/destinations):**
Each integration follows the same three-layer pattern:
1. `backend/app/services/{platform}.py` — async client (httpx), auth handling, data fetch/push
2. `backend/app/api/v1/auth.py` — connect/disconnect routes (`/auth/{platform}/connect`, `/auth/{platform}/callback` for OAuth)
3. DB model — `{platform}_tokens` table (OAuth) or encrypted API key column on `users`

**Rate limit summary for planning:**

| Platform | Limit | Type | Notes |
|----------|-------|------|-------|
| Strava | 100/15min + 1000/day | Per app (shared) | Critical constraint |
| Komoot | Undocumented | Per IP | IP-block risk at scale |
| Intervals.icu | ~1 req/sec | Per key | Generous, no daily cap |
| Runalyze | 30 req/min | Per token | User must have supporter tier |
| Polar | 50 req/15min | Per user | Has webhooks (efficient) |
| Outdooractive | 100 req/min | Per app | Partner agreement for high volume |

---

## Decision Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-04 | Use ARQ (not Celery) for job queue | Async-native, Redis-only, simpler |
| 2026-04 | Fernet for credential encryption | Symmetric, reversible (needed to pass creds to Komoot), well-audited |
| 2026-04 | Multi-app Strava architecture | 1000/day per-app limit forces pooling at scale |
| 2026-04 | `hide_from_home` only (not `visibility`) | Strava API removed `visibility=only_me` option |
| 2026-04 | SQLAlchemy 2.0 async | Clean async, modern API, compatible with FastAPI lifespan |
| 2026-04 | Enums as plain strings + CheckConstraint | Simpler migrations than Python Enum type |
| 2026-04 | UUID PKs everywhere | Avoids sequential ID enumeration in multi-tenant context |
| 2026-04 | AGPL v3 for backend (not BSL or MIT) | Community trust, auditable code, prevents competing SaaS, well-understood |
| 2026-04 | Self-hosted: no license key, all features free | Self-hosters aren't lost revenue; they bring own API creds + IPs, reducing your cost/risk |
| 2026-04 | Cloud Pro: $3.49/mo or $29/yr | Below the $30 impulse-buy threshold; Tapiriik proves willingness to pay in this niche |
| 2026-04 | No "business" tier | No realistic team/enterprise use case in this audience; complexity outweighs revenue |
| 2026-04 | Two upgrade motivators only: speed + history depth | The audience cares about reliability, not complex features |
| 2026-04 | 1 rule free, 5 rules Pro | Enough free to be useful (not crippled), clear upgrade path for power users |
| 2026-04 | Intervals.icu + Runalyze before Garmin/Wahoo | No approval needed; EU cycling audience overlap; Garmin already has native Strava sync |
| 2026-04 | Bidirectional sync is Pro-only | Uses unofficial Komoot write API — higher risk; used by a small subset of the audience |
| 2026-04 | Lifetime option at $79, cap ~200 slots | Early adopter reward, upfront cash flow, avoids lifetime cannibalising recurring revenue |

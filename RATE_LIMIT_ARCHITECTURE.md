# API Limit Management & Economic Governor — Architecture

Status: **plan** (Phase 1 in progress). Owner-facing internal design doc.

RoutePass depends on several third-party APIs with very different limits, costs and
reliability. This document defines how the app manages those limits **globally**
(admin-configured credentials, tiers and costs), how that automatically adjusts
**per-user** behaviour, and how the **economic governor** keeps API/infra cost from
ever exceeding revenue — while never applying any of it in the **self-hosted** build.

---

## 1. Goals

1. One **global, admin-editable** place to manage each provider's credentials, tier
   and limits (no code change / redeploy to raise Strava rates or add an app).
2. Those settings **automatically adjust** how often data is fetched, how much is
   imported, and how many users/connections are admitted — per user, by tier.
3. **Cost invariant:** API + infra cost must never exceed revenue. A flood of
   non-paying users degrades gracefully instead of running up cost or starving
   paying users.
4. **Self-hosted = unlimited:** none of the economic machinery applies; only the
   technical per-provider safety floors remain.
5. A **comprehensive admin dashboard** with economics, provider health, and
   per-user rate insight / analytics.

---

## 2. Current state (baseline)

- `app/core/rate_limit.py` — **Strava-only**, hardcoded (`WINDOW_15MIN_LIMIT=90`,
  `DAILY_LIMIT=950`, free suspended >800). Per-app Redis counters, multi-app pool
  (`strava_apps`) with least-loaded selection.
- `app/core/polling.py` — per-source poll intervals, **hardcoded** per platform.
- No rate limiting for Komoot / Garmin / intervals.icu / Runalyze.
- `/instance` is read-only from env; **no admin API**. `User.is_admin` exists but is
  unused for authorization (no `require_admin`).
- Tiers: free / pro / business; self-hosted unlocks all via `require_tier`.

Everything above is hardcoded in code — this doc moves it into an admin-editable,
revenue-aware system.

---

## 3. Provider limits & costs (researched, mid-2026)

| Provider | Role | Auth | Real limits | Webhooks | Money cost | Upgrade lever |
|---|---|---|---|---|---|---|
| **Strava** | source + dest | OAuth app pool | Default 200/15min · 2,000/day (overall); 100/15min · 1,000/day (non-upload). Upgraded (10 athletes): read 200/2,000, overall 400/4,000. Separate **read vs overall** buckets. | ✅ | **$11.99/mo per developer** (Standard); Extended = no sub | Sub + app count + review (→9,999) + Extended (10k+) |
| **Komoot** | source | email/pw (unofficial) | **None published, no webhooks**; ToS risk | ❌ | $0 | none (partner-only official API) |
| **Garmin** | source | unofficial SDK | **None published**; lockouts/MFA on abuse | ❌ (official ping only) | $0 unofficial / **$5,000** official Health API | go official ($5k + business) |
| **intervals.icu** | dest | API key | Per-day + per-15min + **10 req/s per IP**; `X-RateLimit-*`, 429 + Retry-After | n/a | $0 | none needed |
| **Runalyze** | dest | token | **No hard limit** (fair-use), token w/ expiry | n/a | $0 | none needed |

**Two key facts that shape the design:**

1. **The dominant cost (Strava) is flat/stepped, not per-request.** More free users
   can't literally run up a bill — but they can **exhaust the finite rate-limit /
   athlete budget** and degrade paying users.
2. **Strava's binding constraint is the athlete cap** (10 per self-managed app,
   9,999 after review), not requests. Connecting a Strava account consumes a scarce
   **slot**.

---

## 4. Two scarce resources, two invariants

| Resource | Nature | Managed by |
|---|---|---|
| **Money cost** | flat/stepped, provisioned by admin | Provisioning invariant |
| **Capacity** (requests + athlete slots) | finite, consumed per use | Allocation invariant |

- **Provisioning invariant:** never auto-add paid capacity (extra Strava app,
  Extended, Garmin official) beyond `revenue × coverage_target` (default 70%).
  Manual "invest ahead" override for the admin.
- **Allocation invariant:** free-tier usage is served only from capacity left after a
  reserved slice for paying users. When headroom hits zero, the free tier steps down
  a **degradation ladder** rather than overspending or starving paid users.

Together: more free users → slower / queued / gated, **never a bigger bill**.

---

## 5. Architecture

```
             ┌─────────────────────────────────────────────┐
   admin →   │  Registry: provider_policy + strava_apps +   │
             │  governor_config   (credentials, tier, cost) │
             └───────────────┬─────────────────────────────┘
                             │ (read)
             ┌───────────────▼─────────────────────────────┐
   cron+     │  Economic Governor (control loop)            │
   events →  │  cost vs revenue vs capacity → governor_state│
             │  → free_tier_level, reservations, admission  │
             └───────────────┬─────────────────────────────┘
                             │ (read)
       ┌─────────────────────▼───────────┐   ┌──────────────────────┐
       │ Generic RateLimiter (Redis)     │   │ Scheduler / workers  │
       │ per (platform, scope, bucket)   │   │ derive poll cadence, │
       │ read vs overall for Strava      │   │ backfill, admission  │
       └─────────────────────────────────┘   └──────────────────────┘
```

- **Registry** = source of truth for capacity + cost (admin-editable, DB-backed).
- **Governor** = turns revenue + capacity into a free-tier level + reservations.
- **Limiter + scheduler** = enforce it per request / per poll.
- All three are **bypassed in self-hosted**.

---

## 6. The economic governor

A small ARQ cron (~every 10 min) plus event hooks (Stripe subscription change, admin
config change, new connection) recomputes a cached `governor_state`:

```
monthly_cost    = Σ provider/app costs (Σ strava_apps.monthly_cost_cents, …) + infra
monthly_revenue = Σ active paid subscriptions (subscriptions table)
capacity        = Σ active credentials' request budgets + athlete slots
→ free_tier_level (0–5), paid_reservation, admission_open per provider
```

The limiter and scheduler only **read** `governor_state`.

### 6.1 Degradation ladder (free tier only; paid untouched)

| Level | Behaviour | UX |
|---|---|---|
| 0 Normal | full cadence + backfill | — |
| 1 Soft throttle | stretch free poll intervals (2h→6h→24h), smaller backfill, lower queue priority | subtle |
| 2 Deferred | free syncs run only in leftover / off-peak budget windows | "syncs may be delayed" |
| 3 Admission freeze | block **new** free Strava connections (slots near cap); rest of app works | waitlist / upgrade CTA |
| 4 Paused (read-only) | existing data visible; live sync paused | banner + upgrade CTA |

Never delete data or break the app; always explain *why* + offer upgrade. Paying
users sit above the ladder on reserved capacity.

### 6.2 Athlete-slot admission control (Strava)

- Reserve `paid_reservation_pct` of slots for paid users.
- Free slots exhausted → gate **new** free Strava connections; existing keep working;
  other providers still available.
- Admin decides: add app (+$11.99 / +10 slots), request review (→9,999), or Extended.

Example: 1 app = 10 slots, reserve 4 paid / 6 free. Break-even = **one** Pro sub.
50 free users → 6 get Strava now, rest use other providers / waitlist / upgrade; cost
stays $11.99.

### 6.3 Refresh & import policy (per provider, from registry)

- **Strava:** webhook-driven updates (no polling for changes); one bounded backfill on
  connect (`initial_backfill_limit`); dedup via unique constraints. Cheapest.
- **Komoot / Garmin:** poll on derived interval; incremental via `ConnectionSyncState`
  watermark; bounded backfill; **backoff + circuit-breaker** on errors (sets
  `Connection.status='error'`, surfaced in UI).
- **Re-import** only on Strava webhook `update`; never re-fetch history.
- **Import volume** = `initial_backfill_limit` + `page_size`, clamped by the user's
  per-tier daily budget.

---

## 7. Self-hosted bypass

`DEPLOYMENT_MODE == "selfhosted"` short-circuits the **entire** economic layer:

- No revenue accounting, no free/paid split, no degradation ladder, no admission.
- `require_tier` already unlocks all features.
- Poll intervals fall back to the **technical** per-provider minimums (rate-limit
  safety only — protects the self-hoster's own Strava app / avoids Komoot bans).
- Admin still configures credentials/tier/floors; just never throttled for money.

Single guard: one `if settings.DEPLOYMENT_MODE == "selfhosted": return UNLIMITED`.

---

## 8. Data model

**`provider_policy`** (one row per platform; admin-editable; seeded from current code):
`platform` (pk), `role`, `auth_type`, `supports_webhooks`, `enabled`,
`default_poll_min`, `min_poll_min`, `window_seconds`, `window_limit`, `daily_limit`,
`read_limit_15min`, `read_limit_daily`, `overall_limit_15min`, `overall_limit_daily`,
`athlete_capacity`, `monthly_cost_cents`, `initial_backfill_limit`, `page_size`,
`refresh_strategy`, `headroom_pct`, `free_reserve_pct`, `updated_at`.

**`strava_apps`** (existing pool) gains: `athlete_cap`, `monthly_cost_cents`,
`read_limit_15min`, `read_limit_daily`, `overall_limit_15min`, `overall_limit_daily`.
→ the credential + capacity + cost unit.

**`governor_config`** (singleton): `coverage_target_pct`, `paid_reservation_pct`,
`free_degradation_enabled`, `infra_monthly_cost_cents`, `updated_at`.

**`governor_state`** (computed cache; Redis or a 1-row table): `monthly_cost_cents`,
`monthly_revenue_cents`, `free_tier_level`, per-provider capacity headroom, slots
used, `computed_at`.

**`provider_usage_daily`** (rollup for history/trends): `date`, `platform`, `user_id`
(nullable for aggregate), `requests`, `read_requests`, `overall_requests`, `errors`,
`activities_imported`.

Revenue reuses the existing `subscriptions` table. Admin gated by existing
`User.is_admin` + new `require_admin`.

---

## 9. Per-user request accounting (feeds the dashboard)

To give **per-user rate insight** we must attribute usage to users:

- The `RateLimiter.call(...)` increments per-user Redis counters
  `usage:{platform}:user:{uid}:{date}` (+ read/overall split for Strava) alongside the
  per-app counters.
- A daily cron rolls Redis counters into `provider_usage_daily` for history.
- `JobAuditLog` (already exists) gives per-user job/sync records.
- `SyncedActivity` gives per-user import volume.

Cheap (INCR), and gives today's live numbers (Redis) + historical trends (rollup).

---

## 10. Admin surface (API)

All under `/api/v1/admin`, gated by `require_admin`:

- `GET/PATCH /admin/providers[/{platform}]` — provider policies (limits, cost, import).
- `GET/POST/PATCH/DELETE /admin/strava-apps` — app pool + per-app cost/capacity.
- `GET/PATCH /admin/governor` — coverage target, reservations, infra cost, toggles.
- `GET /admin/metrics/overview` — economics + capacity snapshot.
- `GET /admin/metrics/providers` — per-provider health/usage/error time-series.
- `GET /admin/users` — paginated user analytics (below).
- `GET /admin/users/{id}` — per-user rate insight (below).
- `POST /admin/users/{id}/actions` — throttle / suspend / grant tier / reserve slot /
  exempt from governor.

---

## 11. Comprehensive Admin Dashboard

### 11.1 Economics overview
- **MRR vs monthly cost** (API + infra), headroom, coverage-target gauge.
- Current **free-tier degradation level** (0–4) and why.
- **Runway / forecast:** "at current signup & conversion rate you hit the Strava slot
  cap / cost=revenue in ~N days."
- Sliders: `coverage_target_pct`, `paid_reservation_pct` (live what-if).

### 11.2 Provider health
Per provider: capacity used/total (15-min, daily, **read vs overall** for Strava),
athlete slots used/capacity, error/429 rate, current throttle state, monthly cost,
webhook health. Sparklines for the last 24h/7d.

### 11.3 Strava app pool
Per app: athletes assigned / cap, 15-min & daily usage (read + overall), cost, status,
least-loaded ranking; "add app" / "request review" prompts when near cap.

### 11.4 User analytics & per-user rate insight (the detailed view)
- **User table:** email, tier, connections, joined, last active, throttle level,
  **share of total budget**, requests (24h / 7d / 30d), activities imported, errors,
  cost attribution.
- **Heavy-user ranking:** top consumers of the Strava budget; **free users consuming a
  disproportionate share** (governor targets these first).
- **Per-user drill-down:**
  - Requests over time, by provider, read vs overall.
  - Poll cadence actually applied vs configured; current degradation level.
  - Sync health: last sync per connection, error history, backoff state.
  - Import volume (activities, GPX bytes) and storage footprint.
  - Cost attribution: this user's share of flat + any metered cost.
  - **Anomaly flags:** request spikes, 429 storms, failed-auth loops, abuse patterns.
  - **Actions:** throttle, suspend, grant/revoke tier, reserve a Strava slot, exempt
    from governor, force resync.

### 11.5 Trends & analysis
Request volume per provider over time, daily **budget burn-down**, 429/error trends,
signups vs paid conversions, capacity forecast, cohort retention (optional).

### 11.6 Alerts
Capacity > 80%, cost approaching revenue, provider error spike, athlete slots near cap,
a single user exceeding a share threshold.

---

## 12. Phased rollout

1. **Registry + `require_admin` (dark, no behavior change)** — models + migration +
   seed from current constants; admin read/edit endpoints; tests. *Nothing reads the
   registry yet.* ← **Phase 1 (in progress)**
2. **Generic limiter + per-user accounting** — refactor `RateLimitGuard` → registry-
   driven `RateLimiter`; per-user Redis counters; Strava read/overall split. Still
   seeded to current values, so behaviour unchanged.
3. **Governor + fair-share derivation** — control loop → `governor_state`; derived
   per-user poll cadence + import budgets; degradation ladder; admission control.
   Cloud-only; self-hosted bypass.
4. **Non-Strava limiters** — wrap Komoot/Garmin/Runalyze/intervals in the generic
   limiter + backoff/circuit-breaker.
5. **Admin dashboard** — metrics endpoints + frontend (economics, provider health,
   per-user rate insight, trends, alerts).

Each phase is an independent, deployable, PR-sized change.

---

## 13. Open decisions

1. **Coverage target** default: 100% (break-even) vs 70% (safety margin). *Proposed: 70%.*
2. **Free-Strava at cap:** waitlist (gate new) vs always-allow-but-slowest. *Proposed:
   waitlist at level 3, slowest before that.*
3. **Backfill depth** default per provider (e.g. Strava last 30 activities vs 90 days).
4. **Governor cache** store: Redis vs 1-row table (Redis proposed for the live number,
   table snapshot for history).

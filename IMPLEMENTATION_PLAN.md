# RoutePass — Implementation Plan

> Created: 2026-04-29
> Status: Active — update this file as tasks are completed.
> Covers: scalability fixes, schema corrections, OSS/SaaS deployment split, data privacy and integrity.

---

## Overview

Five areas of work, all required before public launch:

**A — Scalability**: Fix live data integrity issues and remove architectural ceilings so the cloud SaaS can grow beyond ~100 active users without hitting hard walls.

**B — Deployment split**: Make the same binary cleanly support both a self-hosted single-user deployment and the cloud multi-tenant SaaS, controlled by a single env var.

**C — Data privacy & integrity**: Every architectural change that touches user data must preserve strict isolation, support right-to-deletion, and never expose one user's credentials or activity tracks to another.

**D — Coolify + Hetzner cloud deployment**: Full infrastructure definition — server sizing, networking, Docker Compose, object storage, CI/CD, backups, and environment secrets.

**E — Multi-directional sync completeness**: Remove all remaining Komoot→Strava exclusivity; add Strava-source pipelines, per-connection watermarks, and Garmin as a new source.

**F — Legacy Komoot decoupling**: Remove residual Komoot-specific code and DB coupling that the original project left behind; make the codebase honest about being a platform hub.

---

## Sections

- **A** — Scalability fixes
- **B** — OSS/SaaS deployment split
- **C** — Data privacy & integrity
- **D** — Coolify + Hetzner cloud deployment
- **E** — Multi-directional sync completeness
- **F** — Legacy Komoot decoupling
- **Reference** — [Strava→Komoot: Will Not Implement](#strava--komoot-will-not-implement) · [D9 Environment Variables](#d9--coolify-environment-variables-reference)

---

## Execution Order

Dependencies flow top-to-bottom. Never skip ahead of an item marked "requires".

| # | Task | Area | Effort | Requires |
|---|------|------|--------|----------|
| 1 | [A1] Migration 007 — multi-destination schema | Scalability | M | — |
| 2 | [B1] Add `DEPLOYMENT_MODE` to config | OSS/SaaS | XS | — |
| 3 | [B2] Wire deployment guards | OSS/SaaS | S | B1 |
| 4 | [B3] `/api/v1/instance` endpoint | OSS/SaaS | XS | B1 |
| 5 | [B4] Frontend instance-aware UI | OSS/SaaS | S | B3 |
| 6 | [A2] ARQ dedup key + scheduler lock | Scalability | XS | — |
| 7 | [A3] DB pool config env vars | Scalability | XS | — |
| 8 | [A4] Strava multi-app fan-out | Scalability | S | A1 |
| 9 | [A5-ph1] GPX storage — add column + StorageService | Scalability | M | B1 |
| 10 | [B5] Restructure Docker Compose files | OSS/SaaS | S | B1, A5-ph1 |
| 11 | [A5-ph2] GPX storage — drop `gpx_data` column | Scalability | XS | A5-ph1 (backfill confirmed) |
| 12 | [B6] Deprecate `LICENSE_SERVER_URL` | Cleanup | XS | — |
| 13 | [C1] GPX object storage — access controls + encryption | Privacy | S | A5-ph1 |
| 14 | [C2] Cascading delete — purge object storage on activity delete | Privacy | S | A5-ph1 |
| 15 | [C3] User data export + account deletion (GDPR) | Privacy | M | A5-ph1 |
| 16 | [C4] Credential isolation hardening | Privacy | S | — |
| 17 | [C5] Audit log for sensitive actions | Privacy | S | — |
| 18 | [D1] Hetzner server + network + firewall setup | Infra | S | — |
| 19 | [D2] Coolify install + domain wiring | Infra | S | D1 |
| 20 | [D3] `docker-compose.cloud.yml` — Coolify-compatible | Infra | M | B1, B5, D2 |
| 21 | [D4] Hetzner Object Storage bucket + IAM | Infra | XS | D1 |
| 22 | [D5] Database strategy (Coolify vs Hetzner Managed DB) | Infra | S | D2 |
| 23 | [D6] CI/CD — auto-deploy on push | Infra | S | D2, D3 |
| 24 | [D7] Backup strategy | Infra | S | D2, D5 |
| 25 | [D8] Migrations as init container | Infra | XS | D3 |
| 26 | [E1] Fix premature `sync_direction` at ingest time | Sync | XS | A1 |
| 27 | [E2] Fix `sync_komoot_to_strava` — write `destination_platform` on success | Sync | XS | A1 |
| 28 | [E3] Implement `_run_strava_to_intervals_icu` pipeline handler | Sync | S | A1 |
| 29 | [E4] Implement `_run_strava_to_runalyze` pipeline handler | Sync | S | A1, E3 |
| 30 | [E5] Per-connection sync watermarks (`UserSyncState` refactor) | Sync | M | A1 |
| 31 | [E6] Garmin Connect source implementation | Sync | M | E5 |
| 32 | [E7] Remove backward-compat ARQ job aliases | Cleanup | XS | E6 (after 2 deploys) |
| 33 | [F1] Remove Komoot columns from `User` model + all referencing code | Refactor | M | — |
| 34 | [F2] Generalize `SyncRule.direction` constraint (migration 011) | Refactor | S | F1 |
| 35 | [F3] Refactor `/sync/status` to platform-agnostic response | Refactor | S | F1 |
| 36 | [F4] Deprecate `POST /sync/rebuild-history` | Refactor | XS | — |
| 37 | [F5] Extend `SyncedActivity.source` constraint for new platforms | Refactor | XS | — |
| 38 | [F6] Make rule engine platform-agnostic | Refactor | M | F1 |

Effort: XS = <30 min, S = 1–2 h, M = 3–6 h, L = day+

---

## MVP Scope Boundary

Items marked **launch-critical** must ship before any public users are onboarded. Items marked **deferred** can follow in subsequent releases without blocking the product.

| Item | Scope | Rationale |
|------|-------|-----------|
| A1 · Multi-destination schema migration | Launch-critical | Live data integrity — wrong IDs stored today |
| A2 · ARQ dedup + scheduler lock | Launch-critical | Race condition with ≥2 workers |
| A3 · DB pool env vars | Launch-critical | Required for pgBouncer compatibility |
| A5-ph1 · GPX dual-write to object storage | Launch-critical | Unblocks storage cost ceiling |
| B1 · `DEPLOYMENT_MODE` config | Launch-critical | OSS vs cloud binary split |
| B2 · `require_tier` self-hosted bypass | Launch-critical | OSS users must not hit 402 |
| B3 · `/api/v1/instance` endpoint | Launch-critical | Frontend adapts UI per mode |
| B4 · Billing 501 in self-hosted mode | Launch-critical | Prevents misleading billing errors |
| B5 · Multi-origin CORS | Launch-critical | Cloud domain + custom self-hosted domains |
| C1 · GPX object storage access controls | Launch-critical | Private bucket + presigned URLs before any GPX is stored externally |
| C2 · Cascading delete — purge storage on activity delete | Launch-critical | Orphaned GPX blobs otherwise accumulate indefinitely |
| C3 · Account deletion + data export (GDPR) | Launch-critical | Article 17 (erasure) + Article 20 (portability) — required before EU users |
| C4 · Credential isolation hardening | Launch-critical | Ownership assertions prevent cross-user credential leaks |
| C5 · Audit log for sensitive actions | Launch-critical | Required for security investigation and compliance |
| D1–D8 · Coolify/Hetzner infra | Launch-critical | Cloud deployment prerequisite |
| E1 · Fix premature `sync_direction` at ingest | Launch-critical | Broken data if not fixed |
| E2 · Write `destination_platform` on Komoot→Strava success | Launch-critical | Hub model correctness |
| F1 · Remove Komoot columns from `User` model | Launch-critical | Code crashes today against live DB |
| F4 · Deprecate `/sync/rebuild-history` | Launch-critical | Remove dead Komoot migration utility |
| F5 · Extend `SyncedActivity.source` constraint | Launch-critical | Any new-platform ingest will fail without this |
| A4 · Strava multi-app fan-out | Deferred | Only needed when approaching 1k req/day ceiling |
| A5-ph2 · Drop `gpx_data` column | Deferred | After confirming all blobs are migrated |
| B6 · Remove `LICENSE_SERVER_URL` | Deferred | Cleanup; no functional impact |
| E3 · Strava→Intervals.icu handler | Deferred | New direction; existing Komoot→Intervals.icu still works |
| E4 · Strava→Runalyze handler | Deferred | Same as E3 |
| E5 · Per-connection sync watermarks | Deferred | Needed only when adding 3rd+ sources |
| E6 · Garmin Connect source | Deferred | Post-launch new source |
| E7 · Remove ARQ job aliases | Deferred | After 2 deploys with E6 stable |
| F2 · Generalize `SyncRule.direction` | Deferred | Block on E5/E6; not needed until 3rd source ships |
| F3 · Platform-agnostic `/sync/status` | Deferred | Can ship alongside or after E5 |
| F6 · Platform-agnostic rule engine | Deferred | Block on F1; needed when Garmin rules are required |

---

## A1 · Migration 007: Multi-Destination Sync Schema

**Priority: CRITICAL — live data integrity issue**

`_run_komoot_to_intervals_icu` and `_run_komoot_to_runalyze` already run in production.
They currently store Intervals.icu/Runalyze IDs in `strava_activity_id` and write
`sync_direction="komoot_to_strava"` because the check constraint rejects all other values.
This is wrong data that will become a reporting/debugging nightmare at scale.

### What changes

#### `backend/alembic/versions/007_multi_destination_sync.py` (new file)

```python
"""Multi-destination sync schema

- Drop uq_synced_activities_user_komoot (blocks same tour → multiple destinations)
- Add destination_platform column
- Add destination_activity_id column
- Extend sync_direction check constraint
- Add composite unique (user_id, komoot_tour_id, destination_platform)
- Backfill existing strava-destined rows

Revision ID: 007
Revises: 006
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

VALID_DIRECTIONS = (
    "komoot_to_strava",
    "strava_to_komoot",
    "komoot_to_intervals_icu",
    "komoot_to_runalyze",
    "strava_to_intervals_icu",
    "strava_to_runalyze",
    "import_to_strava",
    "import_to_komoot",
)

def upgrade() -> None:
    # 1. Drop old blocking unique constraint
    op.drop_constraint(
        "uq_synced_activities_user_komoot", "synced_activities", type_="unique"
    )

    # 2. Add new columns
    op.add_column(
        "synced_activities",
        sa.Column("destination_platform", sa.String(), nullable=True),
    )
    op.add_column(
        "synced_activities",
        sa.Column("destination_activity_id", sa.String(), nullable=True),
    )

    # 3. Drop old sync_direction check constraint, add extended one
    op.drop_constraint(
        "ck_synced_activities_sync_direction", "synced_activities", type_="check"
    )
    valid_str = ", ".join(f"'{d}'" for d in VALID_DIRECTIONS)
    op.create_check_constraint(
        "ck_synced_activities_sync_direction",
        "synced_activities",
        f"sync_direction IS NULL OR sync_direction IN ({valid_str})",
    )

    # 4. Backfill: existing strava-destined rows
    op.execute("""
        UPDATE synced_activities
        SET destination_platform     = 'strava',
            destination_activity_id  = strava_activity_id
        WHERE strava_activity_id IS NOT NULL
          AND source IN ('komoot', 'import')
    """)

    # 5. New composite unique: one row per (user, komoot_tour, destination)
    op.create_unique_constraint(
        "uq_synced_activities_user_komoot_dest",
        "synced_activities",
        ["user_id", "komoot_tour_id", "destination_platform"],
    )

    # 6. Index on destination_platform for pipeline queries
    op.create_index(
        "ix_synced_activities_dest_platform",
        "synced_activities",
        ["destination_platform"],
    )


def downgrade() -> None:
    op.drop_index("ix_synced_activities_dest_platform", "synced_activities")
    op.drop_constraint(
        "uq_synced_activities_user_komoot_dest", "synced_activities", type_="unique"
    )
    op.drop_constraint(
        "ck_synced_activities_sync_direction", "synced_activities", type_="check"
    )
    op.create_check_constraint(
        "ck_synced_activities_sync_direction",
        "synced_activities",
        "sync_direction IS NULL OR sync_direction IN ('komoot_to_strava', 'strava_to_komoot')",
    )
    op.drop_column("synced_activities", "destination_activity_id")
    op.drop_column("synced_activities", "destination_platform")
    op.create_unique_constraint(
        "uq_synced_activities_user_komoot",
        "synced_activities",
        ["user_id", "komoot_tour_id"],
    )
```

#### `backend/app/db/models/sync.py`

Add two new mapped columns to `SyncedActivity`:

```python
destination_platform: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
destination_activity_id: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
```

Update `__table_args__`:
- Remove `sa.UniqueConstraint("user_id", "komoot_tour_id", name="uq_synced_activities_user_komoot")`
- Add `sa.UniqueConstraint("user_id", "komoot_tour_id", "destination_platform", name="uq_synced_activities_user_komoot_dest")`
- Replace the `ck_synced_activities_sync_direction` check constraint with the extended values list above
- Add `sa.Index("ix_synced_activities_dest_platform", "destination_platform")`

Keep `strava_activity_id` in place — it is still used by `process_strava_activity`'s dedup
check and `uq_synced_activities_user_strava`. It will be deprecated in migration 010.

> **Known trade-off — Komoot-named constraint:** `uq_synced_activities_user_komoot_dest`
> enforces uniqueness on `(user_id, komoot_tour_id, destination_platform)`. For activities
> from non-Komoot sources (Garmin, Strava-native), `komoot_tour_id` is NULL. SQL treats
> `NULL != NULL`, so this constraint does **not** prevent duplicate Garmin or Strava rows.
> Each new source handler is responsible for its own dedup check (see E6 — Garmin dedup
> uses `destination_activity_id`; E3 — Strava dedup uses `strava_activity_id +
> destination_platform`). A future refactor should introduce a generic `source_external_id`
> column and migrate the unique constraint to `(user_id, source, source_external_id,
> destination_platform)`, retiring `komoot_tour_id`. That refactor is not in scope here —
> document it as technical debt to address once E6 is stable.

#### `backend/app/jobs/sync_jobs.py`

**`_run_komoot_to_intervals_icu`** — replace the `SyncedActivity(...)` insert:
```python
# BEFORE (wrong):
strava_activity_id=activity_id,          # repurposed field
sync_direction="komoot_to_strava",        # wrong direction

# AFTER:
destination_platform="intervals_icu",
destination_activity_id=activity_id,
sync_direction="komoot_to_intervals_icu",
```

Replace the pipeline-scoped dedup query:
```python
# BEFORE: filters on pipeline_id (workaround)
# AFTER: uses the real composite unique constraint
already = await db.execute(
    _select(_SA).where(
        _SA.user_id == user.id,
        _SA.komoot_tour_id == tour.id,
        _SA.destination_platform == "intervals_icu",
        _SA.sync_status == "completed",
    )
)
```

**`_run_komoot_to_runalyze`** — same corrections:
```python
destination_platform="runalyze",
destination_activity_id=activity_id,
sync_direction="komoot_to_runalyze",
```

**`sync_gpx_to_strava`** — on success, also write `destination_platform`:
```python
activity.strava_activity_id = strava_activity_id
activity.destination_platform = "strava"
activity.destination_activity_id = strava_activity_id
activity.sync_status = "completed"
activity.sync_direction = "import_to_strava"   # was hardcoded "komoot_to_strava"
```

**`sync_activity_to_komoot`** — on success:
```python
activity.komoot_tour_id = tour_id
activity.destination_platform = "komoot"
activity.destination_activity_id = tour_id
activity.sync_status = "completed"
activity.sync_direction = "import_to_komoot"   # fix the backwards value
```

#### `backend/app/services/sync.py`

In `upload_komoot_to_strava`, the pending-activity query currently filters on
`strava_activity_id IS NULL`. Update to also check `destination_platform`:
```python
# Find Komoot tours not yet pushed to Strava
SyncedActivity.source == "komoot",
sa.or_(
    SyncedActivity.destination_platform == None,
    SyncedActivity.destination_platform != "strava",
),
```

On successful upload, set `destination_platform="strava"` and `destination_activity_id`.

#### `backend/app/api/v1/activities.py`

In the activity serializer, update the `platforms` / `sync_direction` field to read from
`destination_platform` in addition to `source`:
```python
"destination_platform": activity.destination_platform,
"destination_activity_id": activity.destination_activity_id,
```

### Backfill script for mis-stored Intervals.icu/Runalyze records

After applying the migration, run this one-time script for any pipelines that already
pushed to Intervals.icu or Runalyze (the migration cannot distinguish these from real
Strava IDs stored in the same column):

```bash
# backend/scripts/backfill_destination_platform.py
# Usage: python -m backend.scripts.backfill_destination_platform
```

The script queries `SyncedActivity` rows where `pipeline_id IS NOT NULL`, loads the
pipeline's `dest_connection.platform`, and writes the correct `destination_platform` and
`sync_direction`. Run with `make shell-db` if preferred.

---

## B1 · Add `DEPLOYMENT_MODE` to Config

**Priority: HIGH — enables all self-hosted feature gating**

### `backend/app/core/config.py`

Add the following fields to the `Settings` class:

```python
# Deployment mode — controls feature set and billing availability
# "cloud"      → full SaaS with Stripe, shared Strava app pool, tier enforcement
# "selfhosted" → single-user, no billing, all features unlocked, own Strava app
DEPLOYMENT_MODE: str = "cloud"

# Maximum registered users. 0 = unlimited (cloud default).
# Set to 1 for a standard single-user self-hosted install.
MAX_USERS: int = 0

# DB connection pool (tune per deployment; pgBouncer overrides these)
DB_POOL_SIZE: int = 10
DB_MAX_OVERFLOW: int = 20
DB_POOL_TIMEOUT: int = 30

# ARQ worker concurrency
ARQ_MAX_JOBS: int = 10

# Object storage (default: store GPX in DB — suitable for self-hosted)
# Set STORAGE_BACKEND=r2 (or s3) for cloud deployments
STORAGE_BACKEND: str = "db"   # "db" | "s3" | "r2"
STORAGE_BUCKET: str = ""
STORAGE_ENDPOINT_URL: str = ""    # R2 or MinIO custom endpoint
STORAGE_ACCESS_KEY_ID: str = ""
STORAGE_SECRET_ACCESS_KEY: str = ""
STORAGE_REGION: str = "auto"
```

Remove `LICENSE_SERVER_URL` (handled in B6).

### `backend/app/db/session.py`

Read pool config from settings instead of hardcoding:

```python
if not _db_url.startswith("sqlite"):
    _engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
    _engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
    _engine_kwargs["pool_timeout"] = settings.DB_POOL_TIMEOUT
    # Required for pgBouncer transaction-pool mode
    _engine_kwargs["connect_args"] = {"prepared_statement_cache_size": 0}
```

### `backend/app/jobs/worker.py`

Read ARQ concurrency from settings:

```python
class WorkerSettings:
    max_jobs = settings.ARQ_MAX_JOBS
    job_timeout = 600
```

---

## B2 · Wire Deployment Guards

**Priority: HIGH — enforces the feature split**

### `backend/app/api/deps.py`

Modify `require_tier` so self-hosted deployments bypass all tier checks:

```python
def require_tier(min_tier: str) -> Callable:
    required_rank = TIER_RANKS.get(min_tier, 0)

    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        # Self-hosted: all features unlocked for the owner
        if settings.DEPLOYMENT_MODE == "selfhosted":
            return

        from app.db.models.subscription import Subscription
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()
        tier = subscription.tier if subscription else "free"
        if TIER_RANKS.get(tier, 0) < required_rank:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"This feature requires a {min_tier} subscription or higher.",
            )

    return _check
```

### `backend/app/api/v1/auth.py`

In the `register` endpoint, after validating the payload but before inserting the new user:

```python
# Self-hosted user cap
if settings.DEPLOYMENT_MODE == "selfhosted" and settings.MAX_USERS > 0:
    from sqlalchemy import func
    count_result = await db.execute(select(func.count()).select_from(User))
    if (count_result.scalar() or 0) >= settings.MAX_USERS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This instance has reached its maximum user limit.",
        )
```

### `backend/app/api/v1/billing.py`

Add a self-hosted guard at the top of both `create_checkout_session` and
`create_portal_session`, before any Stripe calls:

```python
if settings.DEPLOYMENT_MODE == "selfhosted":
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Billing is not available in self-hosted mode.",
    )
```

### `backend/app/api/v1/webhooks.py`

In the Stripe webhook endpoint (`POST /webhooks/stripe`), add:

```python
if settings.DEPLOYMENT_MODE == "selfhosted":
    return Response(status_code=204)
```

This prevents any accidental Stripe processing if someone misconfigures a webhook URL
pointing at a self-hosted instance.

---

## B3 · `/api/v1/instance` Endpoint

**Priority: HIGH — frontend reads this to adapt its UI**

### `backend/app/api/v1/instance.py` (new file)

```python
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["instance"])


@router.get("")
async def instance_info() -> dict:
    """Return public configuration metadata for this deployment.

    The frontend calls this on boot to determine which UI features to show.
    No authentication required — this is safe to expose publicly.
    """
    return {
        "deployment_mode": settings.DEPLOYMENT_MODE,
        "billing_enabled": bool(settings.STRIPE_SECRET_KEY) and settings.DEPLOYMENT_MODE == "cloud",
        "max_users": settings.MAX_USERS,
        "multi_user": settings.DEPLOYMENT_MODE == "cloud" or settings.MAX_USERS != 1,
    }
```

### `backend/app/api/v1/router.py`

```python
from app.api.v1 import instance
# ...
router.include_router(instance.router, prefix="/instance")
```

---

## B4 · Frontend Instance-Aware UI

**Priority: MEDIUM — depends on B3**

The frontend must suppress billing/upgrade UI when running against a self-hosted backend.

### `frontend/hooks/use-instance.ts` (new file)

```typescript
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'

export interface InstanceInfo {
  deployment_mode: 'cloud' | 'selfhosted'
  billing_enabled: boolean
  max_users: number
  multi_user: boolean
}

export function useInstance() {
  return useQuery<InstanceInfo>({
    queryKey: ['instance'],
    queryFn: () => apiGet('/api/v1/instance'),
    staleTime: Infinity,   // never re-fetch — this doesn't change at runtime
  })
}
```

### Usage across the frontend

Anywhere "Upgrade to Pro", the billing page link, or tier badges appear:

```tsx
const { data: instance } = useInstance()

// Hide billing CTA on self-hosted
{instance?.billing_enabled && <UpgradeButton />}

// Hide tier badges on self-hosted (owner has everything)
{instance?.billing_enabled && <TierBadge tier={user.tier} />}
```

Pages to update:
- `app/(dashboard)/billing/page.tsx` — render a "Self-hosted mode — billing disabled" message when `!billing_enabled`
- `app/(dashboard)/dashboard/page.tsx` — hide the quota/upgrade card
- `app/(dashboard)/rules/page.tsx` — hide the "Pro required" gate UI
- `app/(dashboard)/pipelines/page.tsx` — same
- Sidebar navigation — hide "Billing" link when `!billing_enabled`

---

## A2 · ARQ Dedup Key + Scheduler Redis Lock

**Priority: HIGH — fixes a real race condition before adding worker replicas**

Both changes are in `backend/app/jobs/sync_jobs.py`.

### Dedup key for `poll_user_sources` enqueue

In `source_poll_scheduler`, change the enqueue call:

```python
# BEFORE:
await redis.enqueue_job("poll_user_sources", str(uid))

# AFTER:
await redis.enqueue_job(
    "poll_user_sources",
    str(uid),
    _job_id=f"poll_user_{uid}",   # ARQ deduplicates: same ID = no double-enqueue
)
```

ARQ silently drops the second enqueue if a job with the same `_job_id` is already
queued or running. This makes multiple worker replicas safe.

### Scheduler Redis lock

In `source_poll_scheduler`, add at the very top of the function body (after the Redis
availability check):

```python
# Only one worker runs the scheduler per tick
lock_acquired = await redis.set(
    "routepass:scheduler_lock", 1, nx=True, ex=290
)
if not lock_acquired:
    logger.debug("source_poll_scheduler: lock held by another worker — skipping")
    return
```

`ex=290` — expires just before the 5-minute cron interval so the lock never gets stuck
if the scheduler worker crashes mid-run.

---

## A3 · DB Connection Pool Config

**Priority: MEDIUM — prerequisite for adding API replicas**

> **Implemented alongside B1.** The env vars (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
> `DB_POOL_TIMEOUT`) are added to `config.py` in the B1 step. The `session.py` update
> that reads from them is in the B1 code block. No separate work item — execute A3
> and B1 as a single PR.

The critical addition is `prepared_statement_cache_size=0` in `connect_args`. Without
this, SQLAlchemy's named prepared statements conflict with pgBouncer in transaction-pool
mode — queries work fine in dev (no pgBouncer) but fail or silently misbehave in the
cloud compose (B5). This must land before pgBouncer is enabled.

---

## A4 · Strava Multi-App Fan-Out

**Priority: MEDIUM — required before cloud SaaS grows beyond ~100 active sync users**

Requires A1 (clean schema) to be complete first.

The `StravaApp` model already supports multiple rows. The `RateLimitGuard` already
accepts `app_id`. The only missing piece is routing new users to the least-loaded app.

### `backend/app/core/rate_limit.py`

Add to `RateLimitGuard`:

```python
async def pick_least_loaded_app(self, app_ids: list[int]) -> int:
    """Return the app_id with the most remaining daily headroom.

    Results are cached in Redis for 60 seconds to avoid per-request DB queries.
    Returns the first app_id if all are equally loaded or the list is empty.
    """
    if not app_ids:
        raise ValueError("No active Strava apps available")

    r = await self.get_redis()
    cache_key = "routepass:least_loaded_app"
    cached = await r.get(cache_key)
    if cached:
        return int(cached)

    best_id = app_ids[0]
    best_remaining = -1
    for app_id in app_ids:
        count = await self.daily_count(app_id)
        remaining = DAILY_LIMIT - count
        if remaining > best_remaining:
            best_remaining = remaining
            best_id = app_id

    await r.set(cache_key, best_id, ex=60)
    return best_id
```

### `backend/app/api/v1/auth.py` — Strava OAuth callback

When creating or updating a `StravaToken`, pick the app with the most headroom instead
of always using the first/only app:

```python
from sqlalchemy import select
from app.db.models.user import StravaApp
from app.core.rate_limit import rate_limit_guard

# Load all active app IDs
apps_result = await db.execute(
    select(StravaApp.id).where(StravaApp.is_active == True)  # noqa: E712
)
app_ids = [row[0] for row in apps_result.all()]
chosen_app_id = await rate_limit_guard.pick_least_loaded_app(app_ids)

# Use chosen_app_id when creating the StravaToken
```

### `backend/app/jobs/sync_jobs.py` — `source_poll_scheduler`

Replace the single-app global budget check with a per-user check using the token's
assigned app. The `RateLimitGuard.call()` already handles per-app budgets; the
scheduler's job is just to decide whether to enqueue:

```python
# BEFORE: fetches one global strava_app_id and checks its daily count
app_result = await db.execute(
    select(StravaApp.id).where(StravaApp.is_active == True).limit(1)
)
strava_app_id = app_result.scalar_one_or_none()
daily_count = await rate_limit_guard.daily_count(strava_app_id) if strava_app_id else 0
budget_exhausted_for_free = daily_count > 800

# AFTER: each user's own app is checked independently
# Remove the global pre-check entirely; let RateLimitGuard.call() enforce limits
# per-job. The only remaining global check: if ALL apps are at capacity, log and skip.
all_app_ids = [row[0] for row in (await db.execute(
    select(StravaApp.id).where(StravaApp.is_active == True)  # noqa: E712
)).all()]

all_exhausted = all(
    await rate_limit_guard.daily_count(aid) > 800
    for aid in all_app_ids
) if all_app_ids else True

if all_exhausted:
    logger.warning("All Strava apps at free-tier budget threshold — skipping free tier this cycle")
```

### Registering additional Strava Apps

Additional apps are inserted directly into the `strava_apps` table (or via a future
admin endpoint). Each app needs its own `client_id` / `client_secret` / `verify_token`
from Strava. The `_bootstrap_strava_app()` function in `main.py` seeds app #1 from env
vars at startup — no change needed there. Subsequent apps are manual.

---

## A5 · GPX Blob Migration to Object Storage

### Phase 1 — Add `gpx_storage_key` column (migration 008)

**Priority: MEDIUM — start when storage config (B1) is in place**

#### `backend/alembic/versions/008_add_gpx_storage_key.py` (new file)

```python
"""Add gpx_storage_key column for object storage

Revision ID: 008
Revises: 007
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "synced_activities",
        sa.Column("gpx_storage_key", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_synced_activities_gpx_storage_key",
        "synced_activities",
        ["gpx_storage_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_synced_activities_gpx_storage_key", "synced_activities")
    op.drop_column("synced_activities", "gpx_storage_key")
```

#### `backend/app/db/models/sync.py`

Add column:
```python
gpx_storage_key: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
```

Keep `gpx_data` in place until Phase 2 backfill is confirmed.

### Phase 2 — StorageService + dual-write

#### `backend/app/services/storage.py` (new file)

```python
"""Object storage service for GPX files.

Falls back to a no-op (returns None) when STORAGE_BACKEND=db so that
callers can always check the DB column instead.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_S3_CLIENTS: dict = {}


def _get_s3():
    """Return a lazily-initialised aiobotocore S3 client."""
    import aiobotocore.session  # type: ignore

    key = (settings.STORAGE_ENDPOINT_URL, settings.STORAGE_ACCESS_KEY_ID)
    if key not in _S3_CLIENTS:
        session = aiobotocore.session.get_session()
        _S3_CLIENTS[key] = session.create_client(
            "s3",
            region_name=settings.STORAGE_REGION,
            endpoint_url=settings.STORAGE_ENDPOINT_URL or None,
            aws_access_key_id=settings.STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=settings.STORAGE_SECRET_ACCESS_KEY,
        )
    return _S3_CLIENTS[key]


class StorageService:

    @staticmethod
    def _key(user_id: str, activity_id: str) -> str:
        return f"gpx/{user_id}/{activity_id}.gpx"

    @classmethod
    async def put_gpx(cls, user_id: str, activity_id: str, data: bytes) -> Optional[str]:
        """Upload GPX bytes. Returns the storage key, or None when using DB backend."""
        if settings.STORAGE_BACKEND == "db":
            return None  # caller stores data in gpx_data column

        key = cls._key(str(user_id), str(activity_id))
        try:
            async with _get_s3() as client:
                await client.put_object(
                    Bucket=settings.STORAGE_BUCKET,
                    Key=key,
                    Body=data,
                    ContentType="application/gpx+xml",
                )
            return key
        except Exception as exc:
            logger.error("StorageService.put_gpx failed: %s", exc)
            raise

    @classmethod
    async def get_gpx(cls, key: str) -> bytes:
        """Download GPX bytes by storage key."""
        try:
            async with _get_s3() as client:
                resp = await client.get_object(Bucket=settings.STORAGE_BUCKET, Key=key)
                return await resp["Body"].read()
        except Exception as exc:
            logger.error("StorageService.get_gpx failed for key %s: %s", key, exc)
            raise

    @classmethod
    async def delete_gpx(cls, key: str) -> None:
        """Delete a stored GPX object."""
        if settings.STORAGE_BACKEND == "db":
            return
        try:
            async with _get_s3() as client:
                await client.delete_object(Bucket=settings.STORAGE_BUCKET, Key=key)
        except Exception as exc:
            logger.warning("StorageService.delete_gpx failed for key %s: %s", key, exc)
```

Add `aiobotocore>=2.13` to `backend/requirements.txt`.

#### `backend/app/api/v1/activities.py` — GPX import endpoint

In `import_gpx_activities`, after parsing each GPX file, write to object storage first:

```python
from app.services.storage import StorageService

# After inserting the SyncedActivity record and obtaining activity.id:
storage_key = await StorageService.put_gpx(
    user_id=str(user.id),
    activity_id=str(activity.id),
    data=gpx_bytes,
)
if storage_key:
    activity.gpx_storage_key = storage_key
    activity.gpx_data = None           # clear DB blob when stored externally
else:
    activity.gpx_data = gpx_bytes      # fallback: store in DB (selfhosted default)
await db.commit()
```

#### `backend/app/api/v1/activities.py` — GPX download endpoint

In `GET /activities/{id}/gpx`, resolve GPX in order:

```python
# 1. Object storage key (new path)
if activity.gpx_storage_key:
    gpx_bytes = await StorageService.get_gpx(activity.gpx_storage_key)

# 2. DB column (self-hosted / legacy rows)
elif activity.gpx_data:
    gpx_bytes = activity.gpx_data

# 3. Live fetch from Strava streams (source=strava)
elif activity.source == "strava" and activity.strava_activity_id:
    gpx_bytes = await _fetch_strava_gpx(activity, user, db)

# 4. Live fetch from Komoot (source=komoot with real tour ID)
elif activity.source == "komoot" and activity.komoot_tour_id:
    gpx_bytes = await _fetch_komoot_gpx(activity, user, db)

else:
    raise HTTPException(404, "No GPX track available for this activity.")
```

#### `backend/scripts/backfill_gpx_to_storage.py` (new file)

One-time script to migrate existing `gpx_data` blobs to object storage. Run manually
after deploying Phase 2 in cloud environments:

```python
"""
Migrate gpx_data blobs to object storage.

Usage:
    cd /path/to/routepass
    PYTHONPATH=backend python -m scripts.backfill_gpx_to_storage

Only runs when STORAGE_BACKEND != "db". Idempotent — skips rows that
already have gpx_storage_key set.
"""
from __future__ import annotations
import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models.sync import SyncedActivity
from app.services.storage import StorageService
from app.core.config import settings


async def main() -> None:
    if settings.STORAGE_BACKEND == "db":
        print("STORAGE_BACKEND=db — nothing to migrate.")
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SyncedActivity).where(
                SyncedActivity.gpx_data != None,      # noqa: E711
                SyncedActivity.gpx_storage_key == None,  # noqa: E711
            )
        )
        rows = result.scalars().all()
        print(f"Found {len(rows)} rows to migrate.")

        for i, activity in enumerate(rows):
            try:
                key = await StorageService.put_gpx(
                    str(activity.user_id), str(activity.id), activity.gpx_data
                )
                activity.gpx_storage_key = key
                activity.gpx_data = None
                await db.commit()
                print(f"  [{i+1}/{len(rows)}] migrated {activity.id}")
            except Exception as exc:
                await db.rollback()
                print(f"  [{i+1}/{len(rows)}] FAILED {activity.id}: {exc}")

    print("Done.")


asyncio.run(main())
```

### Phase 3 — Drop `gpx_data` column (migration 009)

**Run only after confirming all rows have `gpx_storage_key` set (or are self-hosted
instances where `gpx_data` is intentionally kept).**

#### `backend/alembic/versions/009_drop_gpx_data.py` (deferred — create when ready)

```python
"""Drop gpx_data column (all blobs migrated to object storage)

Revision ID: 009
Revises: 008
"""
from __future__ import annotations
from alembic import op

revision = "009"
down_revision = "008"


def upgrade() -> None:
    op.drop_column("synced_activities", "gpx_data")


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column(
        "synced_activities",
        sa.Column("gpx_data", sa.LargeBinary(), nullable=True),
    )
```

Remove `gpx_data` from the `SyncedActivity` SQLAlchemy model in the same PR.

> **Note for self-hosted deployments:** `STORAGE_BACKEND=db` is the default and
> recommended setting for self-hosted. Do **not** run migration 009 on self-hosted
> instances — leave `gpx_data` in place and skip Phase 3 entirely.

---

## B5 · Restructure Docker Compose Files

**Priority: MEDIUM — depends on B1 (env vars must be settled)**

### Rename

```
docker-compose.production.yml  →  docker-compose.selfhosted.yml
```

Create a new `docker-compose.cloud.yml` for SaaS deployments.

### `docker-compose.selfhosted.yml`

Key changes from current `docker-compose.production.yml`:
- Add `DEPLOYMENT_MODE=selfhosted` to `api` and `worker` environment
- Add `MAX_USERS=1`
- Add `STORAGE_BACKEND=db`
- Add `ARQ_MAX_JOBS=5`
- Fix the POSTGRES_DB name: change `komoot_strava_sync` → `routepass` in db healthcheck
- Remove `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_LIFETIME`
  from the template — they must not appear in the self-hosted env template
- Remove `frontend` service (self-hosters run it separately or use API only)

### `docker-compose.cloud.yml` (new)

Extends the dev compose for production cloud use:
- `DEPLOYMENT_MODE=cloud`
- `STORAGE_BACKEND=r2` (with R2 env vars)
- Worker `deploy: replicas: 2` (safe after A2 ARQ lock is in place)
- pgBouncer sidecar service (after A3 pool config is done)
- `DB_POOL_SIZE=5` per replica (pgBouncer handles the rest)

### `.env.selfhosted.template`

Remove all Stripe variables. Add:
```
DEPLOYMENT_MODE=selfhosted
MAX_USERS=1
STORAGE_BACKEND=db
ARQ_MAX_JOBS=5

# ── Strava App (required — create at https://www.strava.com/settings/api) ──────
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
STRAVA_WEBHOOK_VERIFY_TOKEN=  # any random string; used to verify Strava webhook challenges
```

---

## B6 · Deprecate `LICENSE_SERVER_URL`

**Priority: LOW — cleanup**

`DEPLOYMENT_MODE` makes the remote license check pattern unnecessary.

### `backend/app/core/config.py`

Remove `LICENSE_SERVER_URL` from the `Settings` class entirely.

The `LicenseCache` DB model and its migration (`001_initial_schema.py`) can remain
untouched — dropping a table costs a migration and gains nothing. Mark it as deprecated
with an inline comment. If a paid self-hosted tier is ever needed in future, use a
locally-validated JWT signed with RoutePass's private key instead.

---

## Testing Checklist

After each group of changes, run `make check` and verify:

| Step completed | Test to add / verify |
|---|---|
| A1 migration applied | Existing tests still pass; `test_activities.py` covers new columns |
| B2 guards wired | Add `test_selfhosted_mode.py`: registration cap, billing 501, tier bypass |
| B3 instance endpoint | Add to `test_auth.py` or new file: unauthenticated GET `/instance` returns 200 |
| A2 ARQ dedup key | Manual: run two workers, trigger scheduler, verify no doubled poll jobs in Redis |
| A4 fan-out | Add `test_rate_limit.py`: `pick_least_loaded_app` returns lowest-count app |
| A5-ph1 dual-write | `test_activities.py`: imported GPX stored in object storage when `STORAGE_BACKEND!=db` |
| A5-ph2 migration | Verify `gpx_data` column absent; all existing GPX still downloadable via key |
| C2 cascading delete | Delete an activity with a storage key; verify blob gone from Hetzner bucket |
| C3 account deletion | Full delete: user row gone, storage blobs purged, Stripe sub cancelled |
| D3 Coolify deploy | `curl https://api.routepass.app/health` returns 200; TLS cert valid |
| D8 init container | First deploy: migrations run automatically; `alembic current` shows head |
| D6 CI/CD | Push to a PR branch; verify GitHub Actions run `make check`; push to `main` triggers Coolify deploy |

---

## File Change Summary

| File | Change | Task |
|---|---|---|
| `alembic/versions/007_multi_destination_sync.py` | New | A1 |
| `alembic/versions/008_add_gpx_storage_key.py` | New | A5-ph1 |
| `alembic/versions/009_drop_gpx_data.py` | New (deferred) | A5-ph2 |
| `app/db/models/sync.py` | Add `destination_platform`, `destination_activity_id`, `gpx_storage_key`; update constraints; add `JobAuditLog` entries for sensitive mutations | A1, A5, C5 |
| `app/db/models/audit.py` | New — `UserAuditLog` model | C5 |
| `app/core/config.py` | Add `DEPLOYMENT_MODE`, `MAX_USERS`, pool config, ARQ config, storage config, `FRONTEND_URLS`; remove `LICENSE_SERVER_URL` | B1, A3, B6, D3 |
| `app/db/session.py` | Read pool config from settings; add `prepared_statement_cache_size=0` | A3, B1 |
| `app/jobs/worker.py` | Read `ARQ_MAX_JOBS` from settings | B1 |
| `app/jobs/sync_jobs.py` | Fix Intervals.icu/Runalyze records; add ARQ dedup key; add scheduler Redis lock; update fan-out budget check; validate `user_id` ownership before every DB write | A1, A2, A4, C4 |
| `app/core/rate_limit.py` | Add `pick_least_loaded_app()` | A4 |
| `app/api/deps.py` | Self-hosted bypass in `require_tier` | B2 |
| `app/api/v1/auth.py` | User cap check; use `pick_least_loaded_app` in Strava OAuth; full account deletion endpoint with cascading purge | B2, A4, C3 |
| `app/api/v1/billing.py` | Self-hosted 501 guard on checkout + portal | B2 |
| `app/api/v1/webhooks.py` | Self-hosted 204 early return on Stripe webhook | B2 |
| `app/api/v1/instance.py` | New endpoint | B3 |
| `app/api/v1/router.py` | Include instance router, export router | B3, C3 |
| `app/api/v1/export.py` | New — user data export endpoint (GDPR) | C3 |
| `app/services/storage.py` | New file — `StorageService` | A5-ph1 |
| `app/api/v1/activities.py` | Dual-write GPX; read `gpx_storage_key` in download; ownership check on all activity endpoints; delete cascades storage | A5-ph1, C1, C2 |
| `app/services/sync.py` | Update `upload_komoot_to_strava` pending query | A1 |
| `scripts/backfill_gpx_to_storage.py` | New one-time script | A5-ph1 |
| `scripts/backfill_destination_platform.py` | New one-time script | A1 |
| `docker-compose.selfhosted.yml` | Renamed + updated | B5 |
| `docker-compose.cloud.yml` | New — Coolify-compatible compose with Traefik labels, pgBouncer, migrate init container; D7 adds `db-backup` service | B5, D3, D7 |
| `.env.selfhosted.template` | Remove Stripe vars; add deployment mode vars | B5 |
| `requirements.txt` | Add `aiobotocore>=2.13` | A5-ph1 |
| `app/main.py` | Multi-origin CORS using `FRONTEND_URLS`; startup migration check | D3, D8 |
| `frontend/hooks/use-instance.ts` | New hook | B4 |
| `frontend/app/(dashboard)/billing/page.tsx` | Guard with `billing_enabled` | B4 |
| `frontend/app/(dashboard)/dashboard/page.tsx` | Hide quota card when `!billing_enabled` | B4 |
| `frontend/app/(dashboard)/layout.tsx` or `sidebar.tsx` | Hide billing nav link when `!billing_enabled` | B4 |
| `backend/Dockerfile` | Ensure `alembic.ini` + `alembic/` are copied | D8 |
| `.github/workflows/check.yml` | New — GitHub Actions CI on PRs | D6 |

---

## C — Data Privacy & Integrity

These requirements apply across **all** A and B tasks. Each new feature or refactor must
be checked against this section before merging.

---

## C1 · Object Storage — Access Controls and Encryption at Rest

**Context:** Once GPX files leave the database (A5), they live in an S3/R2 bucket.
A misconfigured bucket policy would expose every user's GPS tracks publicly.

### Bucket policy (mandatory — configure before enabling `STORAGE_BACKEND=r2/s3`)

The bucket must be:
- **Private** — no public access, no public ACL
- **Encrypted at rest** — enable AES-256 server-side encryption (S3: SSE-S3 or SSE-KMS;
  R2: always encrypted by default)
- **Versioning disabled** — GPX files are write-once; versioning adds cost and complexity
  with no benefit here

For Cloudflare R2, the bucket privacy is enforced by default. For AWS S3, add a bucket
policy that denies `s3:GetObject` to `*` and only allows access from the IAM role used by
the backend service.

### Path structure enforces isolation

The storage key format `gpx/{user_id}/{activity_id}.gpx` means every object is namespaced
by the owner's UUID. This prevents enumeration: even with storage credentials, a query for
`gpx/{other_user_id}/` returns no results if the IAM policy scopes access to a prefix.

For cloud deployments, scope the IAM policy or R2 token to `gpx/*` read/write only —
no bucket-level list permission.

### Presigned URLs (preferred over direct streaming for cloud)

Rather than the API fetching GPX bytes and streaming them to the client, generate a
presigned URL with a short TTL:

```python
# In activities.py — GET /activities/{id}/gpx
if activity.gpx_storage_key and settings.STORAGE_BACKEND != "db":
    async with _get_s3() as client:
        url = await client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.STORAGE_BUCKET, "Key": activity.gpx_storage_key},
            ExpiresIn=300,   # 5 minutes
        )
    return RedirectResponse(url, status_code=302)
```

This means GPX bytes never flow through the API server, reducing bandwidth costs and
removing the API process as a data exfiltration vector. The presigned URL expires in 5
minutes so even if leaked it is useless shortly after.

For self-hosted (`STORAGE_BACKEND=db`), presigned URLs are not applicable — stream
directly from `gpx_data` as today.

### Ownership check before every GPX serve

Every call to `GET /activities/{id}/gpx` must verify `activity.user_id == current_user.id`
before serving bytes or generating a presigned URL. This check already exists but must be
preserved in the refactored GPX resolution logic from A5:

```python
if activity.user_id != user.id:
    raise HTTPException(status_code=403, detail="Not your activity.")
```

---

## C2 · Cascading Delete — Purge Object Storage on Activity Deletion

**Context:** When a user deletes an activity (or their entire account), any GPX blob in
object storage must be purged. Currently `DELETE /activities/{id}` only removes the DB row;
the blob would be orphaned.

### `backend/app/api/v1/activities.py` — delete endpoint

```python
from app.services.storage import StorageService

@router.delete("/{activity_id}")
async def delete_activity(activity_id: str, ...):
    activity = ...  # fetch + ownership check

    # Purge object storage blob first (non-fatal if already gone)
    if activity.gpx_storage_key:
        try:
            await StorageService.delete_gpx(activity.gpx_storage_key)
        except Exception as exc:
            logger.warning(
                "delete_activity: failed to purge storage key %s: %s",
                activity.gpx_storage_key,
                exc,
            )
            # Do not abort the DB delete because of a storage error.
            # The orphaned blob can be cleaned up by a lifecycle rule.

    await db.execute(
        delete(SyncedActivity).where(
            SyncedActivity.id == activity_id,
            SyncedActivity.user_id == user.id,
        )
    )
    await db.commit()
```

### Object storage lifecycle rule (belt-and-suspenders)

Configure an S3/R2 lifecycle rule on the bucket:

- **Abort incomplete multipart uploads** after 1 day
- **Delete objects with tag `orphaned=true`** after 30 days

Any blob not deleted during the API call (e.g., due to a network error) will be cleaned
up within 30 days. The tag is set by the `StorageService.delete_gpx()` implementation when
a hard delete fails:

```python
# In StorageService.delete_gpx, fallback on error:
await client.put_object_tagging(
    Bucket=settings.STORAGE_BUCKET,
    Key=key,
    Tagging={"TagSet": [{"Key": "orphaned", "Value": "true"}]},
)
```

---

## C3 · User Data Export + Account Deletion (GDPR / Right to Erasure)

**Context:** GDPR Article 17 (right to erasure) and Article 20 (right to data portability)
apply when any EU users are in scope. These must be implemented before public launch.

### Account deletion: `DELETE /api/v1/auth/account`

New endpoint that hard-deletes the user and all their data. The PostgreSQL schema already
has `ON DELETE CASCADE` on `user_id` FKs for `synced_activities`, `connections`,
`subscriptions`, `sync_rules`, etc. The endpoint only needs to:

1. Purge all `gpx_storage_key` blobs from object storage
2. Cancel any active Stripe subscription (send `stripe.Subscription.delete()`)
3. Delete the `User` row — cascade handles the rest

```python
@router.delete("/account", status_code=204)
async def delete_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete the authenticated user's account and all associated data."""
    # 1. Purge all GPX blobs
    result = await db.execute(
        select(SyncedActivity.gpx_storage_key).where(
            SyncedActivity.user_id == user.id,
            SyncedActivity.gpx_storage_key != None,  # noqa: E711
        )
    )
    for (key,) in result.all():
        try:
            await StorageService.delete_gpx(key)
        except Exception as exc:
            logger.warning("delete_account: storage purge failed for key %s: %s", key, exc)

    # 2. Cancel Stripe subscription (non-fatal)
    if settings.DEPLOYMENT_MODE == "cloud" and settings.STRIPE_SECRET_KEY:
        sub_result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        sub = sub_result.scalar_one_or_none()
        if sub and sub.stripe_subscription_id:
            try:
                import stripe as _stripe
                _stripe.Subscription.delete(sub.stripe_subscription_id)
            except Exception as exc:
                logger.warning("delete_account: Stripe cancellation failed: %s", exc)

    # 3. Delete user — ON DELETE CASCADE handles all child rows
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
    logger.info("Account deleted for user %s", user.id)
```

Wire this endpoint to a "Delete account" button in `frontend/app/(dashboard)/settings/page.tsx`
behind a confirmation dialog. The frontend must log the user out and clear the auth token
immediately after receiving a 204.

### Data export: `GET /api/v1/export/me`

New endpoint `backend/app/api/v1/export.py` that returns a JSON archive of everything
RoutePass holds about the user:

```python
@router.get("/me")
async def export_my_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export all personal data as a JSON file (GDPR Article 20)."""
    # Fetch all user-scoped records
    activities = (await db.execute(
        select(SyncedActivity).where(SyncedActivity.user_id == user.id)
    )).scalars().all()

    connections = (await db.execute(
        select(Connection).where(Connection.user_id == user.id)
    )).scalars().all()

    rules = (await db.execute(
        select(SyncRule).where(SyncRule.user_id == user.id)
    )).scalars().all()

    export = {
        "exported_at": datetime.now(UTC).isoformat(),
        "user": {
            "id": str(user.id),
            "email": user.email,
            "created_at": user.created_at.isoformat(),
        },
        "activities": [
            {
                "id": str(a.id),
                "name": a.activity_name,
                "sport_type": a.sport_type,
                "source": a.source,
                "destination_platform": a.destination_platform,
                "started_at": a.started_at.isoformat() if a.started_at else None,
                "distance_m": a.distance_m,
                "duration_seconds": a.duration_seconds,
                "elevation_up_m": a.elevation_up_m,
                "sync_status": a.sync_status,
                "synced_at": a.synced_at.isoformat(),
            }
            for a in activities
        ],
        "connections": [
            {
                "platform": c.platform,
                "display_name": c.display_name,
                "status": c.status,
                "created_at": c.created_at.isoformat(),
                # credentials_enc intentionally excluded
            }
            for c in connections
        ],
        "sync_rules": [
            {
                "name": r.name,
                "direction": r.direction,
                "conditions": r.conditions,
                "actions": r.actions,
                "is_active": r.is_active,
            }
            for r in rules
        ],
    }

    import json, io
    buf = io.BytesIO(json.dumps(export, indent=2).encode())
    return StreamingResponse(
        buf,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="routepass-export-{user.id}.json"'},
    )
```

**Important:** `credentials_enc` is explicitly excluded from the export. The export
contains metadata only — no encrypted credentials, no raw tokens, no Komoot passwords.
GPX file contents are also excluded by default (they can be downloaded individually via
`GET /activities/{id}/gpx`).

Add to `frontend/app/(dashboard)/settings/page.tsx`: a "Download my data" button that
calls this endpoint.

---

## C4 · Credential Isolation Hardening

**Context:** Each user's Komoot credentials and Strava tokens are already Fernet-encrypted
before storage. These guards verify that job logic can never accidentally process one
user's credentials under another user's job context.

### Per-user ownership assertion in every ARQ job

Every job in `sync_jobs.py` that writes a `SyncedActivity` row must assert that the
`user_id` on the DB record matches the `user_id` argument passed to the job. This is
currently implicit (jobs fetch the user by ID then write with `user.id`), but should be
made explicit with a guard:

```python
# In poll_user_sources, _run_komoot_to_intervals_icu, etc.
# After fetching the User record:
if str(user.id) != user_id:
    logger.error(
        "SECURITY: user_id mismatch in job — expected %s, got %s. Aborting.",
        user_id, user.id,
    )
    return
```

This catches any future refactor that accidentally swaps argument order.

### Connection record ownership check

`run_pipeline` loads source and destination `Connection` rows but currently does not
assert that `connection.user_id == user.id` before decrypting credentials. Add:

```python
if str(source.user_id) != user_id or str(dest.user_id) != user_id:
    logger.error(
        "SECURITY: pipeline %s connections belong to different user — aborting.",
        pipeline_id,
    )
    return
```

### Separate Fernet keys per data class (future-proofing)

Currently `KOMOOT_ENCRYPTION_KEY` is used for all encrypted blobs (Komoot credentials,
Strava tokens via `encrypt()`/`decrypt()`, connection `credentials_enc`). This means a
leaked encryption key compromises all classes of credentials simultaneously.

Future improvement: add `CONNECTION_ENCRYPTION_KEY` as a separate env var used
specifically for `Connection.credentials_enc`. The migration path:
1. Add `CONNECTION_ENCRYPTION_KEY` to `config.py` (defaults to `KOMOOT_ENCRYPTION_KEY` for
   backwards compat)
2. On `Connection` read, try `CONNECTION_ENCRYPTION_KEY` first, fall back to
   `KOMOOT_ENCRYPTION_KEY` (handles old rows)
3. On write, always use `CONNECTION_ENCRYPTION_KEY`
4. Run a migration script to re-encrypt all existing `credentials_enc` blobs under the
   new key

This is low-urgency but should be done before the platform handles Garmin/Polar OAuth
tokens (higher-value credentials than Komoot passwords).

### Never log credentials

Add a ruff/pylint rule or a pre-commit hook that flags any use of `logger.*` where
the argument contains the words `password`, `token`, `secret`, `credential`, or `key`
followed by a variable. All current usages should be audited.

The `KomootClient` constructor currently accepts `email` and `password` as plain strings —
ensure these are never passed to any logger call, even at DEBUG level.

---

## C5 · Audit Log for Sensitive Actions

**Context:** `JobAuditLog` exists for background jobs. Sensitive user-facing actions
(account deletion, credential changes, API key creation/revocation) currently have no
audit trail.

### Extend `JobAuditLog` or add a new `UserAuditLog` table

Option A — reuse `JobAuditLog` with a new `job_type` convention for user actions:
- `job_type="user_delete_account"`, `user_id=...`, `status="completed"`, `payload={"ip": "..."}`
- `job_type="api_key_created"`, etc.

Option B — add a dedicated `UserAuditLog` model (`backend/app/db/models/subscription.py`
or a new `audit.py`):

```python
class UserAuditLog(Base):
    __tablename__ = "user_audit_log"

    id: Mapped[UUID] = mapped_column(sa.UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[Optional[UUID]] = mapped_column(
        sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(sa.String, nullable=False)
    # action values: "account_deleted", "password_changed", "api_key_created",
    #                "api_key_revoked", "strava_connected", "strava_disconnected",
    #                "komoot_connected", "komoot_disconnected", "export_requested"
    ip_address: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    metadata: Mapped[Optional[dict]] = mapped_column(sa.JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True
    )
```

Option B is preferred — it keeps operational logs (`JobAuditLog`) separate from
compliance/security logs (`UserAuditLog`).

### Actions that must write a `UserAuditLog` entry

| Endpoint | Action value |
|---|---|
| `DELETE /auth/account` | `account_deleted` |
| `POST /auth/register` | `account_created` |
| `POST /auth/komoot` | `komoot_connected` |
| `DELETE /auth/komoot/disconnect` | `komoot_disconnected` |
| `GET /auth/strava/login` → callback | `strava_connected` |
| `DELETE /strava/disconnect` | `strava_disconnected` |
| `POST /api-keys` | `api_key_created` |
| `DELETE /api-keys/{id}` | `api_key_revoked` |
| `GET /export/me` | `export_requested` |

### Retention

`UserAuditLog` rows are retained indefinitely while the user account exists. When the
account is deleted (`DELETE /auth/account`), set `user_id = NULL` on audit rows (the FK
is `ON DELETE SET NULL`) — the log record survives for compliance purposes but is no
longer linked to a real user.

Keep audit rows for at least 90 days after `user_id` is set to NULL, then delete via a
scheduled cleanup job.

---

## Privacy Considerations by Task

| Task | Privacy requirement |
|---|---|
| A1 (schema) | `destination_activity_id` may contain external IDs — never expose these in list endpoints unless the user owns the activity |
| A5 (object storage) | Bucket must be private; presigned URLs preferred; delete blobs on activity/account delete (C2) |
| B3 (instance endpoint) | Safe to expose unauthenticated — contains no user data |
| C3 (account deletion) | Must trigger full cascade including storage purge (C2) and Stripe cancellation |
| A4 (Strava fan-out) | `pick_least_loaded_app` must never expose app IDs or usage counts to end-users via API |
| A2 (ARQ dedup key) | `_job_id=f"poll_user_{uid}"` embeds user UUID in a Redis key — ensure Redis ACLs restrict access to the worker namespace |
| C4 (credentials) | All Komoot/connection credentials must stay encrypted at every layer; never appear in logs, job payloads, or error messages |

---

## D — Coolify + Hetzner Cloud Deployment

RoutePass cloud runs on a Hetzner VPS managed by Coolify. This section defines the full
infrastructure: server sizing, networking, Coolify setup, Coolify-compatible Docker Compose,
object storage (Hetzner is S3-compatible), CI/CD, migrations, and backups.

---

## D1 · Hetzner Server + Network + Firewall

### Server choice

| Stage | Type | Specs | Monthly cost (approx) |
|---|---|---|---|
| Launch (<200 users) | **CX32** | 4 vCPU, 8 GB RAM, 80 GB SSD | ~€13 |
| Growth (200–1000 users) | **CX42** | 8 vCPU, 16 GB RAM, 160 GB SSD | ~€26 |
| Scale | Separate DB server + CX32 for app | — | ~€26 + €13 |

Start with CX32. Upgrade is a 2-minute resize in the Hetzner Cloud console — no data loss,
minimal downtime.

Choose **Nuremberg (nbg1)** or **Helsinki (hel1)** — both in the EU, ideal for GDPR.
Do not use Ashburn (US) if your user base is primarily European.

### Private network

Create a Hetzner private network (`10.0.0.0/16`) and attach the VPS to it. This lets you
add a separate database server later (Hetzner Managed DB or a second VPS) without exposing
the connection over the public internet.

If you start with a single VPS (Coolify + PostgreSQL both on the same machine), you don't
need the private network immediately — but create it now so migration is trivial later.

### Firewall rules

Create a Hetzner Cloud Firewall and attach it to the VPS. Allow only:

| Direction | Protocol | Port | Source | Purpose |
|---|---|---|---|---|
| Inbound | TCP | 22 | Your IP only | SSH |
| Inbound | TCP | 80 | Any | HTTP (Let's Encrypt challenge) |
| Inbound | TCP | 443 | Any | HTTPS (public traffic) |
| Inbound | TCP | 8000 | **Block** | Never expose FastAPI port directly |
| Inbound | TCP | 3000 | **Block** | Never expose Next.js port directly |
| All other inbound | — | — | Block | Default deny |

Traefik (managed by Coolify) handles all inbound HTTP/HTTPS via ports 80 and 443.
The application ports (8000, 3000) are **internal only** and must never be in the
Hetzner Firewall allow list.

---

## D2 · Coolify Installation + Domain Wiring

### Install Coolify on the VPS

```bash
# SSH into the server
ssh root@<hetzner-vps-ip>

# Run the official Coolify installer
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

Coolify installs Docker, sets up Traefik as the reverse proxy, and starts the Coolify
management UI on port 8000 (temporarily accessible via `http://<ip>:8000` during setup;
it will be moved behind Traefik after domain wiring).

### Domain DNS

Point these DNS records at the Hetzner VPS IP (use A records, not CNAME for the apex):

| Record | Type | Target | Purpose |
|---|---|---|---|
| `routepass.app` | A | `<VPS IP>` | Marketing/landing page (Next.js) |
| `app.routepass.app` | A | `<VPS IP>` | Dashboard (Next.js) |
| `api.routepass.app` | A | `<VPS IP>` | FastAPI backend |
| `coolify.routepass.app` | A | `<VPS IP>` | Coolify management UI (restrict access) |

Coolify + Traefik will automatically provision Let's Encrypt TLS certificates for each
subdomain as soon as traffic hits port 80.

### Restrict Coolify UI access

In Coolify settings, enable IP allowlist for the Coolify management UI, or add a Traefik
middleware that requires HTTP Basic Auth. The Coolify UI exposes deployment controls and
environment secrets — it must not be publicly accessible.

---

## D3 · `docker-compose.cloud.yml` — Coolify-Compatible

Coolify deploys Docker Compose files from a git repository. Key differences from the dev
compose:

- **No `env_file`** — Coolify injects env vars from its secrets store at deploy time
- **Traefik labels** on `api` and `frontend` for HTTPS routing + SSL termination
- **`coolify` network** — join Coolify's shared proxy network so Traefik can reach services
- **pgBouncer sidecar** between API and PostgreSQL
- **`image:` instead of `build:`** (recommended for production) — build the Docker images
  in CI and push to a registry; Coolify pulls and deploys. If building in Coolify,
  use `build:` sections as in the dev compose.
- **No port mappings** on api/frontend — Traefik routes by hostname, not port

### `docker-compose.cloud.yml`

```yaml
# Cloud SaaS deployment for Coolify on Hetzner.
# Deploy via Coolify → New Application → Docker Compose → point at this file.
# All environment variables are injected by Coolify — do not use env_file here.

name: routepass-cloud

services:

  # ── Application ─────────────────────────────────────────────────────────────

  api:
    build: ./backend
    restart: unless-stopped
    # No ports: block — Traefik routes by hostname label, not port binding
    networks:
      - internal
      - coolify                        # Coolify's shared proxy network
    depends_on:
      db:      {condition: service_healthy}
      redis:   {condition: service_healthy}
      pgbouncer: {condition: service_started}
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.routepass-api.rule=Host(`api.routepass.app`)"
      - "traefik.http.routers.routepass-api.entrypoints=https"
      - "traefik.http.routers.routepass-api.tls.certresolver=letsencrypt"
      - "traefik.http.services.routepass-api.loadbalancer.server.port=8000"
      # Security headers middleware (defined once, reused by all routers)
      - "traefik.http.routers.routepass-api.middlewares=security-headers@file"

  worker:
    build: ./backend
    command: python -m arq app.jobs.worker.WorkerSettings
    restart: unless-stopped
    networks:
      - internal
    depends_on:
      db:    {condition: service_healthy}
      redis: {condition: service_healthy}
    deploy:
      replicas: 2            # safe after A2 (ARQ dedup key + scheduler lock)

  frontend:
    build:
      context: ./frontend
      args:
        # Internal Docker DNS — Next.js rewrites /api/* to this at runtime
        INTERNAL_API_URL: http://api:8000
    restart: unless-stopped
    networks:
      - internal
      - coolify
    depends_on:
      - api
    labels:
      - "traefik.enable=true"
      # Apex domain + app subdomain both route to the frontend
      - "traefik.http.routers.routepass-fe.rule=Host(`routepass.app`) || Host(`app.routepass.app`)"
      - "traefik.http.routers.routepass-fe.entrypoints=https"
      - "traefik.http.routers.routepass-fe.tls.certresolver=letsencrypt"
      - "traefik.http.services.routepass-fe.loadbalancer.server.port=3000"
      - "traefik.http.routers.routepass-fe.middlewares=security-headers@file"

  # ── Migrations init container ────────────────────────────────────────────────
  # Runs alembic upgrade head before the api starts, then exits.
  # Coolify's depends_on + service_completed_successfully handles the ordering.

  migrate:
    build: ./backend
    command: alembic upgrade head
    restart: "no"
    networks:
      - internal
    depends_on:
      db: {condition: service_healthy}

  # Update api/worker to depend on migrate completing:
  # depends_on:
  #   migrate: {condition: service_completed_successfully}

  # ── pgBouncer ────────────────────────────────────────────────────────────────

  pgbouncer:
    image: bitnami/pgbouncer:latest
    restart: unless-stopped
    networks:
      - internal
    environment:
      POSTGRESQL_HOST: db
      POSTGRESQL_PORT: "5432"
      POSTGRESQL_USERNAME: "${POSTGRES_USER}"
      POSTGRESQL_PASSWORD: "${POSTGRES_PASSWORD}"
      POSTGRESQL_DATABASE: "${POSTGRES_DB}"
      PGBOUNCER_POOL_MODE: transaction
      PGBOUNCER_MAX_CLIENT_CONN: "200"
      PGBOUNCER_DEFAULT_POOL_SIZE: "20"
      PGBOUNCER_AUTH_TYPE: md5
    depends_on:
      db: {condition: service_healthy}

  # ── Data services ─────────────────────────────────────────────────────────────

  db:
    image: postgres:16-alpine
    restart: unless-stopped
    networks:
      - internal
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: "${POSTGRES_DB}"
      POSTGRES_USER: "${POSTGRES_USER}"
      POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    networks:
      - internal
    command: >
      redis-server
      --requirepass "${REDIS_PASSWORD}"
      --appendonly yes
      --appendfsync everysec
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

networks:
  internal:
    driver: bridge
  coolify:
    external: true          # Coolify creates this network; we join it

volumes:
  postgres_data:
  redis_data:
```

### Notes on the Coolify compose

**`env_file` is absent intentionally.** Coolify injects all env vars at deploy time from
its secrets store. You configure them once in the Coolify UI under
Application → Environment Variables.

**The `migrate` service** exits after running `alembic upgrade head`. Coolify honours
`service_completed_successfully` in `depends_on`, so the api and worker will not start
until migrations finish. Add `migrate: {condition: service_completed_successfully}` to the
api and worker `depends_on` blocks. This replaces any manual `make migrate` step in the
deployment workflow.

**Redis password:** Redis in the cloud must be password-protected. The `REDIS_URL` env var
in the application must use the form `redis://:${REDIS_PASSWORD}@redis:6379`. Update
`app/core/config.py` — the default `REDIS_URL = "redis://redis:6379"` is fine for dev
(no password); for cloud Coolify injects the full URL with password.

**pgBouncer:** The api and worker `DATABASE_URL` must point at pgBouncer, not postgres
directly: `postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@pgbouncer:5432/${POSTGRES_DB}`.
pgBouncer exposes the same port as Postgres (5432) so the connection string is identical
except the hostname is `pgbouncer`.

### Code change needed in `backend/app/main.py`

CORS `allow_origins` currently uses `settings.FRONTEND_URL` in production. With Coolify
this needs to match both the apex domain and the app subdomain:

```python
# In config.py, replace single FRONTEND_URL with a list:
FRONTEND_URLS: str = "https://routepass.app,https://app.routepass.app"

# In main.py:
allow_origins = settings.FRONTEND_URLS.split(",") if settings.ENVIRONMENT != "development" else ["*"]
```

---

## D4 · Hetzner Object Storage for GPX Files

Hetzner Object Storage is S3-compatible, EU-hosted, and inexpensive (~€6/month for
1 TB). It maps directly to the `StorageService` implementation from A5.

### Create the bucket

1. In Hetzner Cloud Console → Object Storage → Create Bucket
2. Region: **Nuremberg (eu-central)** — same region as the VPS for minimal latency
3. Bucket name: `routepass-gpx` (private — do not enable public read)
4. Enable server-side encryption (Hetzner enables this by default)

### Create S3 access credentials

In Hetzner Cloud Console → Object Storage → Access Keys → Create:
- Note the Access Key ID and Secret Access Key
- These are added as Coolify environment secrets (never committed to the repo)

### Endpoint and region

Hetzner Object Storage S3 endpoint: `https://fsn1.your-objectstorage.com`
(replace `fsn1` with your chosen region: `nbg1` for Nuremberg, `hel1` for Helsinki).

### Environment variables for Coolify

```
STORAGE_BACKEND=s3
STORAGE_BUCKET=routepass-gpx
STORAGE_ENDPOINT_URL=https://nbg1.your-objectstorage.com
STORAGE_ACCESS_KEY_ID=<from Hetzner>
STORAGE_SECRET_ACCESS_KEY=<from Hetzner>
STORAGE_REGION=eu-central
```

The `StorageService` from A5 uses `aiobotocore` with a custom `endpoint_url` — this
works out of the box with any S3-compatible API including Hetzner Object Storage.

### Verify GDPR alignment

Hetzner is a German company. Object Storage data resides in the EU data centre you select.
This satisfies GDPR data residency requirements for EU users with no additional SCCs or
transfer impact assessments.

---

## D5 · Database Strategy: Coolify-managed vs Hetzner Managed DB

### Option A: Coolify-managed PostgreSQL (recommended for launch)

The `db` service in `docker-compose.cloud.yml` above runs PostgreSQL in a Docker container
on the same VPS. Data persists to a named Docker volume (`postgres_data`).

**Pros:** Zero extra cost; simple setup; Coolify handles container lifecycle.
**Cons:** Database lives on the same disk as the OS; no automatic failover; backup is
manual (see D7).

**Use this until you have meaningful user data worth protecting with a managed service.**

### Option B: Hetzner Managed Databases (recommended post-launch)

Hetzner offers PostgreSQL 16 as a managed service starting at ~€30/month (2 vCPU,
4 GB RAM, 40 GB). Features: automatic daily backups (7-day retention), point-in-time
recovery, automatic minor version upgrades, private network access.

Migration path from Option A to Option B:
1. Create the Hetzner Managed DB in the same private network as the VPS
2. Use `pg_dump` to export from the Coolify-managed PostgreSQL container
3. Import into the managed DB with `pg_restore`
4. Update `DATABASE_URL` (and pgBouncer's `POSTGRESQL_HOST`) in Coolify env vars
5. Remove the `db` service from `docker-compose.cloud.yml` — the managed DB replaces it

The `DATABASE_URL` for the managed DB uses the private network IP, not the public hostname,
so the connection never leaves the Hetzner datacenter.

---

## D6 · CI/CD — Auto-Deploy on Push

Coolify supports automatic re-deployment triggered by a GitHub webhook.

### Setup

1. In Coolify → Application → Settings → Source: connect the GitHub repository with a
   deploy key (Coolify generates an SSH key; add the public half to GitHub → Deploy Keys)
2. In Coolify → Application → Settings → Webhooks: copy the Coolify webhook URL
3. In GitHub → Repository → Settings → Webhooks: add the Coolify webhook URL, trigger on
   `push` events to the `main` branch
4. In Coolify → Application → Settings: enable "Auto-deploy on push to main"

On every push to `main`:
1. Coolify pulls the latest code
2. Builds Docker images from the Dockerfiles (backend + frontend)
3. Runs `docker compose up -d --build` with the cloud compose
4. The `migrate` init container runs `alembic upgrade head` before the api starts
5. Traefik automatically serves the new containers under the same domains

### Branch protection

In GitHub → Branch Rules, protect `main`:
- Require pull request reviews (1 reviewer minimum)
- Require status checks to pass: `make check` (lint + tests) via GitHub Actions

### GitHub Actions workflow (`.github/workflows/check.yml`)

```yaml
name: CI

on:
  pull_request:
    branches: [main]

jobs:
  check:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: routepass_test
          POSTGRES_USER: app
          POSTGRES_PASSWORD: test
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.9"
          cache: pip

      - name: Install backend deps
        run: pip install -r backend/requirements.txt

      - name: Run lint + tests
        working-directory: backend
        env:
          DATABASE_URL: postgresql+asyncpg://app:test@localhost:5432/routepass_test
          REDIS_URL: ""    # tests mock Redis
          SECRET_KEY: test-secret-key-32-chars-minimum
          KOMOOT_ENCRYPTION_KEY: ${{ secrets.TEST_ENCRYPTION_KEY }}
          STRAVA_CLIENT_ID: "0"
          STRAVA_CLIENT_SECRET: "test"
        run: make check
```

Store `TEST_ENCRYPTION_KEY` as a GitHub Actions secret (not in the repo). Use a
dedicated test Fernet key that never touches production data.

---

## D7 · Backup Strategy

Two layers: application-level database dumps + infrastructure-level server snapshots.

### Layer 1: Daily PostgreSQL dump (application-level)

> **Extends D3.** Add the `db-backup` service and `db_backups` volume to the
> `docker-compose.cloud.yml` defined in D3. The D3 block shows the core services;
> D7 appends this backup sidecar. Both land in the same file.

Add a backup service to `docker-compose.cloud.yml` using `postgres:16-alpine` with a
`pg_dump` cron:

```yaml
  db-backup:
    image: postgres:16-alpine
    restart: unless-stopped
    networks:
      - internal
    environment:
      PGPASSWORD: "${POSTGRES_PASSWORD}"
    volumes:
      - db_backups:/backups
    entrypoint: >
      sh -c "
        while true; do
          sleep 86400;
          pg_dump -h db -U ${POSTGRES_USER} -d ${POSTGRES_DB} -Fc
            -f /backups/routepass_$$(date +%Y%m%d_%H%M%S).dump;
          # Keep only last 7 dumps
          ls -t /backups/*.dump | tail -n +8 | xargs -r rm;
        done
      "
    depends_on:
      db: {condition: service_healthy}
```

Add `db_backups` to the volumes section.

For cloud deployments with Hetzner Managed DB (Option B in D5): daily backups are
automatic and you get point-in-time recovery. Layer 1 above can be dropped once you
migrate to managed DB.

### Layer 2: Hetzner server snapshot (infrastructure-level)

Hetzner Cloud supports automated server snapshots (€0.0119/GB/month). Enable:

In Hetzner Cloud Console → Server → Backups → Enable (daily, 7 snapshots retained).

A server snapshot includes the Docker volumes (`postgres_data`, `redis_data`,
`db_backups`). This provides a fast restore path if the OS or Docker state becomes
corrupted.

### Layer 3: Object storage versioning (GPX files)

For Hetzner Object Storage, versioning is not available. Instead:
- The lifecycle rule from C2 (delete orphaned blobs after 30 days) prevents buildup
- GPX files are write-once and user-deletable — no versioning needed

If a user requests a GDPR export (C3), the JSON export does not include raw GPX bytes.
Users download individual GPX files via `GET /activities/{id}/gpx` while their account
is active.

### Restore runbook (document this before going live)

```
1. Database restore from dump:
   docker exec -i <db-container> pg_restore -U app -d routepass -Fc < backup.dump

2. Full restore from Hetzner snapshot:
   - Hetzner Console → Snapshots → Restore
   - Reattach floating IP if applicable
   - Run `coolify restart` to bring services back up

3. Verify: curl https://api.routepass.app/health → {"status":"ok"}
```

---

## D8 · Migrations as Init Container

**Eliminates the manual `make migrate` step from every deployment.**

The `migrate` service in `docker-compose.cloud.yml` already defines this pattern.
Two code changes are needed to make it robust:

### `backend/app/main.py` — guard against running before DB is migrated

Add a startup check in `lifespan`:

```python
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

async def _check_migrations() -> None:
    """Warn if the database is behind the latest Alembic revision."""
    from app.db.session import engine
    alembic_cfg = AlembicConfig("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    head_rev = script.get_current_head()

    async with engine.connect() as conn:
        context = MigrationContext.configure(await conn.run_sync(lambda c: c))
        current_rev = context.get_current_revision()

    if current_rev != head_rev:
        logger.warning(
            "Database is at revision %s but app expects %s. "
            "Run 'alembic upgrade head' before starting the server.",
            current_rev,
            head_rev,
        )
```

Call `await _check_migrations()` inside `lifespan` after `_bootstrap_strava_app()`.
The app starts regardless (non-fatal warning), but the log entry is clearly visible in
Coolify's log viewer.

### `backend/Dockerfile` — ensure alembic.ini is present

The `migrate` service runs `alembic upgrade head` — this requires `alembic.ini` to be
in the working directory. Verify the Dockerfile copies it:

```dockerfile
COPY alembic.ini .
COPY alembic/ ./alembic/
```

If not present, add these two lines to the backend Dockerfile.

---

## D9 · Coolify Environment Variables Reference

> **Reference appendix — no code changes.** This section is a checklist for configuring
> Coolify's secrets store, not an execution step. All variables described here are used
> by the code changes in B1, D3, and D4.

All secrets are stored in Coolify → Application → Environment Variables (encrypted at
rest). Nothing sensitive lives in the repository. This is the complete list for the cloud
deployment:

### Application secrets

```
# Django-style secret key — generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=

# Fernet key for encrypting Komoot credentials
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
KOMOOT_ENCRYPTION_KEY=

# Deployment mode
DEPLOYMENT_MODE=cloud
ENVIRONMENT=production
```

### Database

```
POSTGRES_DB=routepass
POSTGRES_USER=app
POSTGRES_PASSWORD=<strong random password>

# Points at pgBouncer, not postgres directly
DATABASE_URL=postgresql+asyncpg://app:<password>@pgbouncer:5432/routepass
```

### Redis

```
REDIS_PASSWORD=<strong random password>
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379
```

### Strava

```
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
STRAVA_WEBHOOK_VERIFY_TOKEN=<any random string>
```

### Stripe

```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PRO=price_...
STRIPE_PRICE_LIFETIME=price_...
```

### Object storage (Hetzner)

```
STORAGE_BACKEND=s3
STORAGE_BUCKET=routepass-gpx
STORAGE_ENDPOINT_URL=https://nbg1.your-objectstorage.com
STORAGE_ACCESS_KEY_ID=
STORAGE_SECRET_ACCESS_KEY=
STORAGE_REGION=eu-central
```

### OAuth (optional)

```
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
```

### URLs

```
# FRONTEND_URLS replaces the legacy FRONTEND_URL — use the comma-separated form.
# B1 adds this field to config.py; main.py reads it for multi-origin CORS.
FRONTEND_URLS=https://routepass.app,https://app.routepass.app
```

### Worker tuning (cloud defaults)

```
ARQ_MAX_JOBS=10
DB_POOL_SIZE=5         # per API replica; pgBouncer handles the rest
DB_MAX_OVERFLOW=10
```

---

## D — Infrastructure Considerations by Privacy Task

| Task | Infra implication |
|---|---|
| C1 (object storage access) | Hetzner Object Storage bucket is private by default; S3 credentials stored only in Coolify secrets, never in repo or container image |
| C2 (cascading delete) | `StorageService.delete_gpx` calls Hetzner Object Storage delete API — verify Hetzner returns 204 for non-existent keys (it does) |
| C3 (GDPR, data export) | Hetzner EU data centres satisfy GDPR residency; no SCCs needed for German-hosted EU data |
| C4 (credential isolation) | Redis on private `internal` network; not reachable from outside the Docker compose network; password-protected |
| C5 (audit log) | `UserAuditLog` records persist in PostgreSQL; included in db-backup layer |
| D7 (backups) | DB dumps stored in `db_backups` volume on the same VPS — for higher security, push dumps to a second Hetzner Object Storage bucket in a different region via the backup container |

---

## E — Multi-Directional Sync Completeness

Section A1 fixes the schema foundation. This section covers every remaining gap needed
to make multi-directional sync actually correct and complete end-to-end.

---

## E1 · Fix Premature `sync_direction` at Ingest Time

**Priority: HIGH — must land in the same PR as A1**

`ingest_komoot_tours` in `backend/app/services/sync.py` currently stores
`sync_direction="komoot_to_strava"` at ingest time (line 206). This is wrong: the record
is being *received from Komoot*, not yet pushed to Strava. `sync_direction` should reflect
what happened, not what is planned.

After A1, `sync_direction` has a richer set of valid values and `destination_platform`
carries the actual destination once an upload occurs. Setting a direction prematurely
conflates two distinct events (ingest vs. upload) and makes queries on direction
unreliable.

### `backend/app/services/sync.py` — `ingest_komoot_tours`

```python
# BEFORE (line 206):
sync_direction="komoot_to_strava",

# AFTER: direction is NULL at ingest; set when uploaded to a destination
sync_direction=None,
destination_platform=None,
```

### `backend/app/services/sync.py` — `sync_komoot_to_strava` (legacy path)

The same method also creates `SyncedActivity` records directly (lines 583–594) when
using the old combined ingest+upload path. After A1, update the success block:

```python
activity_record = SyncedActivity(
    user_id=user.id,
    komoot_tour_id=tour.id,
    strava_activity_id=activity_id,
    source="komoot",
    sync_direction="komoot_to_strava",
    sync_status="completed",
    destination_platform="strava",           # add
    destination_activity_id=activity_id,     # add
    activity_name=tour.name,
    sport_type=tour.sport,
    distance_m=tour.distance_m,
    elevation_up_m=tour.elevation_up_m,
    started_at=tour.date,
)
```

---

## E2 · Fix `upload_komoot_to_strava` — Write `destination_platform` on Success

**Priority: HIGH — must land in the same PR as A1**

`upload_komoot_to_strava` in `services/sync.py` (line 441) only writes
`act.strava_activity_id = strava_activity_id` on success. After A1, it must also set the
two new destination columns so the activity's state is fully correct:

```python
# In upload_komoot_to_strava, success block:
act.strava_activity_id = strava_activity_id
act.destination_platform = "strava"          # add
act.destination_activity_id = strava_activity_id  # add
act.sync_direction = "komoot_to_strava"      # already set but make explicit
await self.db.commit()
```

Also update the Strava-duplicate detection branch (where a duplicate is detected and the
existing Strava ID is linked):

```python
act.strava_activity_id = existing_id
act.destination_platform = "strava"          # add
act.destination_activity_id = existing_id   # add
await self.db.commit()
```

---

## E3 · Implement `_run_strava_to_intervals_icu` Pipeline Handler

**Priority: MEDIUM — `strava_to_intervals_icu` is in the enum; the UI lets users create
this pipeline; without the handler it silently does nothing.**

### What it needs to do

1. Fetch new Strava activities since the user's `last_strava_sync_at` watermark
2. For each activity, fetch GPS data via `StravaClient.get_activity_streams()`
3. Convert streams to GPX via the existing `_streams_to_gpx()` helper in `strava.py`
4. Upload to Intervals.icu via `IntervalsIcuClient.upload_gpx()`
5. Write a `SyncedActivity` record with `source="strava"`, `destination_platform="intervals_icu"`, `sync_direction="strava_to_intervals_icu"`

### `backend/app/jobs/sync_jobs.py` — add handler

```python
async def _run_strava_to_intervals_icu(
    db: object,
    pipeline: Pipeline,
    user: User,
    source: Connection,   # platform="strava"
    dest: Connection,     # platform="intervals_icu"
) -> None:
    """Handle a Strava→Intervals.icu pipeline.

    Fetches new Strava activities since the last sync watermark, converts each
    to GPX using Strava's streams API, and uploads to Intervals.icu.
    """
    if not dest.credentials_enc:
        logger.error("_run_strava_to_intervals_icu: no dest credentials for %s", dest.id)
        return

    # Resolve Strava access token (prefer user's linked token)
    strava_access_token: Optional[str] = None
    strava_app: Optional[StravaApp] = None
    if user.strava_token:
        strava_access_token = await _get_valid_strava_access_token(user)
        app_res = await db.execute(
            select(StravaApp).where(StravaApp.id == user.strava_token.strava_app_id)
        )
        strava_app = app_res.scalar_one_or_none()

    if not strava_access_token or not strava_app:
        logger.error("_run_strava_to_intervals_icu: no Strava token for user %s", user.id)
        return

    dst_creds = json.loads(security.decrypt(dest.credentials_enc))
    intervals_client = IntervalsIcuClient(
        api_key=dst_creds["api_key"],
        athlete_id=dst_creds["athlete_id"],
    )

    strava_client = StravaClient(access_token=strava_access_token)
    tier_str = user.subscription.tier if user.subscription else "free"

    # Watermark: use last_strava_sync_at; default 30 days back
    from app.db.models.sync import UserSyncState as _USS
    state_res = await db.execute(select(_USS).where(_USS.user_id == user.id))
    state = state_res.scalar_one_or_none()
    since = (
        state.last_strava_sync_at
        if state and state.last_strava_sync_at
        else datetime.now(UTC) - timedelta(days=30)
    )

    try:
        activities = await rate_limit_guard.call(
            strava_app.id,
            tier_str,
            strava_client.get_activities,
            after=int(since.timestamp()),
            per_page=50,
        )
    except Exception as exc:
        logger.error("_run_strava_to_intervals_icu: Strava fetch failed: %s", exc)
        return

    synced_count = 0
    for activity in activities:
        strava_id = str(activity.get("id", ""))
        if not strava_id:
            continue

        # Pipeline-scoped dedup
        from app.db.models.sync import SyncedActivity as _SA
        already = await db.execute(
            select(_SA).where(
                _SA.pipeline_id == pipeline.id,
                _SA.strava_activity_id == strava_id,
                _SA.destination_platform == "intervals_icu",
                _SA.sync_status == "completed",
            )
        )
        if already.scalar_one_or_none():
            continue

        try:
            # Fetch GPS streams and convert to GPX
            streams = await rate_limit_guard.call(
                strava_app.id,
                tier_str,
                strava_client.get_activity_streams,
                activity_id=strava_id,
            )
            gpx_bytes = strava_client._streams_to_gpx(
                streams,
                name=activity.get("name", ""),
            )
            if not gpx_bytes:
                logger.debug(
                    "_run_strava_to_intervals_icu: no GPS data for activity %s — skipping",
                    strava_id,
                )
                continue

            sport = activity.get("sport_type") or activity.get("type")
            icu_activity_id = await intervals_client.upload_gpx(
                gpx_bytes=gpx_bytes,
                name=activity.get("name", "Activity"),
                sport_type=sport,
                external_id=f"strava_{strava_id}",
            )

            started_at = None
            try:
                started_at = datetime.fromisoformat(
                    activity.get("start_date", "").replace("Z", "+00:00")
                )
            except Exception:
                pass

            record = _SA(
                user_id=user.id,
                pipeline_id=pipeline.id,
                strava_activity_id=strava_id,
                source="strava",
                sync_direction="strava_to_intervals_icu",
                sync_status="completed",
                destination_platform="intervals_icu",
                destination_activity_id=icu_activity_id,
                activity_name=activity.get("name"),
                sport_type=sport,
                distance_m=activity.get("distance"),
                elevation_up_m=activity.get("total_elevation_gain"),
                duration_seconds=activity.get("moving_time"),
                started_at=started_at,
            )
            db.add(record)
            await db.commit()
            synced_count += 1

        except Exception as exc:
            logger.error(
                "_run_strava_to_intervals_icu: failed for activity %s: %s",
                strava_id,
                exc,
            )

    logger.info(
        "_run_strava_to_intervals_icu: pipeline %s → %d activities synced",
        pipeline.id,
        synced_count,
    )
```

### Wire into `run_pipeline` dispatch

```python
# In run_pipeline():
if pair == ("komoot", "strava"):
    await _run_komoot_to_strava(db, pipeline, user, source, dest)
elif pair == ("komoot", "intervals_icu"):
    await _run_komoot_to_intervals_icu(db, pipeline, user, source, dest)
elif pair == ("komoot", "runalyze"):
    await _run_komoot_to_runalyze(db, pipeline, user, source, dest)
elif pair == ("strava", "intervals_icu"):              # ADD
    await _run_strava_to_intervals_icu(db, pipeline, user, source, dest)
elif pair == ("strava", "runalyze"):                  # ADD (E4)
    await _run_strava_to_runalyze(db, pipeline, user, source, dest)
```

---

## E4 · Implement `_run_strava_to_runalyze` Pipeline Handler

**Priority: MEDIUM — identical pattern to E3, different destination client**

```python
async def _run_strava_to_runalyze(
    db: object,
    pipeline: Pipeline,
    user: User,
    source: Connection,
    dest: Connection,
) -> None:
    """Handle a Strava→Runalyze pipeline.

    Same watermark + streams-to-GPX pattern as _run_strava_to_intervals_icu.
    """
    if not dest.credentials_enc:
        logger.error("_run_strava_to_runalyze: no dest credentials for %s", dest.id)
        return

    # (Strava token resolution — identical to E3, extract to shared helper in E3 PR)

    dst_creds = json.loads(security.decrypt(dest.credentials_enc))
    runalyze_client = RunalyzeClient(access_token=dst_creds["access_token"])

    # ... watermark fetch, loop over activities, same structure as E3 ...

    # Record:
    record = _SA(
        user_id=user.id,
        pipeline_id=pipeline.id,
        strava_activity_id=strava_id,
        source="strava",
        sync_direction="strava_to_runalyze",
        sync_status="completed",
        destination_platform="runalyze",
        destination_activity_id=runalyze_activity_id,
        ...
    )
```

> **Implementation note:** Extract the Strava-token resolution + watermark + streams
> logic into a shared helper `_get_strava_activities_since(db, pipeline, user, strava_app)`
> when implementing E3, so E4 and any future Strava-source handlers call it instead of
> duplicating 30 lines.

---

## E5 · Per-Connection Sync Watermarks

**Priority: MEDIUM — required before adding any new source platform (Garmin, Polar)**

### The current problem

`UserSyncState` has two columns: `last_komoot_sync_at` and `last_strava_sync_at`. These
are global per-user, not per-connection. This means:

- A user with two Komoot connections (impossible today, but realistic with Garmin/Polar)
  would share a single watermark across both
- When Garmin is added as a source, there is nowhere to store its watermark without adding
  a new column to `UserSyncState` every time a new platform is supported

### The fix: `connection_sync_state` table

#### `backend/alembic/versions/010_connection_sync_state.py` (new migration)

```python
"""Add per-connection sync watermarks

Replaces the two global platform columns in user_sync_state with a separate
table keyed on (user_id, connection_id). Backwards-compatible: the global
columns are kept and used as fallback for connections that predate this migration.

Revision ID: 010
Revises: 008

Note: migration 009 (drop gpx_data) is deferred and optional. E5 chains from 008
directly. If 009 has been applied before running E5, update down_revision to "009".
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.create_table(
        "connection_sync_state",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id", sa.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id", sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String, nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("connection_id", name="uq_connection_sync_state_connection"),
    )

def downgrade() -> None:
    op.drop_table("connection_sync_state")
```

#### `backend/app/db/models/sync.py` — new `ConnectionSyncState` model

```python
class ConnectionSyncState(Base):
    __tablename__ = "connection_sync_state"
    __table_args__ = (
        sa.UniqueConstraint("connection_id", name="uq_connection_sync_state_connection"),
    )

    id: Mapped[UUID] = mapped_column(sa.UUID(as_uuid=True), primary_key=True, default=uuid4)
    connection_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
```

#### Migration path for existing watermarks

`poll_user_sources` in `sync_jobs.py` currently updates `user.last_komoot_poll_at` and
`user.next_komoot_poll_at`. After E5, per-connection state is used instead. Update
`poll_user_sources` to:

1. Load or create a `ConnectionSyncState` row for each `conn` in `source_connections`
2. Pass `state.last_synced_at` to `ingest_komoot_tours` / future Garmin ingest as
   `since`
3. Write `state.last_synced_at = datetime.now(UTC)` after successful ingest

Keep the global `UserSyncState.last_komoot_sync_at` fallback for users who connected
before this migration. If `ConnectionSyncState` row doesn't exist and
`UserSyncState.last_komoot_sync_at` is set, seed the `ConnectionSyncState` row from the
global value on first access.

---

## E6 · Garmin Connect Source Implementation

**Priority: LOW-MEDIUM — requires E5 (per-connection watermarks)**

`_SOURCE_PLATFORMS` already includes `"garmin"`. The connections page UI shows "coming
soon" for Garmin. The job skips Garmin connections with a log line.

### New file: `backend/app/services/garmin.py`

Use the `garminconnect` PyPI package (unofficial but widely used, same pattern as
Komoot's unofficial v007 API):

```python
"""Garmin Connect client for fetching activities."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
import garminconnect  # pip install garminconnect

logger = logging.getLogger(__name__)


class GarminClient:
    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._client: Optional[garminconnect.Garmin] = None

    async def _ensure_connected(self) -> None:
        if self._client is None:
            import asyncio
            self._client = garminconnect.Garmin(self._email, self._password)
            await asyncio.to_thread(self._client.login)

    async def get_activities_since(
        self, since: datetime, limit: int = 100
    ) -> list[dict]:
        """Return activities newer than `since`. Returns raw Garmin activity dicts."""
        await self._ensure_connected()
        import asyncio
        activities = await asyncio.to_thread(
            self._client.get_activities_by_date,
            since.strftime("%Y-%m-%d"),
            datetime.now().strftime("%Y-%m-%d"),
            limit=limit,
        )
        return activities or []

    async def download_gpx(self, activity_id: str) -> bytes:
        """Download a GPX file for a single Garmin activity."""
        await self._ensure_connected()
        import asyncio
        gpx_data = await asyncio.to_thread(
            self._client.download_activity,
            int(activity_id),
            dl_fmt=self._client.ActivityDownloadFormat.GPX,
        )
        return gpx_data
```

Add `garminconnect` to `backend/requirements.txt`.

### `backend/app/jobs/sync_jobs.py` — implement Garmin branch

In `poll_user_sources`, replace the "not yet implemented" log with:

```python
elif conn.platform == "garmin":
    garmin_client = _build_garmin_client_from_connection(conn)
    if garmin_client:
        conn_state = await _get_or_create_connection_sync_state(db, conn, user)
        since = conn_state.last_synced_at or datetime.now(UTC) - timedelta(days=90)
        await sync_service.ingest_garmin_activities(
            user=user,
            garmin=garmin_client,
            since=since,
        )
        conn_state.last_synced_at = datetime.now(UTC)
        await db.commit()
```

### `backend/app/services/sync.py` — `ingest_garmin_activities`

Mirror the structure of `ingest_komoot_tours`:

```python
async def ingest_garmin_activities(
    self, user: User, garmin: GarminClient, since: datetime
) -> int:
    """Fetch Garmin activities since `since` and store them in the hub DB."""
    try:
        activities = await garmin.get_activities_since(since)
    except Exception as exc:
        logger.error("Garmin ingest: fetch failed for user %s: %s", user.id, exc)
        return 0

    ingested = 0
    for activity in activities:
        garmin_id = str(activity.get("activityId", ""))
        if not garmin_id:
            continue

        # Dedup by checking existing garmin ID stored in destination_activity_id
        # (no dedicated garmin_activity_id column — reuse the generic pattern)
        existing = await self.db.execute(
            select(SyncedActivity).where(
                SyncedActivity.user_id == user.id,
                SyncedActivity.source == "garmin",
                SyncedActivity.destination_activity_id == garmin_id,
            )
        )
        if existing.scalar_one_or_none():
            continue

        started_at = None
        try:
            started_at = datetime.fromisoformat(
                activity.get("startTimeLocal", "").replace(" ", "T")
            )
        except Exception:
            pass

        self.db.add(SyncedActivity(
            user_id=user.id,
            source="garmin",
            destination_activity_id=garmin_id,
            sync_direction=None,        # set when pushed to a destination
            destination_platform=None,
            sync_status="completed",
            activity_name=activity.get("activityName"),
            sport_type=activity.get("activityType", {}).get("typeKey"),
            distance_m=activity.get("distance"),
            elevation_up_m=activity.get("elevationGain"),
            duration_seconds=int(activity.get("movingDuration") or 0) or None,
            started_at=started_at,
        ))
        ingested += 1

    await self.db.commit()
    logger.info("Garmin ingest: %d new activities for user %s", ingested, user.id)
    return ingested
```

> **Note on Garmin's unofficial API:** `garminconnect` uses Basic Auth against
> Garmin's SSO. Garmin may require MFA or CAPTCHA for some accounts. Always
> wrap the client in try/except and surface connection errors clearly in the UI
> (via `ConnectionSyncState.last_error`). Garmin also has an official Health API
> (OAuth-based) but requires partner approval — the unofficial path is acceptable
> for launch, exactly as with Komoot.

### Frontend — Connections page

Update `frontend/app/(dashboard)/connections/page.tsx`: change Garmin's "coming soon"
state to "Connect" once E6 is deployed. The connection form needs `email` and `password`
fields (same as Komoot). Update `lib/brand-registry.ts` Garmin entry status accordingly.

---

## E7 · Remove Backward-Compatible ARQ Job Aliases

**Priority: LOW — cleanup only, safe to defer**

Two aliases exist in `sync_jobs.py` and `worker.py` for in-flight ARQ jobs queued before
the rename:

```python
# In sync_jobs.py:
poll_komoot_user = poll_user_sources        # alias
komoot_poll_scheduler = source_poll_scheduler  # alias

# In worker.py functions list:
poll_komoot_user,    # backwards-compat
```

These can be removed once two consecutive production deploys have completed — any job
queued under the old name from the previous deploy will have run by then (ARQ job TTL
is 7 days by default; `job_timeout = 600` in `WorkerSettings`).

**When to remove:**
1. Deploy the E6 release (or any release at least 7 days after the alias was introduced)
2. Verify no `poll_komoot_user` jobs are in the Redis queue: `redis-cli LLEN arq:queue`
3. Remove both alias lines from `sync_jobs.py`
4. Remove `poll_komoot_user` from `WorkerSettings.functions` in `worker.py`

---

## Strava → Komoot: Will Not Implement

> **Standing design decision** — not an execution step; no code or migration required.
> Retained here as the authoritative record of why this direction is absent from the
> pipeline dispatch table. Referenced in the Multi-Direction State table below.

Komoot does not expose a public GPX upload endpoint. The unofficial v007 API has no
upload route. `sync_activity_to_komoot` (which *does* implement an upload) uses a
reverse-engineered endpoint that Komoot has not documented and may remove at any time.

**Decision:** Do not implement `strava_to_komoot` as an automatic pipeline direction.
Keep `sync_activity_to_komoot` as a manual one-off action (user explicitly triggers it
from the activity detail view). Do not add `("strava", "komoot")` to the `run_pipeline`
dispatch table.

The `strava_to_komoot` value remains in the `sync_direction` check constraint (added in
A1) so that `sync_activity_to_komoot` can set it correctly on manual uploads. But no
automated pipeline handler will ever be created for this direction.

Document this explicitly in the user-facing docs site (`docs/src/content/docs/sync/`)
so users do not expect it as a pipeline option.

---

## Multi-Direction Sync: Complete State After All E Tasks

| Direction | Via | Status after E tasks |
|---|---|---|
| Komoot → Strava | `poll_user_sources` + `upload_komoot_to_strava` | ✅ Full, watermarked, rule engine |
| Komoot → Intervals.icu | Pipeline `_run_komoot_to_intervals_icu` | ✅ Fixed (A1) |
| Komoot → Runalyze | Pipeline `_run_komoot_to_runalyze` | ✅ Fixed (A1) |
| Strava → Intervals.icu | Pipeline `_run_strava_to_intervals_icu` | ✅ New (E3) |
| Strava → Runalyze | Pipeline `_run_strava_to_runalyze` | ✅ New (E4) |
| Garmin → Strava | `poll_user_sources` ingest + manual sync | ✅ New (E5, E6) |
| Garmin → Intervals.icu | Pipeline (Garmin source) | ✅ After E6 + add dispatch case |
| Garmin → Runalyze | Pipeline (Garmin source) | ✅ After E6 + add dispatch case |
| Import → Strava | `sync_gpx_to_strava` (manual) | ✅ Fixed direction (A1) |
| Import → Komoot | `sync_activity_to_komoot` (manual) | ✅ Fixed direction (A1) |
| Strava → Komoot | — | ❌ Will not implement (Komoot API limitation) |
| Polar / Wahoo → * | `_SOURCE_PLATFORMS` scaffolded | ⏳ Follow E6 pattern when needed |

---

## E Tasks: File Change Summary

| File | Change | Task |
|---|---|---|
| `app/services/sync.py` | Fix `ingest_komoot_tours` direction (NULL); fix `sync_komoot_to_strava` destination fields | E1, E2 |
| `app/jobs/sync_jobs.py` | Add `_run_strava_to_intervals_icu`, `_run_strava_to_runalyze`; extend `run_pipeline` dispatch; add Garmin branch in `poll_user_sources`; add `_build_garmin_client_from_connection` helper | E3, E4, E6 |
| `app/services/garmin.py` | New — `GarminClient` | E6 |
| `app/services/sync.py` | Add `ingest_garmin_activities` | E6 |
| `app/db/models/sync.py` | Add `ConnectionSyncState` model | E5 |
| `alembic/versions/010_connection_sync_state.py` | New migration | E5 |
| `app/jobs/worker.py` | Remove `poll_komoot_user` from `functions` list | E7 |
| `app/jobs/sync_jobs.py` | Remove alias lines | E7 |
| `requirements.txt` | Add `garminconnect` | E6 |
| `frontend/app/(dashboard)/connections/page.tsx` | Enable Garmin connect form | E6 |
| `docs/src/content/docs/sync/` | Document Strava→Komoot as not implementable | — |

---

## Section F · Legacy Komoot Decoupling

These tasks address the residual Komoot→Strava coupling that the original project was built around. They must be completed before RoutePass can honestly be described as a multi-platform hub — several of them (F1, F4, F5) cause runtime crashes or silent data corruption against the **already-migrated** production database.

---

## F1 · Remove Komoot Columns from `User` Model

**Priority: CRITICAL — code references columns dropped by migration 003**

Migration `003_drop_legacy_user_columns.py` already dropped 12 columns from the `users` table. The SQLAlchemy `User` model was never updated. Any code path that touches these attributes will raise `sqlalchemy.exc.ProgrammingError: column "komoot_email_encrypted" does not exist` at runtime.

### Columns to remove from `app/db/models/user.py`

```python
# DELETE these columns — already dropped in migration 003
komoot_email_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
komoot_password_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
komoot_key_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
komoot_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
komoot_connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
komoot_poll_interval_min: Mapped[int] = mapped_column(Integer, default=60)
next_komoot_poll_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
last_komoot_poll_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
sync_komoot_to_strava: Mapped[bool] = mapped_column(Boolean, default=True)
sync_strava_to_komoot: Mapped[bool] = mapped_column(Boolean, default=False)
hide_from_home_default: Mapped[bool] = mapped_column(Boolean, default=False)
timezone: Mapped[str] = mapped_column(String(64), default="UTC")
```

### Files that reference removed columns

After removing the ORM columns, fix all references across the codebase:

| File | References to remove / replace |
|------|-------------------------------|
| `app/jobs/sync_jobs.py` | `user.komoot_email_encrypted`, `user.komoot_password_encrypted`, `user.komoot_key_version`, `user.komoot_poll_interval_min`, `user.next_komoot_poll_at`, `user.last_komoot_poll_at`; remove `_has_legacy_komoot_credentials()`, `_mirror_komoot_credentials()` |
| `app/services/sync.py` | `user.hide_from_home_default` (passed to Komoot upload) |
| `app/api/v1/sync.py` | `user.sync_komoot_to_strava`, `user.sync_strava_to_komoot`, `user.last_komoot_poll_at` |
| `app/api/v1/auth.py` | Any registration defaults that set removed columns |
| `app/api/v1/connections.py` | Any Komoot connect flow that writes removed columns |
| `app/schemas/user.py` | Remove schema fields that mirror removed columns |

### Replacement pattern for credential access

Komoot credentials now live in the `Connection` table (encrypted `credentials` JSONB field), not on `User`. Replace direct `user.komoot_email_encrypted` access with:

```python
from app.db.models.connection import Connection
from app.core.security import decrypt

async def _get_komoot_credentials(user_id: str, db: AsyncSession) -> tuple[str, str] | None:
    result = await db.execute(
        select(Connection).where(
            Connection.user_id == user_id,
            Connection.platform == "komoot",
            Connection.is_active == True,  # noqa: E712
        )
    )
    conn = result.scalar_one_or_none()
    if not conn or not conn.credentials:
        return None
    creds = conn.credentials  # already decrypted by hybrid property
    return creds.get("email"), creds.get("password")
```

### Poll scheduling replacement

`user.next_komoot_poll_at` and `user.last_komoot_poll_at` move to `ConnectionSyncState` (see E5). Until E5 ships, use a Redis TTL to throttle per-connection polls. The `komoot_poll_interval_min` column no longer exists on `User`; use a module-level constant (60 minutes is the safe default that matches the old per-user default value):

```python
# Temporary: use Redis TTL to throttle per-connection polls
# Replace with ConnectionSyncState.last_synced_at when E5 ships.
KOMOOT_POLL_INTERVAL_SECONDS = 60 * 60   # 60 min — hardcoded until E5 per-connection state
lock_key = f"komoot_poll:{connection.id}"
if await redis.exists(lock_key):
    return  # already polled recently
await redis.setex(lock_key, KOMOOT_POLL_INTERVAL_SECONDS, "1")
```

---

## F2 · Generalize `SyncRule.direction` Constraint

**Priority: Deferred — unblocks creating rules for non-Komoot directions**

`SyncRule.direction` has a hard check constraint permitting only `komoot_to_strava`, `strava_to_komoot`, and `both`. This prevents creating pipeline rules for Garmin→Strava, Strava→Intervals.icu, etc.

### Migration 011

```python
# alembic/versions/011_generalize_sync_rule_direction.py
"""generalize sync_rule direction constraint"""
from __future__ import annotations
from alembic import op

revision = "011"
down_revision = "010"


def upgrade() -> None:
    # Drop the old named constraint
    op.drop_constraint("ck_syncrule_direction", "sync_rules", type_="check")
    # Add a new constraint: must match `<platform>_to_<platform>` or be `both`
    op.create_check_constraint(
        "ck_syncrule_direction_format",
        "sync_rules",
        "direction = 'both' OR direction ~ '^[a-z_]+_to_[a-z_]+$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_syncrule_direction_format", "sync_rules", type_="check")
    op.create_check_constraint(
        "ck_syncrule_direction",
        "sync_rules",
        "direction IN ('komoot_to_strava', 'strava_to_komoot', 'both')",
    )
```

### Application-level validation

Replace the removed DB constraint with a Pydantic validator in `app/schemas/sync.py`:

```python
from __future__ import annotations
import re
from pydantic import field_validator

KNOWN_PLATFORMS = {"komoot", "strava", "garmin", "intervals_icu", "runalyze", "polar", "wahoo"}

class SyncRuleCreate(BaseModel):
    direction: str

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        if v == "both":
            return v
        m = re.match(r"^([a-z_]+)_to_([a-z_]+)$", v)
        if not m:
            raise ValueError("direction must be '<platform>_to_<platform>' or 'both'")
        src, dst = m.group(1), m.group(2)
        if src not in KNOWN_PLATFORMS:
            raise ValueError(f"Unknown source platform: {src}")
        if dst not in KNOWN_PLATFORMS:
            raise ValueError(f"Unknown destination platform: {dst}")
        return v
```

---

## F3 · Platform-Agnostic `/sync/status` Endpoint

**Priority: Deferred — can ship alongside E5**

`GET /api/v1/sync/status` currently returns a hardcoded Komoot-Strava payload:

```json
{
  "komoot_connected": true,
  "strava_connected": true,
  "sync_komoot_to_strava": true,
  "sync_strava_to_komoot": false,
  "last_komoot_sync_at": "...",
  "last_strava_sync_at": "..."
}
```

Replace with a connections-driven response that works for any platform:

### New response schema

```python
# app/schemas/sync.py
from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class ConnectionStatus(BaseModel):
    platform: str
    display_name: str
    connected: bool
    last_sync_at: Optional[datetime]
    error: Optional[str]


class SyncStatusResponse(BaseModel):
    connections: list[ConnectionStatus]
    active_pipelines: int
    last_sync_at: Optional[datetime]  # most recent across all connections
```

### New handler

```python
# app/api/v1/sync.py  — replace GET /sync/status
@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SyncStatusResponse:
    conns_result = await db.execute(
        select(Connection).where(Connection.user_id == user.id)
    )
    connections = conns_result.scalars().all()

    pipelines_result = await db.execute(
        select(func.count(Pipeline.id)).where(
            Pipeline.user_id == user.id,
            Pipeline.is_active == True,  # noqa: E712
        )
    )
    active_pipelines = pipelines_result.scalar_one()

    conn_statuses = [
        ConnectionStatus(
            platform=c.platform,
            display_name=c.platform.replace("_", " ").title(),
            connected=c.is_active,
            last_sync_at=c.last_sync_at if hasattr(c, "last_sync_at") else None,
            error=c.last_error if hasattr(c, "last_error") else None,
        )
        for c in connections
    ]

    all_sync_times = [cs.last_sync_at for cs in conn_statuses if cs.last_sync_at]
    last_sync_at = max(all_sync_times) if all_sync_times else None

    return SyncStatusResponse(
        connections=conn_statuses,
        active_pipelines=active_pipelines,
        last_sync_at=last_sync_at,
    )
```

**Frontend note:** `frontend/hooks/use-sync.ts` reads `komoot_connected`, `strava_connected`, etc. Update the hook to consume `connections[]` and derive per-platform state dynamically:

```typescript
// frontend/hooks/use-sync.ts
export function useConnectionStatus(platform: string) {
  const { data } = useSyncStatus()
  return data?.connections.find(c => c.platform === platform) ?? null
}
```

---

## F4 · Deprecate `POST /sync/rebuild-history`

**Priority: Launch-critical — remove dead Komoot migration utility before public launch**

`POST /api/v1/sync/rebuild-history` scans a user's Strava activity history looking for activities whose `external_id` starts with `"komoot_"` and back-fills the corresponding `SyncedActivity` records. This was a one-time data migration tool for users moving from the old standalone app to the SaaS platform.

It must not exist in a platform-agnostic hub. It also references `user.komoot_email_encrypted` and several dropped `User` columns (blocked by F1 anyway).

### Change

```python
# app/api/v1/sync.py — replace the rebuild-history handler
@router.post("/rebuild-history")
async def rebuild_history(
    _user: User = Depends(get_current_user),
) -> dict[str, str]:
    raise HTTPException(
        status_code=410,
        detail=(
            "This endpoint has been removed. The Komoot→Strava history rebuild "
            "was a one-time migration utility and no longer applies to the "
            "multi-platform hub architecture."
        ),
    )
```

Returning HTTP 410 Gone is preferable to 404 — it signals to any clients that the endpoint existed and was intentionally removed, not that it was never there.

---

## F5 · Extend `SyncedActivity.source` Constraint

**Priority: Launch-critical — ingesting from any new platform will fail at DB level**

`SyncedActivity.source` has a check constraint: `source IN ('komoot', 'strava', 'import')`.

Adding a Garmin source (E6), a Polar source, or any other platform requires this constraint to be relaxed first, otherwise `INSERT` will fail with a check constraint violation.

### Migration 012 (or bundle with 011)

```python
# alembic/versions/012_extend_synced_activity_source.py
"""extend synced_activity source constraint"""
from __future__ import annotations
from alembic import op

revision = "012"
down_revision = "011"


def upgrade() -> None:
    op.drop_constraint("ck_syncedactivity_source", "synced_activities", type_="check")
    op.create_check_constraint(
        "ck_syncedactivity_source",
        "synced_activities",
        "source IN ('komoot', 'strava', 'garmin', 'polar', 'wahoo', 'intervals_icu', 'runalyze', 'import')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_syncedactivity_source", "synced_activities", type_="check")
    op.create_check_constraint(
        "ck_syncedactivity_source",
        "synced_activities",
        "source IN ('komoot', 'strava', 'import')",
    )
```

**Alternative:** replace the exhaustive enum constraint with a regex `source ~ '^[a-z_]+$'` so any new platform can be added without a migration. Use application-level validation (same `KNOWN_PLATFORMS` set from F2) to enforce the allowed values. This is the recommended approach if new sources are expected frequently.

---

## F6 · Platform-Agnostic Rule Engine

**Priority: Deferred — needed before Garmin sync rules ship**

The rule engine in `app/services/sync.py` (`_match_condition`, `_apply_action`) operates directly on Komoot `Tour` objects. It accesses properties like `tour.sport_type`, `tour.distance`, `tour.elevation_gain`, `tour.name` — all Komoot-specific attribute names.

To apply rules to Garmin activities, Strava activities, or any future platform, introduce a normalised `ActivityRecord` dataclass that every platform ingestor maps its native objects into before applying rules.

### Normalised activity record

```python
# app/services/activity_record.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ActivityRecord:
    """Platform-agnostic representation of a single activity.

    Every source ingestor must produce one of these before rules are evaluated.
    Field names mirror the `SyncedActivity` ORM model wherever possible.
    """
    platform: str                   # "komoot" | "strava" | "garmin" | …
    external_id: str                # platform-native ID
    name: str
    sport_type: str                 # normalised per shared/sport-mappings.json
    started_at: datetime
    distance_m: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    duration_s: Optional[float] = None
    gpx_data: Optional[bytes] = None
    extra: dict = field(default_factory=dict)  # platform-specific overflow
```

### Rule engine refactor

```python
# app/services/sync.py — replace Tour-specific helpers

def _match_condition(record: ActivityRecord, rule: SyncRule) -> bool:
    """Return True if `record` satisfies `rule.condition`."""
    if not rule.condition:
        return True
    cond = rule.condition  # dict, e.g. {"field": "sport_type", "op": "eq", "value": "Ride"}
    field_val = getattr(record, cond["field"], record.extra.get(cond["field"]))
    op = cond.get("op", "eq")
    expected = cond["value"]
    if op == "eq":      return field_val == expected
    if op == "neq":     return field_val != expected
    if op == "gt":      return field_val is not None and field_val > expected
    if op == "lt":      return field_val is not None and field_val < expected
    if op == "contains": return expected in (field_val or "")
    return False


def _apply_action(record: ActivityRecord, rule: SyncRule) -> ActivityRecord:
    """Apply `rule.action` to a copy of `record` and return the modified copy."""
    if not rule.action:
        return record
    import copy
    rec = copy.replace(record)  # Python 3.13+ / use dataclasses.replace for 3.9+
    action = rule.action  # dict, e.g. {"set": {"name": "Morning Run"}}
    for field_name, value in action.get("set", {}).items():
        if hasattr(rec, field_name):
            object.__setattr__(rec, field_name, value)
        else:
            rec.extra[field_name] = value
    return rec
```

### Ingestor mapping examples

Each source ingestor converts its native model to `ActivityRecord` before calling the rule engine:

```python
# Komoot
def _komoot_tour_to_record(tour: KomootTour) -> ActivityRecord:
    return ActivityRecord(
        platform="komoot",
        external_id=str(tour.id),
        name=tour.name,
        sport_type=tour.sport,
        started_at=tour.date,
        distance_m=tour.distance,
        elevation_gain_m=tour.elevation_up,
        duration_s=tour.duration,
    )

# Garmin (E6)
def _garmin_activity_to_record(act: dict) -> ActivityRecord:
    return ActivityRecord(
        platform="garmin",
        external_id=str(act["activityId"]),
        name=act.get("activityName", ""),
        sport_type=act.get("activityType", {}).get("typeKey", "generic"),
        started_at=datetime.fromisoformat(act["startTimeLocal"]),
        distance_m=act.get("distance"),
        elevation_gain_m=act.get("elevationGain"),
        duration_s=act.get("duration"),
    )
```

---

## F Tasks: File Change Summary

| File | Change | Task |
|---|---|---|
| `app/db/models/user.py` | Remove 12 legacy Komoot columns | F1 |
| `app/jobs/sync_jobs.py` | Remove `_has_legacy_komoot_credentials`, `_mirror_komoot_credentials`; replace `user.komoot_*` access with Connection lookups | F1 |
| `app/services/sync.py` | Remove `user.hide_from_home_default`; replace `Tour`-specific rule engine with `ActivityRecord`-based helpers | F1, F6 |
| `app/api/v1/sync.py` | Remove `user.sync_komoot_to_strava` references; replace `/sync/status` handler; replace `/sync/rebuild-history` with 410 | F1, F3, F4 |
| `app/schemas/user.py` | Remove schema fields for dropped columns | F1 |
| `app/schemas/sync.py` | Add `ConnectionStatus`, `SyncStatusResponse`; add `SyncRuleCreate.validate_direction` | F2, F3 |
| `app/services/activity_record.py` | New — `ActivityRecord` dataclass | F6 |
| `alembic/versions/011_generalize_sync_rule_direction.py` | New migration | F2 |
| `alembic/versions/012_extend_synced_activity_source.py` | New migration | F5 |
| `frontend/hooks/use-sync.ts` | Replace hardcoded `komoot_connected` / `strava_connected` reads with `useConnectionStatus(platform)` helper | F3 |

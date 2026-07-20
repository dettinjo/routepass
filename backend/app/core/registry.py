"""Default provider policies + idempotent seeding of the API-management registry.

Single source of truth for the seed data (used by the app lifespan on startup and by
tests). The migration only creates the schema. See RATE_LIMIT_ARCHITECTURE.md.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.governance import GovernorConfig, ProviderPolicy

# Seed values reflect today's hardcoded limits (rate_limit.py, polling.py) plus the
# researched provider limits/costs. Admin edits take precedence after first seed —
# ensure_registry_seeded() never overwrites an existing row.
DEFAULT_PROVIDER_POLICIES: list[dict] = [
    dict(
        platform="komoot",
        role="source",
        auth_type="credentials",
        default_poll_min=120,
        min_poll_min=30,
        refresh_strategy="poll",
        initial_backfill_limit=50,
        page_size=50,
        tier_label="Unofficial (no published tier)",
        notes=(
            "No public API — uses the unofficial web API (v006/v007, Basic Auth). "
            "No documented rate limits, no webhooks, and it can break without "
            "notice. Poll conservatively and back off on errors; there is no paid "
            "tier to upgrade to."
        ),
    ),
    dict(
        platform="garmin",
        role="source",
        auth_type="credentials",
        default_poll_min=60,
        min_poll_min=30,
        refresh_strategy="poll",
        initial_backfill_limit=50,
        page_size=50,
        tier_label="Unofficial (no published tier)",
        notes=(
            "Uses the unofficial garminconnect SDK — subject to login rate-limits, "
            "account lockouts and MFA challenges under heavy use. The official "
            "Garmin Connect Developer Program requires a business entity and a "
            "one-time $5,000 fee for Health API production access; not used here."
        ),
    ),
    dict(
        platform="polar",
        role="source",
        auth_type="credentials",
        default_poll_min=60,
        min_poll_min=30,
        refresh_strategy="poll",
        tier_label="Not yet implemented",
        notes="Placeholder policy — Polar Flow is not yet wired up as a source.",
    ),
    dict(
        platform="wahoo",
        role="source",
        auth_type="credentials",
        default_poll_min=60,
        min_poll_min=30,
        refresh_strategy="poll",
        tier_label="Not yet implemented",
        notes="Placeholder policy — Wahoo is not yet wired up as a source.",
    ),
    dict(
        platform="strava",
        role="both",
        auth_type="oauth_pool",
        supports_webhooks=True,
        refresh_strategy="webhook",
        read_limit_15min=200,
        read_limit_daily=2000,
        overall_limit_15min=400,
        overall_limit_daily=4000,
        athlete_capacity=10,
        monthly_cost_cents=1199,
        initial_backfill_limit=30,
        page_size=30,
        tier_label="Standard, self-upgraded (10 athletes)",
        notes=(
            "Requires an active Strava subscription ($11.99/mo per developer, "
            "since June 2026). Read/overall limits and athlete cap here are "
            "per-app defaults for new apps — each strava_apps row self-corrects "
            "from Strava's response headers once it starts making real calls. "
            "Beyond 10 athletes: submit for review (up to 9,999) or Extended "
            "Access (10,000+, no subscription needed, for large/official "
            "integrations)."
        ),
    ),
    dict(
        platform="intervals_icu",
        role="destination",
        auth_type="api_key",
        refresh_strategy="none",
        window_seconds=1,
        window_limit=10,
        tier_label="Free / fair-use",
        notes=(
            "Official API, free. Documented limits: per-day (resets midnight "
            "UTC) + per-15min window, plus a hard 10 req/s per-IP edge limit. "
            "Per-app and per-athlete limits are being added by intervals.icu."
        ),
    ),
    dict(
        platform="runalyze",
        role="destination",
        auth_type="api_key",
        refresh_strategy="none",
        window_seconds=60,
        window_limit=30,
        tier_label="Free / fair-use",
        notes=(
            "Official Personal API, free. No hard rate limit currently enforced "
            "by Runalyze — governed by a fair-use policy; they may add a limit "
            "in the future. window_limit here is our own conservative pacing."
        ),
    ),
]


async def ensure_registry_seeded(db: AsyncSession) -> None:
    """Insert any missing provider policies and the singleton governor config.

    Idempotent: existing rows are never overwritten, so admin edits are preserved.
    """
    existing = set((await db.execute(select(ProviderPolicy.platform))).scalars().all())
    added = False
    for spec in DEFAULT_PROVIDER_POLICIES:
        if spec["platform"] not in existing:
            db.add(ProviderPolicy(**spec))
            added = True

    has_governor = (
        await db.execute(select(func.count()).select_from(GovernorConfig))
    ).scalar() or 0
    if not has_governor:
        db.add(GovernorConfig(id=1))
        added = True

    if added:
        await db.commit()

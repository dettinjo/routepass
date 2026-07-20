"""Default provider policies + idempotent seeding of the API-management registry.

Single source of truth for the seed data (used by the app lifespan on startup and by
tests). The migration only creates the schema. See RATE_LIMIT_ARCHITECTURE.md.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.governance import GovernorConfig, ProviderPolicy

# Seed values reflect today's hardcoded limits (rate_limit.py, polling.py) plus the
# researched provider limits/costs. Admin edits take precedence after first seed.
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
    ),
    dict(
        platform="polar",
        role="source",
        auth_type="credentials",
        default_poll_min=60,
        min_poll_min=30,
        refresh_strategy="poll",
    ),
    dict(
        platform="wahoo",
        role="source",
        auth_type="credentials",
        default_poll_min=60,
        min_poll_min=30,
        refresh_strategy="poll",
    ),
    dict(
        platform="strava",
        role="both",
        auth_type="oauth_pool",
        supports_webhooks=True,
        refresh_strategy="webhook",
        read_limit_15min=200,
        read_limit_daily=2000,
        overall_limit_15min=100,
        overall_limit_daily=1000,
        athlete_capacity=10,
        monthly_cost_cents=1199,
        initial_backfill_limit=30,
        page_size=30,
    ),
    dict(
        platform="intervals_icu",
        role="destination",
        auth_type="api_key",
        refresh_strategy="none",
        window_seconds=1,
        window_limit=10,
    ),
    dict(
        platform="runalyze",
        role="destination",
        auth_type="api_key",
        refresh_strategy="none",
        window_seconds=60,
        window_limit=30,
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

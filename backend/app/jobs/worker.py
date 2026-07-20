from __future__ import annotations

import logging

from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.jobs.sync_jobs import (
    poll_user_sources,
    process_strava_activity,
    run_pipeline,
    source_poll_scheduler,
    sync_activity_to_komoot,
    sync_gpx_to_strava,
)

logger = logging.getLogger(__name__)


async def recompute_governor_state(ctx: dict) -> None:
    """Cron: refresh the cached economic-governor state (cost/revenue/capacity)."""
    from app.core.governor import refresh_state

    async with AsyncSessionLocal() as db:
        state = await refresh_state(db)
        logger.info(
            "Governor recompute: economic_level=%d free_tier_level=%d "
            "cost=%d revenue=%d strava_admission_open=%s",
            state.economic_level,
            state.free_tier_level,
            state.monthly_cost_cents,
            state.monthly_revenue_cents,
            state.strava_admission_open,
        )


async def startup(ctx: dict) -> None:
    """Initialize resources for the worker."""
    logger.info("ARQ Worker starting up. Connecting to DB and Redis...")
    ctx["engine"] = engine


async def shutdown(ctx: dict) -> None:
    """Clean up resources on worker shutdown."""
    logger.info("ARQ Worker shutting down. Cleaning up...")
    await ctx["engine"].dispose()


class WorkerSettings:
    """ARQ Worker configuration."""

    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

    on_startup = startup
    on_shutdown = shutdown

    functions = [
        poll_user_sources,
        process_strava_activity,
        run_pipeline,
        sync_gpx_to_strava,
        sync_activity_to_komoot,
    ]

    cron_jobs = [
        cron(
            source_poll_scheduler,
            hour=None,
            minute=set(range(0, 60, 5)),  # every 5 minutes
            run_at_startup=True,
        ),
        cron(
            recompute_governor_state,
            hour=None,
            minute=set(range(0, 60, 10)),  # every 10 minutes
            run_at_startup=True,
        ),
    ]

    max_jobs = settings.ARQ_MAX_JOBS
    job_timeout = 600

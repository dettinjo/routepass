from __future__ import annotations

import logging

from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import settings
from app.db.session import engine
from app.jobs.sync_jobs import (
    poll_komoot_user,
    poll_user_sources,
    process_strava_activity,
    run_pipeline,
    source_poll_scheduler,
    sync_activity_to_komoot,
    sync_gpx_to_strava,
)

logger = logging.getLogger(__name__)


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
        poll_komoot_user,  # backwards-compat alias for in-flight ARQ jobs
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
        )
    ]

    max_jobs = settings.ARQ_MAX_JOBS
    job_timeout = 600

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core import security
from app.core.rate_limit import rate_limit_guard
from app.db.models.connection import Connection
from app.db.models.pipeline import Pipeline
from app.db.models.subscription import Subscription
from app.db.models.sync import JobAuditLog, SyncedActivity
from app.db.models.user import StravaApp, StravaToken, User
from app.db.session import AsyncSessionLocal
from app.services.intervals_icu import IntervalsIcuClient
from app.services.komoot import KomootClient, to_komoot_sport, to_strava_sport
from app.services.runalyze import RunalyzeClient
from app.services.strava import StravaClient
from app.services.sync import SyncService

UTC = UTC

logger = logging.getLogger(__name__)

_MIN_POLL_INTERVAL: dict = {"free": 120, "pro": 10, "lifetime": 10, "business": 10}

# Platforms that RoutePass pulls activities *from*.
# Destination platforms (strava, intervals_icu, runalyze, trainingpeaks, webhook)
# are never polled — they receive pushes only.
_SOURCE_PLATFORMS: frozenset = frozenset({"komoot", "garmin", "polar", "wahoo"})


async def _get_valid_strava_access_token(user: User) -> str:
    """Return a usable Strava access token, refreshing it when near expiry."""
    if not user.strava_token:
        raise ValueError("User has no Strava token")

    access_token = security.decrypt_maybe_plaintext(user.strava_token.access_token)
    refresh_due_at = user.strava_token.expires_at - timedelta(minutes=5)
    if refresh_due_at > datetime.now(UTC):
        return access_token

    refresh_token = security.decrypt_maybe_plaintext(user.strava_token.refresh_token)
    refreshed = await StravaClient.refresh_access_token(refresh_token)

    user.strava_token.access_token = security.encrypt(refreshed["access_token"])
    user.strava_token.refresh_token = security.encrypt(refreshed["refresh_token"])
    user.strava_token.expires_at = datetime.fromtimestamp(refreshed["expires_at"], tz=UTC)
    user.strava_token.last_refreshed_at = datetime.now(UTC)

    logger.info("Refreshed Strava access token for user %s", user.id)
    return refreshed["access_token"]


async def poll_user_sources(ctx: dict, user_id: str) -> None:
    """Fetch new activities from every connected source platform for one user.

    Iterates all active source connections (Komoot, and future platforms like
    Garmin, Polar, Wahoo) and ingests any new activities into the hub DB.
    After ingestion, pushes un-synced activities to Strava if connected.
    """
    job_id = ctx.get("job_id", "unknown")
    logger.info("Executing poll_user_sources job %s for user %s", job_id, user_id)

    async with AsyncSessionLocal() as db:
        audit = JobAuditLog(
            job_id=job_id,
            job_type="poll_user_sources",
            user_id=user_id,
            status="running",
            priority=5,
            enqueued_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
        )
        db.add(audit)
        await db.commit()

        error_message: str | None = None
        try:
            stmt = (
                select(User)
                .where(User.id == user_id)
                .options(selectinload(User.strava_token), selectinload(User.subscription))
            )
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                logger.warning("poll_user_sources: User %s not found.", user_id)
                return

            if str(user.id) != user_id:
                logger.error(
                    "SECURITY: user_id mismatch in poll_user_sources — "
                    "expected %s, got %s. Aborting.",
                    user_id,
                    user.id,
                )
                return

            # Load all active source connections for this user
            conn_res = await db.execute(
                select(Connection).where(
                    Connection.user_id == user_id,
                    Connection.platform.in_(list(_SOURCE_PLATFORMS)),
                    Connection.status != "disconnected",
                )
            )
            source_connections = conn_res.scalars().all()

            sync_service = SyncService(db)
            komoot_ingested = False

            for conn in source_connections:
                if conn.platform == "komoot":
                    komoot_client = _build_komoot_client_from_connection(conn)
                    if komoot_client:
                        await sync_service.ingest_komoot_tours(user=user, komoot=komoot_client)
                        komoot_ingested = True
                        await db.commit()
                else:
                    logger.info(
                        "poll_user_sources: platform '%s' not yet implemented — skipping",
                        conn.platform,
                    )

            if not komoot_ingested and not source_connections:
                logger.info(
                    "poll_user_sources: User %s has no active source connections — nothing to do",
                    user_id,
                )

            # ── Strava sync (requires Strava token) ───────────────────────────
            if user.strava_token:
                stmt_app = select(StravaApp).where(StravaApp.id == user.strava_token.strava_app_id)
                result_app = await db.execute(stmt_app)
                strava_app = result_app.scalar_one_or_none()

                if strava_app:
                    try:
                        access_token = await _get_valid_strava_access_token(user)
                        strava_client = StravaClient(access_token=access_token)

                        # Phase A: Pull Strava-native activities into the hub.
                        # Watermark-based incremental sync — first run looks back
                        # 90 days, subsequent runs only fetch since last sync.
                        await sync_service.ingest_strava_activities(
                            user=user,
                            strava=strava_client,
                            strava_app=strava_app,
                        )
                    except Exception as exc:
                        logger.error(
                            "poll_user_sources: Strava ingest phase failed for user %s: %s",
                            user_id,
                            exc,
                        )

                    # Phase B: Push hub-stored Komoot activities to Strava.
                    # Requires a Komoot client to download GPX on demand.
                    komoot_for_gpx: KomootClient | None = None
                    for conn in source_connections:
                        if conn.platform == "komoot":
                            komoot_for_gpx = _build_komoot_client_from_connection(conn)
                            break

                    if komoot_for_gpx and strava_app:
                        try:
                            access_token = await _get_valid_strava_access_token(user)
                            strava_client = StravaClient(access_token=access_token)
                            await sync_service.upload_komoot_to_strava(
                                user=user,
                                strava_app=strava_app,
                                komoot=komoot_for_gpx,
                                strava=strava_client,
                            )
                        except Exception as exc:
                            logger.error(
                                "poll_user_sources: Strava upload phase failed for user %s: %s",
                                user_id,
                                exc,
                            )
            else:
                logger.info(
                    "poll_user_sources: User %s has no Strava token — skipping Strava phases",
                    user_id,
                )

            await db.commit()

        except Exception as exc:
            error_message = str(exc)
            logger.error("poll_user_sources failed for user %s: %s", user_id, exc)
        finally:
            audit.status = "failed" if error_message else "completed"
            audit.completed_at = datetime.now(UTC)
            audit.error_message = error_message
            await db.commit()


# Backwards-compat alias — any ARQ jobs still queued under the old name will resolve correctly.
poll_komoot_user = poll_user_sources


# ── Source-platform helpers ───────────────────────────────────────────────────


def _build_komoot_client_from_connection(conn: Connection) -> KomootClient | None:
    """Return a KomootClient from a Connection record's encrypted credentials."""
    if not conn.credentials_enc:
        return None
    try:
        creds = json.loads(security.decrypt(conn.credentials_enc))
        email = creds.get("email")
        password = creds.get("password")
        uid = creds.get("user_id")
        if email and password and uid:
            return KomootClient(email=email, password=password, user_id=uid)
    except Exception as exc:
        logger.warning("Failed to decrypt Komoot connection %s: %s", conn.id, exc)
    return None


async def process_strava_activity(ctx: dict, athlete_id: str, activity_id: str) -> None:
    """Handles a Strava webhook event by recording the inbound activity.

    Full Strava → Komoot reverse sync is architecturally blocked because Komoot
    does not expose a public GPX-upload API endpoint. The groundwork below is
    complete and ready: it fetches the Strava activity metadata, records it in
    the database as a 'strava_to_komoot' entry, and logs the limitation.

    When a Komoot upload endpoint becomes available (via reverse-engineered mobile
    API or official partner access), replace the TODO block with the Komoot upload call.
    """
    logger.info("process_strava_activity: athlete=%s activity=%s", athlete_id, activity_id)

    async with AsyncSessionLocal() as db:
        # Resolve the local user from Strava's athlete id.
        stmt = (
            select(User)
            .join(StravaToken, StravaToken.user_id == User.id)
            .where(StravaToken.strava_athlete_id == int(athlete_id))
            .options(
                selectinload(User.strava_token),
                selectinload(User.subscription),
            )
        )
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            logger.warning(
                "process_strava_activity: No user found for Strava athlete %s.",
                athlete_id,
            )
            return

        if not user.strava_token:
            logger.warning("process_strava_activity: User %s has no Strava token.", user.id)
            return

        # Avoid duplicate processing — check across all directions
        existing = await db.execute(
            select(SyncedActivity).where(
                SyncedActivity.user_id == user.id,
                SyncedActivity.strava_activity_id == activity_id,
            )
        )
        if existing.scalar_one_or_none():
            logger.info(
                "process_strava_activity: activity %s already recorded for user %s — skipping.",
                activity_id,
                user.id,
            )
            return

        # Fetch activity metadata from Strava
        access_token = await _get_valid_strava_access_token(user)
        strava_client = StravaClient(access_token=access_token)
        stmt_app = select(StravaApp).where(StravaApp.id == user.strava_token.strava_app_id)
        result_app = await db.execute(stmt_app)
        strava_app = result_app.scalar_one_or_none()

        if not strava_app:
            logger.error("process_strava_activity: StravaApp not found for user %s", user.id)
            return

        tier_str = user.subscription.tier if user.subscription else "free"
        try:
            activity_data = await rate_limit_guard.call(
                strava_app.id,
                tier_str,
                strava_client.get_activity,
                activity_id=activity_id,
            )
        except Exception as exc:
            logger.error(
                "process_strava_activity: Failed to fetch Strava activity %s: %s",
                activity_id,
                exc,
            )
            return

        # Ingest into hub as a completed Strava-sourced activity.
        # Reverse sync to Komoot is not yet possible (no public upload API).
        started_at = None
        try:
            started_at = datetime.fromisoformat(
                activity_data.get("start_date", "").replace("Z", "+00:00")
            )
        except Exception:
            pass

        sport = activity_data.get("sport_type") or activity_data.get("type")

        record = SyncedActivity(
            user_id=user.id,
            source="strava",
            strava_activity_id=activity_id,
            sync_direction=None,
            sync_status="completed",
            activity_name=activity_data.get("name"),
            sport_type=sport,
            distance_m=activity_data.get("distance"),
            elevation_up_m=activity_data.get("total_elevation_gain"),
            started_at=started_at,
            duration_seconds=activity_data.get("moving_time"),
        )
        db.add(record)
        await db.commit()

        logger.info(
            "process_strava_activity: Recorded activity %s for user %s as pending reverse sync.",
            activity_id,
            user.id,
        )


async def source_poll_scheduler(ctx: dict) -> None:
    """Cron: finds users with active source connections due for a poll and enqueues jobs."""
    logger.info("Running source_poll_scheduler cron job")

    redis = ctx.get("redis")
    if not redis:
        logger.error("Redis not available in Worker ctx.")
        return

    # Distributed lock — only one worker replica runs the scheduler per tick.
    # TTL of 290 s (just under the 5-min cron interval) prevents a stale lock
    # from blocking the next tick if the scheduler worker crashes mid-run.
    lock_acquired = await redis.set("routepass:scheduler_lock", 1, nx=True, ex=290)
    if not lock_acquired:
        logger.debug("source_poll_scheduler: lock held by another worker — skipping")
        return

    async with AsyncSessionLocal() as db:
        # Fetch active StravaApp id for Strava budget check
        app_result = await db.execute(
            select(StravaApp.id).where(StravaApp.is_active == True).limit(1)  # noqa: E712
        )
        strava_app_id = app_result.scalar_one_or_none()

        daily_count = await rate_limit_guard.daily_count(strava_app_id) if strava_app_id else 0
        budget_exhausted_for_free = daily_count > 800
        if budget_exhausted_for_free:
            logger.warning(
                "Daily Strava budget at %d — free-tier polling suspended this cycle.", daily_count
            )

        # Eligible users: active users that have at least one active source Connection.
        # Poll throttling is handled via Redis TTL per connection (until E5 per-connection
        # watermarks are implemented).
        has_source_conn = (
            select(Connection.id)
            .where(
                Connection.user_id == User.id,
                Connection.platform.in_(list(_SOURCE_PLATFORMS)),
                Connection.status != "disconnected",
            )
            .exists()
        )

        stmt = (
            select(User.id, Subscription.tier)
            .outerjoin(Subscription, Subscription.user_id == User.id)
            .where(
                User.is_active == True,  # noqa: E712
                has_source_conn,
            )
        )
        result = await db.execute(stmt)
        rows = result.all()

        enqueued = 0
        skipped_budget = 0
        for uid, tier in rows:
            tier = tier or "free"
            if budget_exhausted_for_free and tier == "free":
                skipped_budget += 1
                continue
            await redis.enqueue_job(
                "poll_user_sources",
                str(uid),
                _job_id=f"poll_user_{uid}",  # ARQ dedup: same ID = no double-enqueue
            )
            enqueued += 1

        logger.info(
            "Scheduler: enqueued=%d, skipped_free_budget=%d (daily=%d)",
            enqueued,
            skipped_budget,
            daily_count,
        )


# Backwards-compat alias — the cron entry in worker.py still references this name.
komoot_poll_scheduler = source_poll_scheduler


async def run_pipeline(ctx: dict, pipeline_id: str, user_id: str) -> None:
    """Execute a single pipeline: fetch from source, push to destination."""
    job_id = ctx.get("job_id", "unknown")
    logger.info("run_pipeline job=%s pipeline=%s user=%s", job_id, pipeline_id, user_id)

    async with AsyncSessionLocal() as db:
        audit = JobAuditLog(
            job_id=job_id,
            job_type="run_pipeline",
            user_id=user_id,
            status="running",
            priority=5,
            enqueued_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
        )
        db.add(audit)
        await db.commit()

        error_message: str | None = None
        try:
            # Load pipeline with connections
            pipeline_result = await db.execute(
                select(Pipeline).where(
                    Pipeline.id == pipeline_id,
                    Pipeline.user_id == user_id,
                )
            )
            pipeline = pipeline_result.scalar_one_or_none()
            if not pipeline:
                logger.warning(
                    "run_pipeline: Pipeline %s not found for user %s", pipeline_id, user_id
                )
                return
            if not pipeline.enabled:
                logger.info("run_pipeline: Pipeline %s is disabled — skipping", pipeline_id)
                return

            source_result = await db.execute(
                select(Connection).where(Connection.id == pipeline.source_connection_id)
            )
            source = source_result.scalar_one_or_none()

            dest_result = await db.execute(
                select(Connection).where(Connection.id == pipeline.dest_connection_id)
            )
            dest = dest_result.scalar_one_or_none()

            if not source or not dest:
                logger.error("run_pipeline: Missing connection(s) for pipeline %s", pipeline_id)
                return

            if str(source.user_id) != user_id or str(dest.user_id) != user_id:
                logger.error(
                    "SECURITY: pipeline %s connections belong to different user — aborting.",
                    pipeline_id,
                )
                return

            # Load user with subscription and strava token
            user_result = await db.execute(
                select(User)
                .where(User.id == user_id)
                .options(selectinload(User.strava_token), selectinload(User.subscription))
            )
            user = user_result.scalar_one_or_none()
            if not user:
                logger.warning("run_pipeline: User %s not found", user_id)
                return

            pair = (source.platform, dest.platform)

            if pair == ("komoot", "strava"):
                await _run_komoot_to_strava(db, pipeline, user, source, dest)
            elif pair == ("komoot", "intervals_icu"):
                await _run_komoot_to_intervals_icu(db, pipeline, user, source, dest)
            elif pair == ("komoot", "runalyze"):
                await _run_komoot_to_runalyze(db, pipeline, user, source, dest)
            else:
                logger.warning(
                    "run_pipeline: Unsupported platform pair %s→%s for pipeline %s",
                    source.platform,
                    dest.platform,
                    pipeline_id,
                )

        except Exception as exc:
            error_message = str(exc)
            logger.error("run_pipeline failed for pipeline %s: %s", pipeline_id, exc)
        finally:
            audit.status = "failed" if error_message else "completed"
            audit.completed_at = datetime.now(UTC)
            audit.error_message = error_message
            await db.commit()


async def _run_komoot_to_strava(
    db: object,
    pipeline: Pipeline,
    user: User,
    source: Connection,
    dest: Connection,
) -> None:
    """Handle a Komoot→Strava pipeline execution."""
    # Decrypt Komoot credentials from source connection
    if not source.credentials_enc:
        logger.error("_run_komoot_to_strava: No credentials for source connection %s", source.id)
        return

    creds = json.loads(security.decrypt(source.credentials_enc))
    komoot_client = KomootClient(
        email=creds["email"],
        password=creds["password"],
        user_id=creds["user_id"],
    )

    # Strava token — prefer Connection credentials, fall back to legacy StravaToken
    strava_access_token: str | None = None
    strava_app: StravaApp | None = None

    if dest.credentials_enc:
        dest_creds = json.loads(security.decrypt(dest.credentials_enc))
        strava_access_token = dest_creds.get("access_token")
        app_id = dest.meta.get("app_id") if dest.meta else None
        if app_id:
            from sqlalchemy import select as _select

            app_res = await db.execute(_select(StravaApp).where(StravaApp.id == app_id))
            strava_app = app_res.scalar_one_or_none()
    elif user.strava_token:
        strava_access_token = await _get_valid_strava_access_token(user)
        from sqlalchemy import select as _select

        app_res = await db.execute(
            _select(StravaApp).where(StravaApp.id == user.strava_token.strava_app_id)
        )
        strava_app = app_res.scalar_one_or_none()

    if not strava_access_token or not strava_app:
        logger.error("_run_komoot_to_strava: No Strava credentials for dest connection %s", dest.id)
        return

    strava_client = StravaClient(access_token=strava_access_token)
    sync_service = SyncService(db)
    synced = await sync_service.sync_komoot_to_strava(
        user=user,
        strava_app=strava_app,
        komoot=komoot_client,
        strava=strava_client,
    )
    logger.info("_run_komoot_to_strava: pipeline %s → %d tours synced", pipeline.id, synced)


# ── Komoot → Intervals.icu ─────────────────────────────────────────────────────


async def _run_komoot_to_intervals_icu(
    db: object,
    pipeline: Pipeline,
    user: User,
    source: Connection,
    dest: Connection,
) -> None:
    """Handle a Komoot→Intervals.icu pipeline execution.

    Fetches new Komoot tours since the user's last sync watermark, downloads GPX,
    and uploads each to Intervals.icu via the REST API.

    NOTE: SyncedActivity insertion for multi-destination pipelines requires a DB
    migration to relax the (user_id, komoot_tour_id) unique constraint.  Until
    that migration lands, deduplication is handled by querying SyncedActivity
    filtered on pipeline_id instead of the global unique constraint.
    """
    if not source.credentials_enc:
        logger.error(
            "_run_komoot_to_intervals_icu: No credentials for source connection %s", source.id
        )
        return
    if not dest.credentials_enc:
        logger.error("_run_komoot_to_intervals_icu: No credentials for dest connection %s", dest.id)
        return

    src_creds = json.loads(security.decrypt(source.credentials_enc))
    komoot_client = KomootClient(
        email=src_creds["email"],
        password=src_creds["password"],
        user_id=src_creds["user_id"],
    )

    dst_creds = json.loads(security.decrypt(dest.credentials_enc))
    intervals_client = IntervalsIcuClient(
        api_key=dst_creds["api_key"],
        athlete_id=dst_creds["athlete_id"],
    )

    # Determine watermark: use the user's global komoot sync state
    from sqlalchemy import select as _select

    from app.db.models.sync import UserSyncState

    state_res = await db.execute(_select(UserSyncState).where(UserSyncState.user_id == user.id))
    state = state_res.scalar_one_or_none()

    from datetime import timedelta

    since = (
        state.last_komoot_sync_at
        if state and state.last_komoot_sync_at
        else datetime.now(UTC) - timedelta(days=30)
    )

    try:
        tours = await komoot_client.get_tours(since=since)
    except Exception as exc:
        logger.error("_run_komoot_to_intervals_icu: Failed to fetch tours: %s", exc)
        return

    synced_count = 0
    for tour in tours:
        try:
            from app.db.models.sync import SyncedActivity as _SA

            already = await db.execute(
                _select(_SA).where(
                    _SA.user_id == user.id,
                    _SA.komoot_tour_id == tour.id,
                    _SA.destination_platform == "intervals_icu",
                    _SA.sync_status == "completed",
                )
            )
            if already.scalar_one_or_none():
                logger.debug("Tour %s already synced to intervals_icu — skipping", tour.id)
                continue

            gpx_bytes = await komoot_client.download_gpx(tour.id)
            activity_id = await intervals_client.upload_gpx(
                gpx_bytes=gpx_bytes,
                name=tour.name,
                sport_type=tour.strava_sport,  # Strava type names are accepted by Intervals.icu
                description=tour.description,
                external_id=f"komoot_{tour.id}",
            )

            record = _SA(
                user_id=user.id,
                pipeline_id=pipeline.id,
                komoot_tour_id=tour.id,
                destination_platform="intervals_icu",
                destination_activity_id=activity_id,
                sync_direction="komoot_to_intervals_icu",
                sync_status="completed",
                activity_name=tour.name,
                sport_type=tour.sport,
                distance_m=tour.distance_m,
                elevation_up_m=tour.elevation_up_m,
                started_at=tour.date,
            )
            db.add(record)
            await db.commit()
            synced_count += 1

        except Exception as exc:
            logger.error("_run_komoot_to_intervals_icu: Failed for tour %s: %s", tour.id, exc)

    logger.info(
        "_run_komoot_to_intervals_icu: pipeline %s → %d tours synced", pipeline.id, synced_count
    )


# ── Komoot → Runalyze ──────────────────────────────────────────────────────────


async def _run_komoot_to_runalyze(
    db: object,
    pipeline: Pipeline,
    user: User,
    source: Connection,
    dest: Connection,
) -> None:
    """Handle a Komoot→Runalyze pipeline execution.

    Fetches new Komoot tours, downloads GPX, and pushes each to Runalyze via
    the personal-access-token upload API.  Rate limit: 30 req/min (Runalyze
    documented limit); this implementation does not enforce it — callers should
    not invoke this handler more than once every two minutes for large backlogs.

    NOTE: Same schema note as _run_komoot_to_intervals_icu — multi-destination
    deduplication via pipeline_id until a future migration lands.
    """
    if not source.credentials_enc:
        logger.error("_run_komoot_to_runalyze: No credentials for source connection %s", source.id)
        return
    if not dest.credentials_enc:
        logger.error("_run_komoot_to_runalyze: No credentials for dest connection %s", dest.id)
        return

    src_creds = json.loads(security.decrypt(source.credentials_enc))
    komoot_client = KomootClient(
        email=src_creds["email"],
        password=src_creds["password"],
        user_id=src_creds["user_id"],
    )

    dst_creds = json.loads(security.decrypt(dest.credentials_enc))
    runalyze_client = RunalyzeClient(access_token=dst_creds["access_token"])

    from sqlalchemy import select as _select

    from app.db.models.sync import UserSyncState

    state_res = await db.execute(_select(UserSyncState).where(UserSyncState.user_id == user.id))
    state = state_res.scalar_one_or_none()

    from datetime import timedelta

    since = (
        state.last_komoot_sync_at
        if state and state.last_komoot_sync_at
        else datetime.now(UTC) - timedelta(days=30)
    )

    try:
        tours = await komoot_client.get_tours(since=since)
    except Exception as exc:
        logger.error("_run_komoot_to_runalyze: Failed to fetch tours: %s", exc)
        return

    synced_count = 0
    for tour in tours:
        try:
            from app.db.models.sync import SyncedActivity as _SA

            already = await db.execute(
                _select(_SA).where(
                    _SA.user_id == user.id,
                    _SA.komoot_tour_id == tour.id,
                    _SA.destination_platform == "runalyze",
                    _SA.sync_status == "completed",
                )
            )
            if already.scalar_one_or_none():
                logger.debug("Tour %s already synced to runalyze — skipping", tour.id)
                continue

            gpx_bytes = await komoot_client.download_gpx(tour.id)
            activity_id = await runalyze_client.upload_gpx(
                gpx_bytes=gpx_bytes,
                external_id=f"komoot_{tour.id}",
            )

            record = _SA(
                user_id=user.id,
                pipeline_id=pipeline.id,
                komoot_tour_id=tour.id,
                destination_platform="runalyze",
                destination_activity_id=activity_id,
                sync_direction="komoot_to_runalyze",
                sync_status="completed",
                activity_name=tour.name,
                sport_type=tour.sport,
                distance_m=tour.distance_m,
                elevation_up_m=tour.elevation_up_m,
                started_at=tour.date,
            )
            db.add(record)
            await db.commit()
            synced_count += 1

        except Exception as exc:
            logger.error("_run_komoot_to_runalyze: Failed for tour %s: %s", tour.id, exc)

    logger.info("_run_komoot_to_runalyze: pipeline %s → %d tours synced", pipeline.id, synced_count)


# ── Direct GPX → Strava upload ────────────────────────────────────────────────


async def sync_gpx_to_strava(ctx: dict, activity_id: str, user_id: str) -> None:
    """Upload a stored GPX directly to Strava and update the SyncedActivity record.

    Works for imported and seeded activities (gpx_data stored in DB) as well as
    komoot-sourced activities where the GPX is downloaded on demand.
    """
    logger.info("sync_gpx_to_strava: activity=%s user=%s", activity_id, user_id)

    async with AsyncSessionLocal() as db:
        # Load activity
        act_res = await db.execute(
            select(SyncedActivity).where(
                SyncedActivity.id == activity_id,
                SyncedActivity.user_id == user_id,
            )
        )
        activity = act_res.scalar_one_or_none()
        if not activity:
            logger.warning("sync_gpx_to_strava: activity %s not found", activity_id)
            return

        if activity.strava_activity_id:
            logger.info("sync_gpx_to_strava: activity %s already on Strava — skipping", activity_id)
            return

        # Load user
        user_res = await db.execute(
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.strava_token), selectinload(User.subscription))
        )
        user = user_res.scalar_one_or_none()

        if not user:
            logger.warning("sync_gpx_to_strava: user %s not found", user_id)
            return

        if not user.strava_token:
            activity.sync_status = "failed"
            activity.conflict_reason = "No Strava connection found. Connect Strava first."
            await db.commit()
            return

        # Resolve GPX bytes — use stored data or download from Komoot
        gpx_bytes: bytes | None = activity.gpx_data

        if not gpx_bytes and activity.komoot_tour_id and activity.source == "komoot":
            # Resolve Komoot credentials from the Connection table
            km_email: str | None = None
            km_password: str | None = None
            km_uid: str | None = None
            km_conn_res = await db.execute(
                select(Connection).where(
                    Connection.user_id == user_id,
                    Connection.platform == "komoot",
                    Connection.status != "disconnected",
                )
            )
            km_conn = km_conn_res.scalar_one_or_none()
            if km_conn and km_conn.credentials_enc:
                km_creds = json.loads(security.decrypt(km_conn.credentials_enc))
                km_email = km_creds.get("email")
                km_password = km_creds.get("password")
                km_uid = km_creds.get("user_id")

            if not km_email or not km_password or not km_uid:
                activity.sync_status = "failed"
                activity.conflict_reason = "No GPX stored and Komoot is not connected."
                await db.commit()
                return
            try:
                komoot = KomootClient(
                    email=km_email,
                    password=km_password,
                    user_id=km_uid,
                )
                gpx_bytes = await komoot.download_gpx(activity.komoot_tour_id)
            except Exception as exc:
                logger.error("sync_gpx_to_strava: Komoot GPX download failed: %s", exc)
                activity.sync_status = "failed"
                activity.conflict_reason = f"Could not download GPX from Komoot: {exc}"
                await db.commit()
                return

        if not gpx_bytes:
            activity.sync_status = "failed"
            activity.conflict_reason = "No GPX track available for this activity."
            await db.commit()
            return

        # Get a valid Strava access token
        try:
            access_token = await _get_valid_strava_access_token(user)
        except Exception as exc:
            logger.error("sync_gpx_to_strava: token error for user %s: %s", user_id, exc)
            activity.sync_status = "failed"
            activity.conflict_reason = f"Strava authentication failed: {exc}"
            await db.commit()
            return

        # Resolve StravaApp for rate limiting
        app_res = await db.execute(
            select(StravaApp).where(StravaApp.id == user.strava_token.strava_app_id)
        )
        strava_app = app_res.scalar_one_or_none()
        if not strava_app:
            activity.sync_status = "failed"
            activity.conflict_reason = "Strava app configuration error."
            await db.commit()
            return

        tier_str = user.subscription.tier if user.subscription else "free"
        strava = StravaClient(access_token=access_token)
        sport = to_strava_sport(activity.sport_type or "")

        try:
            activity.sync_status = "processing"
            await db.commit()

            upload_id = await rate_limit_guard.call(
                strava_app.id,
                tier_str,
                strava.upload_gpx,
                gpx_bytes=gpx_bytes,
                name=activity.activity_name or "Imported Activity",
                description="Synced via RoutePass",
                sport_type=sport,
                external_id=f"routepass_{activity_id}",
            )
            strava_activity_id = await strava.poll_upload(upload_id)

            activity.strava_activity_id = strava_activity_id
            activity.destination_platform = "strava"
            activity.destination_activity_id = strava_activity_id
            activity.sync_status = "completed"
            activity.sync_direction = (
                "komoot_to_strava" if activity.source == "komoot" else "import_to_strava"
            )
            activity.conflict_reason = None
            await db.commit()
            logger.info(
                "sync_gpx_to_strava: activity %s → Strava %s", activity_id, strava_activity_id
            )

        except Exception as exc:
            logger.error("sync_gpx_to_strava: upload failed for %s: %s", activity_id, exc)
            activity.sync_status = "failed"
            activity.conflict_reason = f"Strava upload failed: {exc}"
            await db.commit()


# ── Direct GPX → Komoot upload ────────────────────────────────────────────────


async def sync_activity_to_komoot(ctx: dict, activity_id: str, user_id: str) -> None:
    """Upload a stored GPX to Komoot as a recorded tour and update the SyncedActivity record.

    Requires the user to have Komoot credentials set (via Connections page).
    Komoot upload uses the unofficial v007 API — may fail if the endpoint changes.
    """
    logger.info("sync_activity_to_komoot: activity=%s user=%s", activity_id, user_id)

    async with AsyncSessionLocal() as db:
        act_res = await db.execute(
            select(SyncedActivity).where(
                SyncedActivity.id == activity_id,
                SyncedActivity.user_id == user_id,
            )
        )
        activity = act_res.scalar_one_or_none()
        if not activity:
            logger.warning("sync_activity_to_komoot: activity %s not found", activity_id)
            return

        if activity.komoot_tour_id and not activity.komoot_tour_id.startswith("seed_"):
            # Already on Komoot (real tour ID, not the seed_ sentinel)
            logger.info(
                "sync_activity_to_komoot: activity %s already has komoot_tour_id — skipping",
                activity_id,
            )
            return

        user_res = await db.execute(
            select(User).where(User.id == user_id).options(selectinload(User.subscription))
        )
        user = user_res.scalar_one_or_none()
        if not user:
            return

        # Resolve Komoot credentials from the Connection table.
        komoot_email: str | None = None
        komoot_password: str | None = None
        komoot_user_id_str: str | None = None

        conn_res = await db.execute(
            select(Connection).where(
                Connection.user_id == user_id,
                Connection.platform == "komoot",
                Connection.status != "disconnected",
            )
        )
        komoot_conn = conn_res.scalar_one_or_none()
        if komoot_conn and komoot_conn.credentials_enc:
            creds = json.loads(security.decrypt(komoot_conn.credentials_enc))
            komoot_email = creds.get("email")
            komoot_password = creds.get("password")
            komoot_user_id_str = creds.get("user_id")

        if not komoot_email or not komoot_password or not komoot_user_id_str:
            activity.sync_status = "failed"
            activity.conflict_reason = (
                "Komoot is not connected. Add credentials in Settings → Connections."
            )
            await db.commit()
            return

        gpx_bytes: bytes | None = activity.gpx_data
        if not gpx_bytes:
            activity.sync_status = "failed"
            activity.conflict_reason = (
                "No GPX track available. Only activities with a GPS track"
                " can be uploaded to Komoot."
            )
            await db.commit()
            return

        komoot = KomootClient(
            email=komoot_email,
            password=komoot_password,
            user_id=komoot_user_id_str,
        )

        try:
            activity.sync_status = "processing"
            await db.commit()

            tour_id = await komoot.upload_tour(
                gpx_bytes=gpx_bytes,
                name=activity.activity_name or "Imported Activity",
                sport_type=to_komoot_sport(activity.sport_type or ""),
                description="Synced via RoutePass",
            )

            activity.komoot_tour_id = tour_id
            activity.destination_platform = "komoot"
            activity.destination_activity_id = tour_id
            activity.sync_status = "completed"
            activity.sync_direction = "import_to_komoot"
            activity.conflict_reason = None
            await db.commit()
            logger.info(
                "sync_activity_to_komoot: activity %s → Komoot tour %s", activity_id, tour_id
            )

        except Exception as exc:
            logger.error(
                "sync_activity_to_komoot: upload failed for activity %s: %s", activity_id, exc
            )
            activity.sync_status = "failed"
            activity.conflict_reason = f"Komoot upload failed: {exc}"
            await db.commit()

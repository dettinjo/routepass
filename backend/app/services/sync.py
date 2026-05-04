from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.garmin import GarminClient

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import rate_limit_guard
from app.db.models.sync import SyncedActivity, SyncRule, UserSyncState
from app.db.models.user import StravaApp, User
from app.services.activity_record import ActivityRecord
from app.services.komoot import KomootClient, Tour
from app.services.strava import StravaClient

# Strava activity lists use the legacy `type` field for older activities and
# `sport_type` for newer ones. We prefer the newer field where available.
_STRAVA_SPORT = lambda a: a.get("sport_type") or a.get("type")  # noqa: E731

UTC = UTC

logger = logging.getLogger(__name__)


def _match_condition(record: ActivityRecord, conditions: dict) -> bool:
    """Return True if all conditions match the record. All conditions must pass (AND logic)."""
    distance_km = (record.distance_m or 0) / 1000.0
    elevation_m = record.elevation_gain_m or 0
    sport = record.sport_type or ""

    for key, value in conditions.items():
        if key in ("sport_type", "sport"):
            # {"sport_type": {"is": ["e_road_cycling", "e_touringbicycle"]}}
            # {"sport_type": {"is_not": ["hike"]}}
            # Legacy plain equality: {"sport_type": "E-Bike"}
            if isinstance(value, dict):
                if "is" in value:
                    allowed = [s.lower() for s in value["is"]]
                    if sport.lower() not in allowed:
                        return False
                if "is_not" in value:
                    blocked = [s.lower() for s in value["is_not"]]
                    if sport.lower() in blocked:
                        return False
            else:
                if sport.lower() != str(value).lower():
                    return False

        elif key == "distance_km":
            if isinstance(value, dict):
                if "gt" in value and not (distance_km > value["gt"]):
                    return False
                if "lt" in value and not (distance_km < value["lt"]):
                    return False
                if "between" in value:
                    lo, hi = value["between"]
                    if not (lo <= distance_km <= hi):
                        return False
            else:
                return False

        elif key == "elevation_m":
            if isinstance(value, dict):
                if "gt" in value and not (elevation_m > value["gt"]):
                    return False
                if "lt" in value and not (elevation_m < value["lt"]):
                    return False
            else:
                return False

        elif key == "name_contains":
            if str(value).lower() not in record.name.lower():
                return False

    return True


def _apply_action(record: ActivityRecord, actions: dict, user: User) -> tuple:
    """Apply rule actions to an activity record.

    Returns (skip, modified_record, extra_kwargs) where extra_kwargs are passed
    to the destination upload call (e.g. hide_from_home override).
    """
    from dataclasses import replace

    extras: dict = {}

    if actions.get("skip") or actions.get("sync_to") == "None":
        return True, record, extras

    if "set_sport_type" in actions:
        # Store the destination-mapped sport in extra so ingestors can use it.
        new_extra = {**record.extra, "strava_sport": actions["set_sport_type"]}
        record = replace(record, extra=new_extra)

    if "name_template" in actions:
        tmpl = actions["name_template"]
        try:
            new_name = tmpl.format(
                name=record.name,
                distance=(record.distance_m or 0) / 1000,
                elevation=int(record.elevation_gain_m or 0),
            )
            record = replace(record, name=new_name)
        except Exception:
            pass

    if "append_description" in actions:
        extras["description_suffix"] = actions["append_description"]

    if "set_hide_from_home" in actions:
        extras["hide_from_home"] = bool(actions["set_hide_from_home"])

    return False, record, extras


# ── Platform → ActivityRecord converters ─────────────────────────────────────


def _komoot_tour_to_record(tour: Tour) -> ActivityRecord:
    """Convert a Komoot Tour to the platform-agnostic ActivityRecord."""
    return ActivityRecord(
        platform="komoot",
        external_id=tour.id,
        name=tour.name,
        description=tour.description or "",
        sport_type=tour.sport,
        started_at=tour.date,
        distance_m=tour.distance_m,
        elevation_gain_m=tour.elevation_up_m,
        duration_s=tour.duration_seconds,
        extra={"strava_sport": tour.strava_sport},
    )


def _garmin_activity_to_record(activity: dict) -> ActivityRecord:
    """Convert a raw Garmin Connect activity dict to ActivityRecord."""
    started = None
    try:
        ts = activity.get("startTimeLocal") or activity.get("startTimeGMT") or ""
        if ts:
            started = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        pass

    return ActivityRecord(
        platform="garmin",
        external_id=str(activity.get("activityId", "")),
        name=activity.get("activityName") or "",
        sport_type=activity.get("activityType", {}).get("typeKey", ""),
        started_at=started or datetime.now(UTC),
        distance_m=activity.get("distance"),
        elevation_gain_m=activity.get("elevationGain"),
        duration_s=activity.get("duration"),
        extra={"garmin_activity_id": activity.get("activityId")},
    )


class SyncService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get_or_create_sync_state(self, user_id: str) -> UserSyncState:
        result = await self.db.execute(
            select(UserSyncState).where(UserSyncState.user_id == user_id)
        )
        state = result.scalar_one_or_none()
        if not state:
            state = UserSyncState(user_id=user_id)
            self.db.add(state)
            await self.db.flush()
        return state

    async def _is_synced(self, user_id: str, tour_id: str) -> bool:
        result = await self.db.execute(
            select(SyncedActivity).where(
                SyncedActivity.user_id == user_id,
                SyncedActivity.komoot_tour_id == tour_id,
                SyncedActivity.sync_status == "completed",
            )
        )
        return result.scalar_one_or_none() is not None

    async def ingest_komoot_tours(
        self,
        user: User,
        komoot: KomootClient,
        since: datetime | None = None,
    ) -> int:
        """Fetch Komoot tours and store them in the hub DB without requiring Strava.

        Activities are stored as source='komoot', sync_status='completed' so they appear
        in the activities overview immediately. strava_activity_id is left NULL and can be
        filled in later when the user connects Strava and uploads.

        Args:
            since: Watermark override. When provided (E5 per-connection path), the caller
                   manages the ConnectionSyncState and this method skips UserSyncState.
                   When omitted, falls back to UserSyncState.last_komoot_sync_at.

        Returns the count of newly stored tours.
        """
        state = await self._get_or_create_sync_state(str(user.id))

        if since is None:
            # Legacy path: use global UserSyncState watermark
            if state.last_komoot_sync_at is None:
                since = datetime.now(UTC) - timedelta(days=90)
                logger.info(
                    "Initial Komoot ingest for user %s — looking back to %s", user.id, since
                )
            else:
                since = state.last_komoot_sync_at
                logger.info("Komoot ingest for user %s since %s", user.id, since)
        else:
            logger.info(
                "Komoot ingest for user %s since %s (per-connection watermark)", user.id, since
            )

        try:
            tours = await komoot.get_tours(since=since)
        except Exception as exc:
            logger.error("Komoot ingest: failed to fetch tours for user %s: %s", user.id, exc)
            state.last_error = f"Fetch failed: {exc}"
            state.last_error_at = datetime.now(UTC)
            await self.db.commit()
            return 0

        ingested = 0
        for tour in tours:
            try:
                existing = await self.db.execute(
                    select(SyncedActivity).where(
                        SyncedActivity.user_id == user.id,
                        SyncedActivity.komoot_tour_id == tour.id,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                self.db.add(
                    SyncedActivity(
                        user_id=user.id,
                        source="komoot",
                        komoot_tour_id=tour.id,
                        # sync_direction and destination_platform are NULL at ingest;
                        # they are set when the activity is actually pushed to a destination.
                        sync_direction=None,
                        destination_platform=None,
                        sync_status="completed",
                        activity_name=tour.name,
                        sport_type=tour.sport,
                        distance_m=tour.distance_m,
                        elevation_up_m=tour.elevation_up_m,
                        started_at=tour.date,
                        duration_seconds=tour.duration_seconds,
                    )
                )
                ingested += 1
                await self.db.commit()
            except Exception as exc:
                logger.error(
                    "Komoot ingest: failed to store tour %s for user %s: %s",
                    tour.id,
                    user.id,
                    exc,
                )

        state.last_komoot_sync_at = datetime.now(UTC)
        if ingested > 0:
            state.last_successful_sync_at = datetime.now(UTC)
            state.total_synced_count += ingested
        await self.db.commit()
        logger.info("Komoot ingest: %d new tours stored for user %s", ingested, user.id)
        return ingested

    async def ingest_strava_activities(
        self,
        user: User,
        strava: StravaClient,
        strava_app: StravaApp,
    ) -> int:
        """Pull Strava-native activities into the hub DB using a watermark.

        Industry pattern: watermark-based incremental sync — only fetch activities
        newer than `last_strava_sync_at`. First run looks back 90 days.
        Idempotent: the unique constraint on (user_id, strava_activity_id) means
        activities already linked from a Komoot→Strava upload are silently skipped
        by the dedup query before we even attempt an insert.

        Returns count of newly stored activities.
        """
        state = await self._get_or_create_sync_state(str(user.id))
        tier_str = user.subscription.tier if user.subscription else "free"

        since = (
            state.last_strava_sync_at
            if state.last_strava_sync_at
            else datetime.now(UTC) - timedelta(days=90)
        )
        after_ts = int(since.timestamp())

        logger.info("Strava ingest for user %s since %s", user.id, since.isoformat())

        ingested = 0
        page = 1

        while True:
            try:
                activities = await rate_limit_guard.call(
                    strava_app.id,
                    tier_str,
                    strava.get_activities,
                    after=after_ts,
                    page=page,
                    per_page=50,
                )
            except Exception as exc:
                logger.error(
                    "Strava ingest: failed to fetch page %d for user %s: %s",
                    page,
                    user.id,
                    exc,
                )
                break

            if not activities:
                break

            for activity in activities:
                strava_id = str(activity.get("id", ""))
                if not strava_id:
                    continue

                # Skip if already in hub — covers both standalone Strava activities
                # and activities already linked from a Komoot→Strava upload.
                existing = await self.db.execute(
                    select(SyncedActivity).where(
                        SyncedActivity.user_id == user.id,
                        SyncedActivity.strava_activity_id == strava_id,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                started_at = None
                try:
                    started_at = datetime.fromisoformat(
                        activity.get("start_date", "").replace("Z", "+00:00")
                    )
                except Exception:
                    pass

                self.db.add(
                    SyncedActivity(
                        user_id=user.id,
                        source="strava",
                        strava_activity_id=strava_id,
                        sync_direction=None,
                        sync_status="completed",
                        activity_name=activity.get("name"),
                        sport_type=_STRAVA_SPORT(activity),
                        distance_m=activity.get("distance"),
                        elevation_up_m=activity.get("total_elevation_gain"),
                        duration_seconds=activity.get("moving_time"),
                        started_at=started_at,
                    )
                )
                ingested += 1

            await self.db.commit()
            page += 1

            if len(activities) < 50:
                break  # last page

        state.last_strava_sync_at = datetime.now(UTC)
        if ingested > 0:
            state.last_successful_sync_at = datetime.now(UTC)
            state.total_synced_count += ingested
        await self.db.commit()

        logger.info("Strava ingest: %d new activities stored for user %s", ingested, user.id)
        return ingested

    async def upload_komoot_to_strava(
        self,
        user: User,
        strava_app: StravaApp,
        komoot: KomootClient,
        strava: StravaClient,
    ) -> int:
        """Upload stored source='komoot' activities (without strava_activity_id) to Strava.

        Operates on activities already in the hub DB. Downloads GPX on-demand, uploads
        to Strava, and updates the record. Returns the count successfully uploaded.
        """
        tier_str = user.subscription.tier if user.subscription else "free"

        # Pull sync rules
        rules_stmt = (
            select(SyncRule)
            .where(
                SyncRule.user_id == user.id,
                SyncRule.is_active == True,  # noqa: E712
                SyncRule.direction.in_(["komoot_to_strava", "both"]),
            )
            .order_by(SyncRule.rule_order.asc())
        )
        rules_res = await self.db.execute(rules_stmt)
        rules = rules_res.scalars().all()

        pending_res = await self.db.execute(
            select(SyncedActivity).where(
                SyncedActivity.user_id == user.id,
                SyncedActivity.source == "komoot",
                sa.or_(
                    SyncedActivity.destination_platform.is_(None),
                    SyncedActivity.destination_platform != "strava",
                ),
            )
        )
        pending = pending_res.scalars().all()

        uploaded = 0
        for act in pending:
            if not act.komoot_tour_id:
                continue
            try:
                # Build a platform-agnostic record for rule evaluation
                rec = ActivityRecord(
                    platform="komoot",
                    external_id=act.komoot_tour_id,
                    name=act.activity_name or "",
                    description="",
                    sport_type=act.sport_type or "",
                    started_at=act.started_at or datetime.now(UTC),
                    distance_m=act.distance_m or 0,
                    elevation_gain_m=act.elevation_up_m or 0,
                    extra={"strava_sport": act.sport_type or ""},
                )

                skip_tour = False
                rule_extras: dict = {}
                for rule in rules:
                    if _match_condition(rec, rule.conditions):
                        skip_tour, rec, rule_extras = _apply_action(rec, rule.actions, user)
                        if skip_tour:
                            logger.info("Rule skipped tour %s for Strava", rec.external_id)
                        break

                if skip_tour:
                    continue

                strava_sport = rec.extra.get("strava_sport") or rec.sport_type
                gpx_bytes = await komoot.download_gpx(act.komoot_tour_id)

                upload_id = await rate_limit_guard.call(
                    strava_app.id,
                    tier_str,
                    strava.upload_gpx,
                    gpx_bytes=gpx_bytes,
                    name=rec.name,
                    description=rec.description or "",
                    sport_type=strava_sport,
                    external_id=f"komoot_{act.komoot_tour_id}",
                )
                strava_activity_id = await rate_limit_guard.call(
                    strava_app.id,
                    tier_str,
                    strava.poll_upload,
                    upload_id=upload_id,
                )

                hide = rule_extras.get("hide_from_home", False)
                try:
                    await rate_limit_guard.call(
                        strava_app.id,
                        tier_str,
                        strava.update_activity,
                        activity_id=strava_activity_id,
                        hide_from_home=hide,
                    )
                except Exception as e:
                    logger.warning("Could not set hide_from_home on %s: %s", strava_activity_id, e)

                act.strava_activity_id = strava_activity_id
                act.destination_platform = "strava"
                act.destination_activity_id = strava_activity_id
                act.sync_direction = "komoot_to_strava"
                await self.db.commit()
                uploaded += 1
                logger.info(
                    "Uploaded Komoot tour %s → Strava %s", act.komoot_tour_id, strava_activity_id
                )

            except Exception as exc:
                err_str = str(exc)
                # Strava signals a duplicate by embedding the existing activity URL in
                # the error message: "… duplicate of <a href='/activities/18283071249'…"
                m = re.search(r"/activities/(\d+)", err_str)
                if m:
                    existing_id = m.group(1)
                    act.strava_activity_id = existing_id
                    act.destination_platform = "strava"
                    act.destination_activity_id = existing_id
                    act.sync_direction = "komoot_to_strava"
                    await self.db.commit()
                    uploaded += 1
                    logger.info(
                        "Strava duplicate detected: linked tour %s → existing activity %s",
                        act.komoot_tour_id,
                        existing_id,
                    )
                else:
                    logger.error(
                        "upload_komoot_to_strava: failed for tour %s user %s: %s",
                        act.komoot_tour_id,
                        user.id,
                        exc,
                    )

        logger.info("Strava upload: %d activities uploaded for user %s", uploaded, user.id)
        return uploaded

    async def sync_komoot_to_strava(
        self,
        user: User,
        strava_app: StravaApp,
        komoot: KomootClient,
        strava: StravaClient,
    ) -> int:
        """Run the one-way sync from Komoot to Strava for a single user."""
        logger.info("Starting sync for user %s", user.id)

        state = await self._get_or_create_sync_state(str(user.id))

        if state.last_komoot_sync_at is None:
            # First sync: look back 30 days
            since = datetime.now(UTC) - timedelta(days=30)
            logger.info("Initial sync for user %s — looking back to %s", user.id, since)
        else:
            since = state.last_komoot_sync_at
            logger.info("Syncing newer than %s for user %s", since, user.id)

        try:
            tours = await komoot.get_tours(since=since)
        except Exception as exc:
            logger.error("Failed to fetch Komoot tours for user %s: %s", user.id, exc)
            state.last_error = f"Fetch failed: {exc}"
            state.last_error_at = datetime.now(UTC)
            await self.db.commit()
            return 0

        synced_count = 0

        # Pull dynamic rules
        rules_stmt = (
            select(SyncRule)
            .where(
                SyncRule.user_id == user.id,
                SyncRule.is_active == True,  # noqa: E712
                SyncRule.direction.in_(["komoot_to_strava", "both"]),
            )
            .order_by(SyncRule.rule_order.asc())
        )
        rules_res = await self.db.execute(rules_stmt)
        rules = rules_res.scalars().all()

        for tour in tours:
            try:
                rec = _komoot_tour_to_record(tour)

                # Evaluate rules (first match wins)
                skip_tour = False
                rule_extras: dict = {}
                for rule in rules:
                    if _match_condition(rec, rule.conditions):
                        skip_tour, rec, rule_extras = _apply_action(rec, rule.actions, user)
                        if skip_tour:
                            logger.info("Rule '%s' skipped tour %s", rule.name, tour.id)
                        else:
                            logger.debug("Rule '%s' modified tour %s", rule.name, tour.id)
                        break  # first matching rule wins

                if skip_tour:
                    continue

                # Check DB for duplicate
                if await self._is_synced(str(user.id), tour.id):
                    logger.debug("Tour %s already synced for user %s", tour.id, user.id)
                    continue

                logger.info("Syncing tour %s for %s", tour.id, user.id)

                strava_sport = rec.extra.get("strava_sport") or rec.sport_type
                gpx_bytes = await komoot.download_gpx(tour.id)
                external_id = f"komoot_{tour.id}"

                tier_str = user.subscription.tier if user.subscription else "free"

                # Upload to Strava (guarded by rate limiter)
                upload_id = await rate_limit_guard.call(
                    strava_app.id,
                    tier_str,
                    strava.upload_gpx,
                    gpx_bytes=gpx_bytes,
                    name=rec.name,
                    description=rec.description,
                    sport_type=strava_sport,
                    external_id=external_id,
                )

                # Poll status (guarded)
                activity_id = await rate_limit_guard.call(
                    strava_app.id,
                    tier_str,
                    strava.poll_upload,
                    upload_id=upload_id,
                )

                # Update settings (guarded) — rule may override hide_from_home
                hide = rule_extras.get("hide_from_home", False)
                try:
                    await rate_limit_guard.call(
                        strava_app.id,
                        tier_str,
                        strava.update_activity,
                        activity_id=activity_id,
                        hide_from_home=hide,
                    )
                except Exception as e:
                    logger.warning(
                        "Could not set hide_from_home on activity %s: %s", activity_id, e
                    )

                # Record in local DB
                activity_record = SyncedActivity(
                    user_id=user.id,
                    source="komoot",
                    komoot_tour_id=tour.id,
                    strava_activity_id=activity_id,
                    destination_platform="strava",
                    destination_activity_id=activity_id,
                    sync_direction="komoot_to_strava",
                    sync_status="completed",
                    activity_name=rec.name,
                    sport_type=tour.sport,
                    distance_m=tour.distance_m,
                    elevation_up_m=tour.elevation_up_m,
                    started_at=tour.date,
                )
                self.db.add(activity_record)
                synced_count += 1
                state.total_synced_count += 1

                # Commit progressively per successfully uploaded tour
                await self.db.commit()

            except Exception as exc:
                logger.error("Failed syncing tour %s for user %s: %s", tour.id, user.id, exc)
                # Keep rolling despite the error
                continue

        # Update last sync marker
        state.last_komoot_sync_at = datetime.now(UTC)
        if synced_count > 0:
            state.last_successful_sync_at = datetime.now(UTC)

        await self.db.commit()
        logger.info("Sync complete for user %s — %d tours synced", user.id, synced_count)

        return synced_count

    async def ingest_garmin_activities(
        self,
        user: User,
        garmin: GarminClient,  # type: ignore[name-defined]
        since: datetime | None = None,
    ) -> int:
        """Fetch Garmin Connect activities and store them in the hub DB.

        Uses a watermark (`since`) to do incremental syncs — first run looks back 90
        days, subsequent runs only fetch what's newer. Returns count of new rows stored.
        """

        if since is None:
            since = datetime.now(UTC) - timedelta(days=90)
            logger.info("Initial Garmin ingest for user %s — looking back to %s", user.id, since)
        else:
            logger.info(
                "Garmin ingest for user %s since %s (per-connection watermark)", user.id, since
            )

        try:
            activities = await garmin.get_activities_since(since=since)
        except Exception as exc:
            logger.error("Garmin ingest: failed to fetch for user %s: %s", user.id, exc)
            return 0

        ingested = 0
        for activity in activities:
            garmin_id = str(activity.get("activityId", ""))
            if not garmin_id:
                continue

            try:
                existing = await self.db.execute(
                    select(SyncedActivity).where(
                        SyncedActivity.user_id == user.id,
                        # garmin activities are stored via komoot_tour_id as "garmin_<id>"
                        # to avoid schema changes until a dedicated column exists.
                        SyncedActivity.komoot_tour_id == f"garmin_{garmin_id}",
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                rec = _garmin_activity_to_record(activity)

                self.db.add(
                    SyncedActivity(
                        user_id=user.id,
                        source="garmin",
                        # Re-use komoot_tour_id as a generic external-id slot until
                        # a dedicated garmin_activity_id column is added (A5-ph3 deferred).
                        komoot_tour_id=f"garmin_{garmin_id}",
                        sync_direction=None,
                        destination_platform=None,
                        sync_status="completed",
                        activity_name=rec.name,
                        sport_type=rec.sport_type,
                        distance_m=rec.distance_m,
                        elevation_up_m=rec.elevation_gain_m,
                        started_at=rec.started_at,
                        duration_seconds=(
                            int(rec.duration_s) if rec.duration_s is not None else None
                        ),
                    )
                )
                ingested += 1
                await self.db.commit()
            except Exception as exc:
                logger.error(
                    "Garmin ingest: failed to store activity %s for user %s: %s",
                    garmin_id,
                    user.id,
                    exc,
                )

        logger.info("Garmin ingest: %d new activities stored for user %s", ingested, user.id)
        return ingested

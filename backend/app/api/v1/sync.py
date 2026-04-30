from __future__ import annotations

import logging
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.db.models.connection import Connection
from app.db.models.sync import SyncedActivity, UserSyncState
from app.db.models.user import StravaToken, User

UTC = UTC

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sync"])


def _serialize_activity(activity: SyncedActivity | None) -> dict | None:
    if activity is None:
        return None

    return {
        "id": str(activity.id),
        "komoot_tour_id": activity.komoot_tour_id,
        "strava_activity_id": activity.strava_activity_id,
        "sync_direction": activity.sync_direction,
        "sync_status": activity.sync_status,
        "activity_name": activity.activity_name,
        "sport_type": activity.sport_type,
        "distance_m": activity.distance_m,
        "elevation_up_m": activity.elevation_up_m,
        "started_at": activity.started_at.isoformat() if activity.started_at else None,
        "synced_at": activity.synced_at.isoformat(),
    }


@router.get("/status")
async def get_sync_status(
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Return the current sync state for the user, driven by the Connection table."""
    state_result = await db.execute(select(UserSyncState).where(UserSyncState.user_id == user.id))
    state = state_result.scalar_one_or_none()

    activity_result = await db.execute(
        select(SyncedActivity)
        .where(SyncedActivity.user_id == user.id)
        .order_by(SyncedActivity.synced_at.desc())
        .limit(1)
    )
    latest_activity = activity_result.scalar_one_or_none()

    # Resolve connected platforms from the Connection table (source of truth).
    # StravaToken still exists as legacy — include it so existing Strava users aren't broken.
    connections_result = await db.execute(select(Connection).where(Connection.user_id == user.id))
    connections = connections_result.scalars().all()
    connected_platforms = {c.platform for c in connections}

    strava_token = (
        await db.execute(select(StravaToken).where(StravaToken.user_id == user.id))
    ).scalar_one_or_none()
    if strava_token:
        connected_platforms.add("strava")

    return {
        "connections": [{"platform": p, "connected": True} for p in sorted(connected_platforms)],
        # Legacy fields retained for backward-compatibility until frontend is updated (F3).
        "komoot_connected": "komoot" in connected_platforms,
        "strava_connected": "strava" in connected_platforms,
        "last_komoot_sync_at": state.last_komoot_sync_at.isoformat()
        if state and state.last_komoot_sync_at
        else None,
        "last_strava_sync_at": state.last_strava_sync_at.isoformat()
        if state and state.last_strava_sync_at
        else None,
        "last_successful_sync_at": (
            state.last_successful_sync_at.isoformat()
            if state and state.last_successful_sync_at
            else None
        ),
        "total_synced_count": state.total_synced_count if state else 0,
        "last_error": state.last_error if state else None,
        "last_error_at": state.last_error_at.isoformat() if state and state.last_error_at else None,
        "latest_activity": _serialize_activity(latest_activity),
    }


@router.post("/trigger")
async def trigger_sync(
    request: Request,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Trigger a manual sync of all connected sources via background workers."""
    arq_pool = request.app.state.arq_pool
    if not arq_pool:
        return {"status": "error", "message": "Worker pool not available"}
    await arq_pool.enqueue_job("poll_user_sources", str(user.id))
    return {"status": "queued", "message": "Sync job enqueued successfully"}


@router.post("/rebuild-history", status_code=status.HTTP_410_GONE)
async def rebuild_history(
    _user: User = Depends(deps.get_current_user),
) -> dict:
    """Removed endpoint — was a one-time Komoot→Strava migration utility."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "This endpoint has been removed. The Komoot→Strava history rebuild "
            "was a one-time migration utility and no longer applies to the "
            "multi-platform hub architecture."
        ),
    )

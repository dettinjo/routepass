from __future__ import annotations

import logging
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.db.models.connection import Connection
from app.db.models.pipeline import Pipeline
from app.db.models.sync import ConnectionSyncState, SyncedActivity
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
    activity_result = await db.execute(
        select(SyncedActivity)
        .where(SyncedActivity.user_id == user.id)
        .order_by(SyncedActivity.synced_at.desc())
        .limit(1)
    )
    latest_activity = activity_result.scalar_one_or_none()

    # Resolve all connections and their per-connection watermarks.
    connections_result = await db.execute(select(Connection).where(Connection.user_id == user.id))
    connections = connections_result.scalars().all()

    css_result = await db.execute(
        select(ConnectionSyncState).where(ConnectionSyncState.user_id == user.id)
    )
    css_by_conn: dict = {str(s.connection_id): s for s in css_result.scalars().all()}

    # StravaToken counts as a Strava connection for legacy users.
    strava_token = (
        await db.execute(select(StravaToken).where(StravaToken.user_id == user.id))
    ).scalar_one_or_none()

    conn_statuses = []
    for c in connections:
        css = css_by_conn.get(str(c.id))
        conn_statuses.append(
            {
                "platform": c.platform,
                "display_name": c.display_name or c.platform.replace("_", " ").title(),
                "connected": c.status != "disconnected",
                "last_sync_at": css.last_synced_at.isoformat()
                if css and css.last_synced_at
                else None,
                "error": css.last_error if css else None,
            }
        )

    if strava_token and not any(c["platform"] == "strava" for c in conn_statuses):
        conn_statuses.append(
            {
                "platform": "strava",
                "display_name": "Strava",
                "connected": True,
                "last_sync_at": None,
                "error": None,
            }
        )

    active_pipelines_result = await db.execute(
        select(func.count(Pipeline.id)).where(
            Pipeline.user_id == user.id,
            Pipeline.enabled == True,  # noqa: E712
        )
    )
    active_pipelines = active_pipelines_result.scalar_one()

    all_sync_times = [c["last_sync_at"] for c in conn_statuses if c["last_sync_at"]]
    last_sync_at = max(all_sync_times) if all_sync_times else None

    connected_platforms = {c["platform"] for c in conn_statuses if c["connected"]}

    return {
        "connections": conn_statuses,
        "active_pipelines": active_pipelines,
        "last_sync_at": last_sync_at,
        # Legacy fields — retained for backward compat; remove when frontend is updated
        "komoot_connected": "komoot" in connected_platforms,
        "strava_connected": "strava" in connected_platforms,
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
    await arq_pool.enqueue_job(
        "poll_user_sources",
        str(user.id),
        _job_id=f"poll_user_{user.id}",  # dedup: prevents duplicate queuing
    )
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

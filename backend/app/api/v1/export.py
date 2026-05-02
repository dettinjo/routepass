from __future__ import annotations

import io
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.db.models.connection import Connection
from app.db.models.sync import SyncedActivity, SyncRule
from app.db.models.user import User
from app.services.audit import write_audit

UTC = UTC

logger = logging.getLogger(__name__)

router = APIRouter(tags=["export"])


@router.get("/me")
async def export_my_data(
    request: Request,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> StreamingResponse:
    """Export all personal data as a downloadable JSON file (GDPR Article 20)."""
    activities = (
        (await db.execute(select(SyncedActivity).where(SyncedActivity.user_id == user.id)))
        .scalars()
        .all()
    )

    connections = (
        (await db.execute(select(Connection).where(Connection.user_id == user.id))).scalars().all()
    )

    rules = (await db.execute(select(SyncRule).where(SyncRule.user_id == user.id))).scalars().all()

    export = {
        "exported_at": datetime.now(UTC).isoformat(),
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
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

    logger.info("Data export requested by user %s", user.id)
    await write_audit(db, user.id, "export_requested", request)
    await db.commit()

    buf = io.BytesIO(json.dumps(export, indent=2).encode())
    return StreamingResponse(
        buf,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="routepass-export-{user.id}.json"'},
    )

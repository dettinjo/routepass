from __future__ import annotations

import json
from datetime import UTC
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.polling import (
    MAX_POLL_INTERVAL_MIN,
    POLL_INTERVALS,
    effective_poll_interval_min,
    poll_interval_bounds,
)
from app.core.security import encrypt
from app.db.models.connection import Connection
from app.db.models.sync import ConnectionSyncState
from app.db.models.user import User

_KOMOOT_V006 = "https://api.komoot.de/v006"
_KOMOOT_BASE = "https://www.komoot.de/api/v007"

UTC = UTC

router = APIRouter(tags=["connections"])


class ConnectionCreate(BaseModel):
    platform: str
    display_name: str
    credentials: dict | None = None


class ConnectionUpdate(BaseModel):
    poll_interval_min: int | None = None


class ConnectionResponse(BaseModel):
    id: str
    platform: str
    display_name: str
    status: str
    last_synced_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str


def _serialize(conn: Connection, last_error: str | None = None) -> dict:
    is_source = conn.platform in POLL_INTERVALS
    poll: dict | None = None
    if is_source:
        default, minimum = poll_interval_bounds(conn.platform)
        poll = {
            "configured": conn.poll_interval_min,
            "effective": effective_poll_interval_min(conn.platform, conn.poll_interval_min),
            "default": default,
            "min": minimum,
            "max": MAX_POLL_INTERVAL_MIN,
        }
    return {
        "id": str(conn.id),
        "platform": conn.platform,
        "display_name": conn.display_name,
        "status": conn.status,
        "last_synced_at": conn.last_synced_at.isoformat() if conn.last_synced_at else None,
        "last_error": last_error,
        "is_source": is_source,
        "poll_interval": poll,
        "created_at": conn.created_at.isoformat(),
        "updated_at": conn.updated_at.isoformat(),
    }


async def _validate_komoot_credentials(credentials: dict) -> None:
    """Authenticate against Komoot and auto-discover the numeric user ID.

    Uses the v006 /account/email/{email}/ endpoint (same approach as the
    open-source kompy library). v006 reliably returns username + a session
    token for ALL account types, including Google/Facebook-linked accounts
    where the v007 /account endpoint returns 404.
    """
    email = credentials.get("email", "").strip()
    password = credentials.get("password", "")
    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Komoot email and password are required.",
        )
    try:
        async with httpx.AsyncClient(
            auth=(email, password),
            headers={"Accept": "application/hal+json, application/json"},
            timeout=httpx.Timeout(15.0),
        ) as client:
            resp = await client.get(f"{_KOMOOT_V006}/account/email/{email}/")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach Komoot: {exc}",
        ) from exc

    if resp.status_code in (401, 403):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Komoot email or password.",
        )
    if not resp.is_success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Komoot API returned {resp.status_code}.",
        )

    # v006 response always includes the numeric username (user ID)
    account = resp.json()
    user_id = str(account.get("username", "") or "")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Komoot login succeeded but could not read user ID from response.",
        )
    credentials["user_id"] = user_id


_VALID_PLATFORMS = {
    "komoot",
    "strava",
    "garmin",
    "polar",
    "wahoo",
    "intervals_icu",
    "runalyze",
    "trainingpeaks",
    "webhook",
}


@router.get("")
async def list_connections(
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> list[dict]:
    result = await db.execute(
        select(Connection, ConnectionSyncState.last_error)
        .outerjoin(
            ConnectionSyncState,
            ConnectionSyncState.connection_id == Connection.id,
        )
        .where(Connection.user_id == user.id)
    )
    return [_serialize(conn, last_error) for conn, last_error in result.all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionCreate,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    if body.platform not in _VALID_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown platform: {body.platform}",
        )

    credentials_enc: bytes | None = None
    if body.credentials:
        if body.platform == "komoot":
            await _validate_komoot_credentials(body.credentials)

        credentials_enc = encrypt(json.dumps(body.credentials))

    conn = Connection(
        user_id=user.id,
        platform=body.platform,
        display_name=body.display_name,
        credentials_enc=credentials_enc,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return _serialize(conn)


@router.get("/{connection_id}")
async def get_connection(
    connection_id: UUID,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    result = await db.execute(
        select(Connection, ConnectionSyncState.last_error)
        .outerjoin(
            ConnectionSyncState,
            ConnectionSyncState.connection_id == Connection.id,
        )
        .where(
            Connection.id == connection_id,
            Connection.user_id == user.id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    conn, last_error = row
    return _serialize(conn, last_error)


@router.patch("/{connection_id}")
async def update_connection(
    connection_id: UUID,
    body: ConnectionUpdate,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    result = await db.execute(
        select(Connection).where(
            Connection.id == connection_id,
            Connection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    if body.poll_interval_min is not None:
        if conn.platform not in POLL_INTERVALS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Poll interval is not configurable for {conn.platform}.",
            )
        _, minimum = poll_interval_bounds(conn.platform)
        if not (minimum <= body.poll_interval_min <= MAX_POLL_INTERVAL_MIN):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Poll interval for {conn.platform} must be between "
                    f"{minimum} and {MAX_POLL_INTERVAL_MIN} minutes."
                ),
            )
        conn.poll_interval_min = body.poll_interval_min

    await db.commit()
    await db.refresh(conn)
    return _serialize(conn)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: UUID,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> None:
    result = await db.execute(
        select(Connection).where(
            Connection.id == connection_id,
            Connection.user_id == user.id,
        )
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    # Strava credentials live in the StravaToken table, not credentials_enc. Deleting
    # only the Connection row would leave the OAuth token behind — /auth/me would still
    # report Strava connected and the worker would keep pushing activities. Revoke both.
    if conn.platform == "strava":
        from app.db.models.user import StravaToken

        await db.execute(delete(StravaToken).where(StravaToken.user_id == user.id))

    await db.delete(conn)
    await db.commit()

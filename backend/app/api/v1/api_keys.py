from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.security import generate_api_key
from app.db.models.subscription import ApiKey
from app.db.models.user import User
from app.services.audit import write_audit

UTC = UTC

router = APIRouter(tags=["api-keys"])


class ApiKeyCreate(BaseModel):
    name: str


@router.get("")
async def list_api_keys(
    user: User = Depends(deps.get_current_user),
    _tier: None = Depends(deps.require_tier("pro")),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """List all active and revoked API keys for the current user."""
    stmt = select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    result = await db.execute(stmt)
    keys = result.scalars().all()

    return {
        "data": [
            {
                "id": str(k.id),
                "name": k.name,
                "key_prefix": k.key_prefix,
                "created_at": k.created_at.isoformat(),
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
            }
            for k in keys
        ]
    }


@router.post("")
async def create_api_key(
    payload: ApiKeyCreate,
    request: Request,
    user: User = Depends(deps.get_current_user),
    _tier: None = Depends(deps.require_tier("pro")),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Generate a new Developer API Key for integrations."""
    # Enforce limit of 5 keys per user for safety
    stmt = select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.revoked_at == None)  # noqa
    result = await db.execute(stmt)
    active_keys = result.scalars().all()

    if len(active_keys) >= 5:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Maximum limit of 5 active API keys reached."
        )

    raw_key, key_hash = generate_api_key()

    # Store just the hash and a visual prefix
    key_prefix = raw_key[:8] + "..."

    new_key = ApiKey(
        user_id=user.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=payload.name,
    )
    db.add(new_key)
    await write_audit(db, user.id, "api_key_created", request, {"name": payload.name})
    await db.commit()

    return {
        "id": str(new_key.id),
        "name": new_key.name,
        "key_prefix": new_key.key_prefix,
        "raw_key": raw_key,
        "message": "Store this raw_key securely. It will never be shown again.",
    }


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: UUID,
    request: Request,
    user: User = Depends(deps.get_current_user),
    _tier: None = Depends(deps.require_tier("pro")),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Revoke an API key without deleting its audit history."""
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id))
    key = result.scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found.")

    key.revoked_at = datetime.now(UTC)
    await write_audit(db, user.id, "api_key_revoked", request, {"key_prefix": key.key_prefix})
    await db.commit()
    return {"status": "success"}

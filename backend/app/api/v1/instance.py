from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["instance"])


@router.get("")
async def instance_info() -> dict:
    """Return public configuration metadata for this deployment.

    Called by the frontend on boot to adapt its UI (hide billing, unlock
    features, display the correct mode badge, etc.). No authentication
    required — all values are intentionally non-sensitive.
    """
    return {
        "deployment_mode": settings.DEPLOYMENT_MODE,
        "billing_enabled": settings.DEPLOYMENT_MODE == "cloud",
        "max_users": settings.MAX_USERS,
        "storage_backend": settings.STORAGE_BACKEND,
        "version": "0.1.0",
    }

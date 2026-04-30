from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    activities,
    api_keys,
    auth,
    billing,
    connections,
    instance,
    pipelines,
    rules,
    sync,
    webhooks,
)

router = APIRouter()

router.include_router(auth.router, prefix="/auth")
router.include_router(sync.router, prefix="/sync")
router.include_router(activities.router, prefix="/activities")
router.include_router(billing.router, prefix="/billing")
router.include_router(webhooks.router, prefix="/webhooks")
router.include_router(api_keys.router, prefix="/api-keys")
router.include_router(rules.router, prefix="/rules")
router.include_router(connections.router, prefix="/connections")
router.include_router(pipelines.router, prefix="/pipelines")
router.include_router(instance.router, prefix="/instance")

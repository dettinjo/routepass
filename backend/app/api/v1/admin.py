"""Admin API for the API-management registry and economic governor (Phase 1).

Read + edit the provider policies, Strava app pool (capacity/cost) and governor
config. Gated by require_admin. Nothing here enforces limits yet — later phases wire
the registry into the limiter/scheduler/governor. See RATE_LIMIT_ARCHITECTURE.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core import security
from app.core.config import settings
from app.db.models.governance import GovernorConfig, ProviderPolicy
from app.db.models.user import StravaApp, User

router = APIRouter(tags=["admin"])


# ── Providers ────────────────────────────────────────────────────────────────

_PROVIDER_FIELDS = (
    "platform",
    "role",
    "auth_type",
    "supports_webhooks",
    "enabled",
    "default_poll_min",
    "min_poll_min",
    "window_seconds",
    "window_limit",
    "daily_limit",
    "read_limit_15min",
    "read_limit_daily",
    "overall_limit_15min",
    "overall_limit_daily",
    "athlete_capacity",
    "monthly_cost_cents",
    "initial_backfill_limit",
    "page_size",
    "refresh_strategy",
    "headroom_pct",
    "free_reserve_pct",
)


class ProviderPolicyUpdate(BaseModel):
    enabled: bool | None = None
    role: str | None = None
    auth_type: str | None = None
    supports_webhooks: bool | None = None
    default_poll_min: int | None = None
    min_poll_min: int | None = None
    window_seconds: int | None = None
    window_limit: int | None = None
    daily_limit: int | None = None
    read_limit_15min: int | None = None
    read_limit_daily: int | None = None
    overall_limit_15min: int | None = None
    overall_limit_daily: int | None = None
    athlete_capacity: int | None = None
    monthly_cost_cents: int | None = None
    initial_backfill_limit: int | None = None
    page_size: int | None = None
    refresh_strategy: str | None = None
    headroom_pct: int | None = None
    free_reserve_pct: int | None = None


def _serialize_provider(p: ProviderPolicy) -> dict:
    out = {f: getattr(p, f) for f in _PROVIDER_FIELDS}
    out["id"] = str(p.id)
    out["updated_at"] = p.updated_at.isoformat()
    return out


@router.get("/providers")
async def list_providers(
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
) -> list[dict]:
    result = await db.execute(select(ProviderPolicy).order_by(ProviderPolicy.platform))
    return [_serialize_provider(p) for p in result.scalars().all()]


@router.patch("/providers/{platform}")
async def update_provider(
    platform: str,
    body: ProviderPolicyUpdate,
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    result = await db.execute(select(ProviderPolicy).where(ProviderPolicy.platform == platform))
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown provider: {platform}")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)
    await db.commit()
    await db.refresh(policy)
    await _invalidate_governor_state(db)
    return _serialize_provider(policy)


# ── Governor config ──────────────────────────────────────────────────────────


class GovernorConfigUpdate(BaseModel):
    coverage_target_pct: int | None = None
    paid_reservation_pct: int | None = None
    free_degradation_enabled: bool | None = None
    infra_monthly_cost_cents: int | None = None


def _serialize_governor(g: GovernorConfig) -> dict:
    return {
        "coverage_target_pct": g.coverage_target_pct,
        "paid_reservation_pct": g.paid_reservation_pct,
        "free_degradation_enabled": g.free_degradation_enabled,
        "infra_monthly_cost_cents": g.infra_monthly_cost_cents,
        "updated_at": g.updated_at.isoformat(),
    }


async def _get_or_create_governor(db: AsyncSession) -> GovernorConfig:
    result = await db.execute(select(GovernorConfig).where(GovernorConfig.id == 1))
    g = result.scalar_one_or_none()
    if g is None:
        g = GovernorConfig(id=1)
        db.add(g)
        await db.commit()
        await db.refresh(g)
    return g


@router.get("/governor")
async def get_governor(
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    return _serialize_governor(await _get_or_create_governor(db))


@router.patch("/governor")
async def update_governor(
    body: GovernorConfigUpdate,
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    g = await _get_or_create_governor(db)
    for field, value in body.model_dump(exclude_unset=True).items():
        if field.endswith("_pct") and value is not None and not (0 <= value <= 100):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} must be between 0 and 100."
            )
        setattr(g, field, value)
    await db.commit()
    await db.refresh(g)
    await _invalidate_governor_state(db)
    return _serialize_governor(g)


async def _invalidate_governor_state(db: AsyncSession) -> None:
    """Force the next read to recompute rather than serve a stale cached state."""
    from app.core.governor import refresh_state

    await refresh_state(db)


@router.get("/governor/state")
async def get_governor_state(
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Live economic-governor state: cost vs revenue, Strava slot occupancy, and the
    resulting free-tier degradation level. See RATE_LIMIT_ARCHITECTURE.md §6."""
    from app.core.governor import get_state

    return (await get_state(db)).to_dict()


@router.post("/governor/state/recompute")
async def recompute_governor_state(
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Force an immediate recompute (bypassing the 10-min cache) after a config or
    Strava-app-pool change the admin wants to see reflected right away."""
    from app.core.governor import refresh_state

    return (await refresh_state(db)).to_dict()


# ── Strava app pool ──────────────────────────────────────────────────────────


class StravaAppCreate(BaseModel):
    client_id: str
    client_secret: str
    display_name: str
    athlete_cap: int = 10
    monthly_cost_cents: int = 1199


class StravaAppUpdate(BaseModel):
    display_name: str | None = None
    is_active: bool | None = None
    athlete_cap: int | None = None
    monthly_cost_cents: int | None = None


def _serialize_app(a: StravaApp) -> dict:
    # Never expose client_secret.
    return {
        "id": a.id,
        "client_id": a.client_id,
        "display_name": a.display_name,
        "is_active": a.is_active,
        "athlete_cap": a.athlete_cap,
        "monthly_cost_cents": a.monthly_cost_cents,
        "read_limit_15min": a.read_limit_15min,
        "read_limit_daily": a.read_limit_daily,
        "overall_limit_15min": a.overall_limit_15min,
        "overall_limit_daily": a.overall_limit_daily,
    }


@router.get("/strava-apps")
async def list_strava_apps(
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
) -> list[dict]:
    result = await db.execute(select(StravaApp).order_by(StravaApp.id))
    return [_serialize_app(a) for a in result.scalars().all()]


@router.post("/strava-apps", status_code=status.HTTP_201_CREATED)
async def create_strava_app(
    body: StravaAppCreate,
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    app_entry = StravaApp(
        client_id=body.client_id,
        client_secret=security.encrypt(body.client_secret),
        display_name=body.display_name,
        is_active=True,
        athlete_cap=body.athlete_cap,
        monthly_cost_cents=body.monthly_cost_cents,
    )
    db.add(app_entry)
    await db.commit()
    await db.refresh(app_entry)
    await _invalidate_governor_state(db)
    return _serialize_app(app_entry)


@router.patch("/strava-apps/{app_id}")
async def update_strava_app(
    app_id: int,
    body: StravaAppUpdate,
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    result = await db.execute(select(StravaApp).where(StravaApp.id == app_id))
    app_entry = result.scalar_one_or_none()
    if app_entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strava app not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(app_entry, field, value)
    await db.commit()
    await db.refresh(app_entry)
    await _invalidate_governor_state(db)
    return _serialize_app(app_entry)


# ── Economics snapshot (read-only; full governor lands in a later phase) ───────


@router.get("/usage/user/{user_id}")
async def user_usage(
    user_id: str,
    _: User = Depends(deps.require_admin),
    redis=Depends(deps.get_redis),
) -> dict:
    """Today's per-user Strava request usage (overall + read) recorded by the limiter."""
    from datetime import datetime

    date_key = datetime.now(deps.UTC).strftime("%Y-%m-%d")
    overall = int(await redis.get(f"usage:strava:user:{user_id}:overall:{date_key}") or 0)
    read = int(await redis.get(f"usage:strava:user:{user_id}:read:{date_key}") or 0)
    return {
        "user_id": user_id,
        "date": date_key,
        "strava": {"overall": overall, "read": read, "writes": overall - read},
    }


@router.get("/metrics/overview")
async def metrics_overview(
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Cost/capacity snapshot from the registry. Live usage + revenue arrive with the
    governor phase; for now this reports configured capacity and cost."""
    from app.db.models.subscription import Subscription

    apps = (await db.execute(select(StravaApp).where(StravaApp.is_active == True))).scalars().all()  # noqa: E712
    monthly_cost_cents = sum(a.monthly_cost_cents for a in apps)
    strava_athlete_capacity = sum(a.athlete_cap for a in apps)

    governor = await _get_or_create_governor(db)
    monthly_cost_cents += governor.infra_monthly_cost_cents

    paid = (
        (
            await db.execute(
                select(Subscription).where(
                    Subscription.tier != "free", Subscription.status == "active"
                )
            )
        )
        .scalars()
        .all()
    )

    return {
        "self_hosted": settings.DEPLOYMENT_MODE == "selfhosted",
        "monthly_cost_cents": monthly_cost_cents,
        "strava": {
            "active_apps": len(apps),
            "athlete_capacity": strava_athlete_capacity,
        },
        "paid_subscriptions": len(paid),
        "coverage_target_pct": governor.coverage_target_pct,
        "paid_reservation_pct": governor.paid_reservation_pct,
    }

"""Admin API for the API-management registry and economic governor (Phase 1).

Read + edit the provider policies, Strava app pool (capacity/cost) and governor
config. Gated by require_admin. Nothing here enforces limits yet — later phases wire
the registry into the limiter/scheduler/governor. See RATE_LIMIT_ARCHITECTURE.md.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core import security
from app.core.config import settings
from app.db.models.governance import GovernorConfig, ProviderPolicy
from app.db.models.user import StravaApp, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


async def _usage_count(redis, key: str) -> int:
    """Read a usage counter, degrading to 0 if Redis is unavailable rather than
    failing the whole dashboard request over a non-critical stat."""
    try:
        return int(await redis.get(key) or 0)
    except Exception as exc:
        logger.warning("admin: usage counter read failed for %s: %s", key, exc)
        return 0


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
    overall = await _usage_count(redis, f"usage:strava:user:{user_id}:overall:{date_key}")
    read = await _usage_count(redis, f"usage:strava:user:{user_id}:read:{date_key}")
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


# ── Revenue (real MRR, from Stripe-backed subscriptions) ────────────────────────


@router.get("/metrics/revenue")
async def metrics_revenue(
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Real monthly-recurring-revenue estimate + a breakdown by plan.

    Reuses the governor's conservative revenue estimate (same number the
    degradation ladder acts on) so the dashboard and the enforcement logic never
    disagree about "how much revenue do we have".
    """
    from app.core.governor import get_state
    from app.core.tiers import PLANS, stripe_price_for
    from app.db.models.subscription import Subscription

    state = await get_state(db)

    subs = (
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

    price_to_plan = {
        stripe_price_for(plan): plan.id
        for plan in PLANS.values()
        if plan.id != "free" and stripe_price_for(plan)
    }
    breakdown: dict[str, int] = {}
    for sub in subs:
        plan_id = price_to_plan.get(sub.stripe_price_id or "") or (
            "lifetime" if sub.tier == "lifetime" else "pro_annual"
        )
        breakdown[plan_id] = breakdown.get(plan_id, 0) + 1

    return {
        "monthly_revenue_cents": state.monthly_revenue_cents,
        "active_paid_subscriptions": len(subs),
        "breakdown_by_plan": breakdown,
    }


# ── Users ────────────────────────────────────────────────────────────────────


def _serialize_user_row(
    user: User,
    tier: str | None,
    sub_status: str | None,
    conn_count: int,
    error_conn_count: int,
    strava_requests_today: int,
) -> dict:
    from app.core.tiers import is_comp_email

    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "tier": tier or "free",
        "subscription_status": sub_status,
        "is_admin": user.is_admin,
        "is_comp": is_comp_email(user.email),
        "created_at": user.created_at.isoformat(),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "connections_count": conn_count,
        "error_connections_count": error_conn_count,
        "strava_requests_today": strava_requests_today,
    }


@router.get("/users")
async def list_users(
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
    redis=Depends(deps.get_redis),
) -> dict:
    """Paginated user list with connection health and today's Strava usage."""
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from app.db.models.connection import Connection as ConnectionModel
    from app.db.models.subscription import Subscription

    limit = max(1, min(limit, 200))

    base_stmt = select(User)
    if search:
        base_stmt = base_stmt.where(User.email.ilike(f"%{search}%"))

    total = (await db.execute(select(func.count()).select_from(base_stmt.subquery()))).scalar() or 0

    users = (
        (await db.execute(base_stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )

    if not users:
        return {"total": total, "limit": limit, "offset": offset, "users": []}

    user_ids = [u.id for u in users]

    subs = (
        (await db.execute(select(Subscription).where(Subscription.user_id.in_(user_ids))))
        .scalars()
        .all()
    )
    sub_by_user = {s.user_id: s for s in subs}

    conn_rows = (
        await db.execute(
            select(ConnectionModel.user_id, ConnectionModel.status).where(
                ConnectionModel.user_id.in_(user_ids)
            )
        )
    ).all()
    conn_count: dict = {}
    error_count: dict = {}
    for uid, conn_status in conn_rows:
        conn_count[uid] = conn_count.get(uid, 0) + 1
        if conn_status == "error":
            error_count[uid] = error_count.get(uid, 0) + 1

    date_key = _dt.now(_UTC).strftime("%Y-%m-%d")
    result_users = []
    for u in users:
        sub = sub_by_user.get(u.id)
        usage = await _usage_count(redis, f"usage:strava:user:{u.id}:overall:{date_key}")
        result_users.append(
            _serialize_user_row(
                u,
                sub.tier if sub else None,
                sub.status if sub else None,
                conn_count.get(u.id, 0),
                error_count.get(u.id, 0),
                usage,
            )
        )

    return {"total": total, "limit": limit, "offset": offset, "users": result_users}


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: UUID,
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
    redis=Depends(deps.get_redis),
) -> dict:
    """Per-user rate insight: connections, recent jobs, and today's usage per
    provider — the drill-down behind the users table."""
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from app.core.polling import effective_poll_interval_min
    from app.core.tiers import is_comp_email
    from app.db.models.connection import Connection as ConnectionModel
    from app.db.models.subscription import Subscription
    from app.db.models.sync import ConnectionSyncState, JobAuditLog

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    sub = (
        await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    ).scalar_one_or_none()

    conn_rows = (
        await db.execute(
            select(
                ConnectionModel, ConnectionSyncState.last_error, ConnectionSyncState.last_synced_at
            )
            .outerjoin(ConnectionSyncState, ConnectionSyncState.connection_id == ConnectionModel.id)
            .where(ConnectionModel.user_id == user_id)
        )
    ).all()

    connections = []
    for conn, last_error, last_synced_at in conn_rows:
        connections.append(
            {
                "id": str(conn.id),
                "platform": conn.platform,
                "status": conn.status,
                "display_name": conn.display_name,
                "last_error": last_error,
                "last_synced_at": last_synced_at.isoformat() if last_synced_at else None,
                "poll_interval_effective_min": effective_poll_interval_min(
                    conn.platform, conn.poll_interval_min
                ),
            }
        )

    jobs = (
        (
            await db.execute(
                select(JobAuditLog)
                .where(JobAuditLog.user_id == user_id)
                .order_by(JobAuditLog.enqueued_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    recent_jobs = [
        {
            "job_type": j.job_type,
            "status": j.status,
            "error_message": j.error_message,
            "enqueued_at": j.enqueued_at.isoformat() if j.enqueued_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        }
        for j in jobs
    ]

    date_key = _dt.now(_UTC).strftime("%Y-%m-%d")
    usage_today = {}
    for platform in ("strava", "intervals_icu", "runalyze"):
        usage_today[platform] = await _usage_count(
            redis, f"usage:{platform}:user:{user_id}:overall:{date_key}"
        )

    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "is_admin": user.is_admin,
        "is_comp": is_comp_email(user.email),
        "created_at": user.created_at.isoformat(),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "tier": sub.tier if sub else "free",
        "subscription_status": sub.status if sub else None,
        "stripe_customer_id": sub.stripe_customer_id if sub else None,
        "connections": connections,
        "recent_jobs": recent_jobs,
        "usage_today": usage_today,
    }


# ── Alerts ───────────────────────────────────────────────────────────────────


@router.get("/alerts")
async def list_alerts(
    _: User = Depends(deps.require_admin),
    db: AsyncSession = Depends(deps.get_db),
) -> list[dict]:
    """Computed alert list surfaced on the Overview tab."""
    from app.core.governor import (
        LEVEL_DEFERRED,
        LEVEL_PAUSED,
        LEVEL_SOFT_THROTTLE,
        get_state,
    )
    from app.db.models.connection import Connection as ConnectionModel

    alerts: list[dict] = []
    state = await get_state(db)

    if not state.self_hosted:
        if state.economic_level >= LEVEL_PAUSED:
            cost = state.monthly_cost_cents / 100
            revenue = state.monthly_revenue_cents / 100
            alerts.append(
                {
                    "severity": "critical",
                    "message": (
                        f"Free-tier syncing is paused: cost (${cost:.2f}) far exceeds "
                        f"revenue (${revenue:.2f})."
                    ),
                }
            )
        elif state.economic_level >= LEVEL_DEFERRED:
            alerts.append(
                {
                    "severity": "warning",
                    "message": "Free-tier syncing is deferred — cost is approaching revenue.",
                }
            )
        elif state.economic_level >= LEVEL_SOFT_THROTTLE:
            alerts.append(
                {
                    "severity": "info",
                    "message": "Free-tier poll intervals are stretched (soft throttle).",
                }
            )

        if not state.strava_admission_open:
            alerts.append(
                {
                    "severity": "warning",
                    "message": (
                        f"Strava free slots are full "
                        f"({state.strava_free_slots_used}/{state.strava_free_capacity_slots}) — "
                        "new free connections are waitlisted."
                    ),
                }
            )
        elif state.strava_free_capacity_slots and (
            state.strava_free_slots_used / state.strava_free_capacity_slots > 0.8
        ):
            alerts.append({"severity": "info", "message": "Strava free slots are over 80% full."})

    error_count = (
        await db.execute(
            select(func.count())
            .select_from(ConnectionModel)
            .where(ConnectionModel.status == "error")
        )
    ).scalar() or 0
    if error_count > 0:
        alerts.append(
            {
                "severity": "warning",
                "message": f"{error_count} connection(s) are currently in an error state.",
            }
        )

    if not alerts:
        alerts.append({"severity": "ok", "message": "No active alerts."})

    return alerts

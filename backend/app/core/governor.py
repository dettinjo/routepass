"""Economic governor: turns cost + capacity + revenue into a free-tier policy.

Reads the registry (strava_apps, provider_policy, governor_config) and active
subscriptions to compute a GovernorState, cached in Redis and recomputed on a
cron + on demand. Two invariants (see RATE_LIMIT_ARCHITECTURE.md):

- Provisioning invariant: cost is compared against revenue * coverage_target_pct.
- Allocation invariant: free-tier Strava connections are only admitted while free
  slot headroom remains after the paid reservation.

Self-hosted instances always get the "unlimited" state — no revenue accounting,
no degradation, no admission control.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tiers import PLANS, stripe_price_for

UTC = UTC
logger = logging.getLogger(__name__)

_STATE_CACHE_KEY = "routepass:governor:state"
_STATE_CACHE_TTL = 600  # 10 min; matches the recompute cron cadence

# A one-time (lifetime) purchase is amortized over this many months for the
# governor's monthly revenue estimate.
LIFETIME_AMORTIZATION_MONTHS = 24

# Degradation ladder (see RATE_LIMIT_ARCHITECTURE.md §6.1).
LEVEL_NORMAL = 0
LEVEL_SOFT_THROTTLE = 1
LEVEL_DEFERRED = 2
LEVEL_ADMISSION_FREEZE = 3
LEVEL_PAUSED = 4

# Poll-interval multiplier applied to free-tier users at each level.
# None means "do not poll at all" (existing data stays visible; live sync paused).
_POLL_MULTIPLIER: dict[int, int | None] = {
    LEVEL_NORMAL: 1,
    LEVEL_SOFT_THROTTLE: 3,
    LEVEL_DEFERRED: 12,
    LEVEL_ADMISSION_FREEZE: 12,
    LEVEL_PAUSED: None,
}


@dataclass
class _DefaultGovernorConfig:
    """Fallback used when no GovernorConfig row exists yet (mirrors model defaults)."""

    coverage_target_pct: int = 70
    paid_reservation_pct: int = 40
    free_degradation_enabled: bool = True
    infra_monthly_cost_cents: int = 0


_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


@dataclass
class GovernorState:
    self_hosted: bool
    monthly_cost_cents: int
    monthly_revenue_cents: int
    coverage_target_pct: int
    paid_reservation_pct: int
    free_degradation_enabled: bool
    economic_level: int
    strava_total_slots: int
    strava_reserved_paid_slots: int
    strava_free_capacity_slots: int
    strava_free_slots_used: int
    strava_admission_open: bool
    free_tier_level: int
    computed_at: str

    def poll_multiplier(self) -> int | None:
        """Multiplier applied to a free-tier connection's poll interval, or None to
        skip polling entirely (paused)."""
        return _POLL_MULTIPLIER.get(self.free_tier_level, 1)

    def to_dict(self) -> dict:
        return asdict(self)


def _unlimited_state() -> GovernorState:
    now = datetime.now(UTC).isoformat()
    return GovernorState(
        self_hosted=True,
        monthly_cost_cents=0,
        monthly_revenue_cents=0,
        coverage_target_pct=100,
        paid_reservation_pct=0,
        free_degradation_enabled=False,
        economic_level=LEVEL_NORMAL,
        strava_total_slots=0,
        strava_reserved_paid_slots=0,
        strava_free_capacity_slots=0,
        strava_free_slots_used=0,
        strava_admission_open=True,
        free_tier_level=LEVEL_NORMAL,
        computed_at=now,
    )


def _monthly_equivalent_cents(plan_id: str) -> int:
    plan = PLANS.get(plan_id)
    if plan is None:
        return 0
    if plan.interval == "month":
        return plan.amount_cents
    if plan.interval == "year":
        return plan.amount_cents // 12
    if plan.interval == "once":
        return plan.amount_cents // LIFETIME_AMORTIZATION_MONTHS
    return 0


async def _estimate_revenue_cents(db: AsyncSession) -> int:
    """Conservative monthly-equivalent revenue across active paid subscriptions.

    Matches stripe_price_id back to a plan when possible; otherwise falls back to
    the tier's plan estimate. Never over-estimates, so the provisioning invariant
    stays safe even without exact Stripe price bookkeeping.
    """
    from app.db.models.subscription import Subscription

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

    total = 0
    for sub in subs:
        plan_id = price_to_plan.get(sub.stripe_price_id or "")
        if plan_id is None:
            plan_id = "lifetime" if sub.tier == "lifetime" else "pro_annual"
        total += _monthly_equivalent_cents(plan_id)
    return total


async def _cost_and_slot_capacity(db: AsyncSession) -> tuple[int, int, object]:
    from app.db.models.governance import GovernorConfig
    from app.db.models.user import StravaApp

    apps = (
        (
            await db.execute(select(StravaApp).where(StravaApp.is_active == True))  # noqa: E712
        )
        .scalars()
        .all()
    )
    strava_cost_cents = sum(a.monthly_cost_cents for a in apps)
    total_slots = sum(a.athlete_cap for a in apps)

    governor_cfg = (
        await db.execute(select(GovernorConfig).where(GovernorConfig.id == 1))
    ).scalar_one_or_none()
    if governor_cfg is None:
        # No row yet (registry not seeded, e.g. in a test DB) — use the same
        # defaults as the GovernorConfig model/migration, unpersisted.
        governor_cfg = _DefaultGovernorConfig()

    monthly_cost_cents = strava_cost_cents + governor_cfg.infra_monthly_cost_cents
    return monthly_cost_cents, total_slots, governor_cfg


async def _strava_slot_usage(db: AsyncSession) -> tuple[int, int]:
    """Return (total_slots_used, free_tier_slots_used) across all connected Strava athletes."""
    from app.db.models.subscription import Subscription
    from app.db.models.user import StravaToken, User

    rows = (
        await db.execute(
            select(User.id, Subscription.tier)
            .join(StravaToken, StravaToken.user_id == User.id)
            .outerjoin(Subscription, Subscription.user_id == User.id)
        )
    ).all()
    total_used = len(rows)
    free_used = sum(1 for _, tier in rows if not tier or tier == "free")
    return total_used, free_used


async def compute_state(db: AsyncSession) -> GovernorState:
    """Recompute the governor state from the registry + subscriptions (no cache)."""
    if settings.DEPLOYMENT_MODE == "selfhosted":
        return _unlimited_state()

    monthly_cost_cents, total_slots, governor_cfg = await _cost_and_slot_capacity(db)
    monthly_revenue_cents = await _estimate_revenue_cents(db)
    _total_used, free_used = await _strava_slot_usage(db)

    reserved_paid_slots = int(total_slots * governor_cfg.paid_reservation_pct / 100)
    free_capacity_slots = max(total_slots - reserved_paid_slots, 0)
    admission_open = not governor_cfg.free_degradation_enabled or free_used < free_capacity_slots

    if not governor_cfg.free_degradation_enabled:
        economic_level = LEVEL_NORMAL
    else:
        covered_revenue = monthly_revenue_cents * governor_cfg.coverage_target_pct / 100
        if monthly_cost_cents <= covered_revenue:
            economic_level = LEVEL_NORMAL
        elif monthly_cost_cents <= monthly_revenue_cents:
            economic_level = LEVEL_SOFT_THROTTLE
        elif monthly_cost_cents <= monthly_revenue_cents * 1.3:
            economic_level = LEVEL_DEFERRED
        else:
            economic_level = LEVEL_PAUSED

    free_tier_level = economic_level
    if not admission_open and free_tier_level < LEVEL_ADMISSION_FREEZE:
        free_tier_level = LEVEL_ADMISSION_FREEZE

    return GovernorState(
        self_hosted=False,
        monthly_cost_cents=monthly_cost_cents,
        monthly_revenue_cents=monthly_revenue_cents,
        coverage_target_pct=governor_cfg.coverage_target_pct,
        paid_reservation_pct=governor_cfg.paid_reservation_pct,
        free_degradation_enabled=governor_cfg.free_degradation_enabled,
        economic_level=economic_level,
        strava_total_slots=total_slots,
        strava_reserved_paid_slots=reserved_paid_slots,
        strava_free_capacity_slots=free_capacity_slots,
        strava_free_slots_used=free_used,
        strava_admission_open=admission_open,
        free_tier_level=free_tier_level,
        computed_at=datetime.now(UTC).isoformat(),
    )


async def refresh_state(db: AsyncSession) -> GovernorState:
    """Recompute and cache the governor state. Called by the cron + admin endpoint."""
    state = await compute_state(db)
    try:
        r = _get_redis()
        await r.set(_STATE_CACHE_KEY, json.dumps(state.to_dict()), ex=_STATE_CACHE_TTL)
    except Exception as exc:
        logger.warning("Governor: failed to cache state: %s", exc)
    return state


async def get_state(db: AsyncSession) -> GovernorState:
    """Return the cached governor state, computing (and caching) it on a miss."""
    if settings.DEPLOYMENT_MODE == "selfhosted":
        return _unlimited_state()

    try:
        r = _get_redis()
        cached = await r.get(_STATE_CACHE_KEY)
        if cached:
            return GovernorState(**json.loads(cached))
    except Exception as exc:
        logger.warning("Governor: cache read failed, recomputing: %s", exc)

    return await refresh_state(db)

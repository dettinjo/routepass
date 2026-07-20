from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import governor
from app.db.models.governance import GovernorConfig
from app.db.models.subscription import Subscription
from app.db.models.user import StravaApp, StravaToken, User


async def _make_user(db: AsyncSession, email: str, tier: str | None) -> User:
    user = User(email=email, is_active=True)
    db.add(user)
    await db.flush()
    if tier is not None:
        db.add(Subscription(user_id=user.id, tier=tier, status="active"))
    await db.commit()
    return user


async def _make_strava_token(db: AsyncSession, user: User, app: StravaApp) -> None:
    db.add(
        StravaToken(
            user_id=user.id,
            strava_app_id=app.id,
            strava_athlete_id=hash(user.email) % 1_000_000,
            access_token=b"enc",
            refresh_token=b"enc",
            expires_at=datetime.now(UTC),
            connected_at=datetime.now(UTC),
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_self_hosted_is_always_unlimited(db: AsyncSession):
    with patch("app.core.governor.settings.DEPLOYMENT_MODE", "selfhosted"):
        state = await governor.compute_state(db)
    assert state.self_hosted is True
    assert state.strava_admission_open is True
    assert state.free_tier_level == governor.LEVEL_NORMAL
    assert state.poll_multiplier() == 1


@pytest.mark.asyncio
async def test_no_apps_no_revenue_is_normal_not_division_error(db: AsyncSession):
    """Zero apps and zero revenue must not crash — cost is 0, so it's trivially covered."""
    with patch("app.core.governor.settings.DEPLOYMENT_MODE", "cloud"):
        state = await governor.compute_state(db)
    assert state.monthly_cost_cents == 0
    assert state.monthly_revenue_cents == 0
    assert state.economic_level == governor.LEVEL_NORMAL
    # No slots at all → no free headroom → admission closed.
    assert state.strava_admission_open is False
    assert state.free_tier_level == governor.LEVEL_ADMISSION_FREEZE


@pytest.mark.asyncio
async def test_economic_levels_scale_with_cost_vs_revenue(db: AsyncSession):
    db.add(
        GovernorConfig(
            id=1,
            coverage_target_pct=70,
            paid_reservation_pct=0,
            free_degradation_enabled=True,
            infra_monthly_cost_cents=0,
        )
    )
    db.add(
        StravaApp(
            client_id="1",
            client_secret=b"e",
            display_name="A",
            is_active=True,
            athlete_cap=100,
            monthly_cost_cents=1000,
        )
    )
    await db.commit()

    async def revenue(_db, cents):
        with patch("app.core.governor._estimate_revenue_cents", return_value=cents):
            with patch("app.core.governor.settings.DEPLOYMENT_MODE", "cloud"):
                return await governor.compute_state(_db)

    # cost=1000. covered_revenue = revenue*0.7. revenue=2000 -> covered=1400 >= cost -> NORMAL
    assert (await revenue(db, 2000)).economic_level == governor.LEVEL_NORMAL
    # revenue=1200 -> covered=840 < 1000 <= 1200 -> SOFT_THROTTLE
    assert (await revenue(db, 1200)).economic_level == governor.LEVEL_SOFT_THROTTLE
    # revenue=800 -> covered=560; cost(1000) <= revenue*1.3(1040) -> DEFERRED
    assert (await revenue(db, 800)).economic_level == governor.LEVEL_DEFERRED
    # revenue=100 -> cost(1000) > revenue*1.3(130) -> PAUSED
    assert (await revenue(db, 100)).economic_level == governor.LEVEL_PAUSED


@pytest.mark.asyncio
async def test_admission_reserves_paid_slots(db: AsyncSession):
    db.add(
        GovernorConfig(
            id=1,
            coverage_target_pct=70,
            paid_reservation_pct=50,
            free_degradation_enabled=True,
            infra_monthly_cost_cents=0,
        )
    )
    app = StravaApp(
        client_id="1",
        client_secret=b"e",
        display_name="A",
        is_active=True,
        athlete_cap=10,
        monthly_cost_cents=0,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    free_user = await _make_user(db, "free1@test.com", "free")
    await _make_strava_token(db, free_user, app)

    with patch("app.core.governor.settings.DEPLOYMENT_MODE", "cloud"):
        state = await governor.compute_state(db)

    # 10 slots, 50% reserved for paid -> 5 free capacity; 1 free user connected -> still open.
    assert state.strava_total_slots == 10
    assert state.strava_reserved_paid_slots == 5
    assert state.strava_free_capacity_slots == 5
    assert state.strava_free_slots_used == 1
    assert state.strava_admission_open is True

    # Fill the remaining 4 free slots -> exactly at capacity -> closed.
    for i in range(4):
        u = await _make_user(db, f"free{i + 2}@test.com", "free")
        await _make_strava_token(db, u, app)

    with patch("app.core.governor.settings.DEPLOYMENT_MODE", "cloud"):
        state2 = await governor.compute_state(db)
    assert state2.strava_free_slots_used == 5
    assert state2.strava_admission_open is False
    assert state2.free_tier_level == governor.LEVEL_ADMISSION_FREEZE


@pytest.mark.asyncio
async def test_paid_users_dont_count_against_free_capacity(db: AsyncSession):
    db.add(
        GovernorConfig(
            id=1,
            coverage_target_pct=70,
            paid_reservation_pct=50,
            free_degradation_enabled=True,
            infra_monthly_cost_cents=0,
        )
    )
    app = StravaApp(
        client_id="1",
        client_secret=b"e",
        display_name="A",
        is_active=True,
        athlete_cap=10,
        monthly_cost_cents=0,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    for i in range(5):
        u = await _make_user(db, f"pro{i}@test.com", "pro")
        await _make_strava_token(db, u, app)

    with patch("app.core.governor.settings.DEPLOYMENT_MODE", "cloud"):
        state = await governor.compute_state(db)

    assert state.strava_free_slots_used == 0
    assert state.strava_admission_open is True  # free capacity untouched by paid users


@pytest.mark.asyncio
async def test_degradation_disabled_is_always_normal_and_open(db: AsyncSession):
    db.add(
        GovernorConfig(
            id=1,
            coverage_target_pct=70,
            paid_reservation_pct=100,
            free_degradation_enabled=False,
            infra_monthly_cost_cents=0,
        )
    )
    db.add(
        StravaApp(
            client_id="1",
            client_secret=b"e",
            display_name="A",
            is_active=True,
            athlete_cap=1,
            monthly_cost_cents=100_000,
        )
    )
    await db.commit()

    with patch("app.core.governor.settings.DEPLOYMENT_MODE", "cloud"):
        state = await governor.compute_state(db)
    assert state.economic_level == governor.LEVEL_NORMAL
    assert state.strava_admission_open is True
    assert state.free_tier_level == governor.LEVEL_NORMAL


def test_poll_multiplier_table():
    from app.core.governor import GovernorState

    def state_at(level: int) -> GovernorState:
        return GovernorState(
            self_hosted=False,
            monthly_cost_cents=0,
            monthly_revenue_cents=0,
            coverage_target_pct=70,
            paid_reservation_pct=40,
            free_degradation_enabled=True,
            economic_level=level,
            strava_total_slots=0,
            strava_reserved_paid_slots=0,
            strava_free_capacity_slots=0,
            strava_free_slots_used=0,
            strava_admission_open=True,
            free_tier_level=level,
            computed_at="2026-01-01T00:00:00+00:00",
        )

    assert state_at(governor.LEVEL_NORMAL).poll_multiplier() == 1
    assert state_at(governor.LEVEL_SOFT_THROTTLE).poll_multiplier() == 3
    assert state_at(governor.LEVEL_DEFERRED).poll_multiplier() == 12
    assert state_at(governor.LEVEL_PAUSED).poll_multiplier() is None


@pytest.mark.asyncio
async def test_revenue_estimate_uses_plan_fallback_conservatively(db: AsyncSession):
    free = await _make_user(db, "f@test.com", "free")
    pro = await _make_user(db, "p@test.com", "pro")
    lifetime = await _make_user(db, "l@test.com", "lifetime")
    assert free  # free contributes nothing

    revenue = await governor._estimate_revenue_cents(db)
    # pro (no stripe_price_id match) falls back to pro_annual monthly-equivalent (3900//12=325)
    # lifetime falls back to lifetime monthly-equivalent (9900//24=412)
    assert revenue == 325 + 412
    assert pro.id and lifetime.id  # keep references alive for clarity

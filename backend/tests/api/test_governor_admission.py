from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import StravaApp, StravaToken, User


@pytest.mark.asyncio
async def test_strava_login_blocked_when_free_slots_exhausted(
    async_client: AsyncClient, free_user_headers: dict, db: AsyncSession
):
    """A brand-new free user is refused a Strava connection once free slots are full."""
    app = StravaApp(
        client_id="1",
        client_secret=b"enc",
        display_name="A",
        is_active=True,
        athlete_cap=1,
        monthly_cost_cents=1199,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    # Fill the single slot with another free user.
    other = User(email="other-free@test.com", is_active=True)
    db.add(other)
    await db.flush()
    db.add(
        StravaToken(
            user_id=other.id,
            strava_app_id=app.id,
            strava_athlete_id=1,
            access_token=b"e",
            refresh_token=b"e",
            expires_at=datetime.now(UTC),
            connected_at=datetime.now(UTC),
        )
    )
    await db.commit()

    with patch("app.api.v1.auth.settings.DEPLOYMENT_MODE", "cloud"):
        resp = await async_client.get("/api/v1/auth/strava/login", headers=free_user_headers)
    assert resp.status_code == 429
    assert "capacity" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_strava_login_allowed_for_reconnect_even_when_full(
    async_client: AsyncClient, free_user, free_user_headers: dict, db: AsyncSession
):
    """A user who already has a Strava token is reconnecting, not taking a new slot."""
    app = StravaApp(
        client_id="1",
        client_secret=b"enc",
        display_name="A",
        is_active=True,
        athlete_cap=1,
        monthly_cost_cents=1199,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)
    db.add(
        StravaToken(
            user_id=free_user.id,
            strava_app_id=app.id,
            strava_athlete_id=2,
            access_token=b"e",
            refresh_token=b"e",
            expires_at=datetime.now(UTC),
            connected_at=datetime.now(UTC),
        )
    )
    await db.commit()

    with patch("app.api.v1.auth.settings.DEPLOYMENT_MODE", "cloud"):
        resp = await async_client.get("/api/v1/auth/strava/login", headers=free_user_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_strava_login_allowed_for_comp_email_even_when_full(
    async_client: AsyncClient, db: AsyncSession
):
    """Operator-comped accounts never compete for the free Strava slot pool."""
    from app.core import security

    comp_user = User(email="owner@routepass.test", is_active=True)
    db.add(comp_user)
    await db.commit()
    token = security.create_access_token(str(comp_user.id))

    app = StravaApp(
        client_id="1",
        client_secret=b"enc",
        display_name="A",
        is_active=True,
        athlete_cap=1,
        monthly_cost_cents=1199,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)
    other = User(email="other-free@test.com", is_active=True)
    db.add(other)
    await db.flush()
    db.add(
        StravaToken(
            user_id=other.id,
            strava_app_id=app.id,
            strava_athlete_id=3,
            access_token=b"e",
            refresh_token=b"e",
            expires_at=datetime.now(UTC),
            connected_at=datetime.now(UTC),
        )
    )
    await db.commit()

    with (
        patch("app.api.v1.auth.settings.DEPLOYMENT_MODE", "cloud"),
        patch("app.core.tiers.settings.ADMIN_EMAILS", "owner@routepass.test"),
    ):
        resp = await async_client.get(
            "/api/v1/auth/strava/login", headers={"Authorization": f"Bearer {token}"}
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_strava_login_never_blocked_selfhosted(
    async_client: AsyncClient, free_user_headers: dict
):
    """Self-hosted instances never enforce admission control."""
    with patch("app.api.v1.auth.settings.DEPLOYMENT_MODE", "selfhosted"):
        resp = await async_client.get("/api/v1/auth/strava/login", headers=free_user_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_governor_state_endpoint(async_client: AsyncClient, free_user_headers: dict):
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        resp = await async_client.get("/api/v1/admin/governor/state", headers=free_user_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["self_hosted"] is True
    assert body["strava_admission_open"] is True


@pytest.mark.asyncio
async def test_admin_governor_recompute_reflects_new_strava_app(
    async_client: AsyncClient, free_user_headers: dict, db: AsyncSession
):
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        before = await async_client.get("/api/v1/admin/governor/state", headers=free_user_headers)
        assert before.json()["self_hosted"] is True

        recomputed = await async_client.post(
            "/api/v1/admin/governor/state/recompute", headers=free_user_headers
        )
    assert recomputed.status_code == 200
    assert recomputed.json()["self_hosted"] is True

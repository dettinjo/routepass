from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_plans_catalog_public(async_client: AsyncClient):
    with patch("app.core.tiers.settings.STRIPE_SECRET_KEY", ""):
        r = await async_client.get("/api/v1/billing/plans")
    assert r.status_code == 200
    body = r.json()
    assert body["billing_configured"] is False  # Stripe not configured
    plans = {p["id"]: p for p in body["plans"]}
    assert {"pro_monthly", "pro_annual", "lifetime"} <= set(plans)
    assert plans["pro_monthly"]["amount_cents"] == 499
    assert plans["pro_monthly"]["interval"] == "month"
    assert plans["pro_annual"]["amount_cents"] == 3900
    assert plans["lifetime"]["interval"] == "once"


@pytest.mark.asyncio
async def test_comp_email_reports_business_and_gets_admin_in_cloud(
    async_client: AsyncClient, free_user_headers: dict
):
    with (
        patch("app.core.tiers.settings.ADMIN_EMAILS", "free@test.com"),
        patch("app.api.deps.settings.DEPLOYMENT_MODE", "cloud"),
        patch("app.api.v1.auth.settings.DEPLOYMENT_MODE", "cloud"),
    ):
        me = await async_client.get("/api/v1/auth/me", headers=free_user_headers)
        assert me.status_code == 200
        assert me.json()["tier"] == "business"

        admin = await async_client.get("/api/v1/admin/providers", headers=free_user_headers)
        assert admin.status_code == 200  # comped operator is admin


@pytest.mark.asyncio
async def test_non_comp_free_user_forbidden_admin_in_cloud(
    async_client: AsyncClient, free_user_headers: dict
):
    with (
        patch("app.core.tiers.settings.ADMIN_EMAILS", ""),
        patch("app.api.deps.settings.DEPLOYMENT_MODE", "cloud"),
    ):
        r = await async_client.get("/api/v1/admin/providers", headers=free_user_headers)
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_checkout_maps_new_plans(async_client: AsyncClient, free_user_headers: dict):
    with (
        patch("app.api.v1.billing.settings.DEPLOYMENT_MODE", "cloud"),
        patch("app.api.v1.billing.settings.STRIPE_SECRET_KEY", ""),
    ):
        # Valid plan but Stripe unconfigured → 503 (not 400), proving the plan resolved.
        ok = await async_client.post(
            "/api/v1/billing/checkout", json={"plan": "pro_monthly"}, headers=free_user_headers
        )
        assert ok.status_code == 503

        bad = await async_client.post(
            "/api/v1/billing/checkout", json={"plan": "nope"}, headers=free_user_headers
        )
        assert bad.status_code == 400


@pytest.mark.asyncio
async def test_checkout_legacy_tier_still_maps(async_client: AsyncClient, free_user_headers: dict):
    with (
        patch("app.api.v1.billing.settings.DEPLOYMENT_MODE", "cloud"),
        patch("app.api.v1.billing.settings.STRIPE_SECRET_KEY", ""),
    ):
        r = await async_client.post(
            "/api/v1/billing/checkout", json={"tier": "pro"}, headers=free_user_headers
        )
        assert r.status_code == 503  # resolved to pro_annual, then Stripe-unconfigured

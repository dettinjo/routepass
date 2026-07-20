from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.registry import ensure_registry_seeded


@pytest.mark.asyncio
async def test_admin_forbidden_for_non_admin_in_cloud(
    async_client: AsyncClient, free_user_headers: dict
):
    """In cloud mode, a non-admin user is rejected with 403."""
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "cloud"):
        r = await async_client.get("/api/v1/admin/providers", headers=free_user_headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_self_hosted_user_is_admin_and_registry_seeded(
    async_client: AsyncClient, free_user_headers: dict, db: AsyncSession
):
    """Self-hosted owner has admin access; the seeded registry has all providers."""
    await ensure_registry_seeded(db)
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        r = await async_client.get("/api/v1/admin/providers", headers=free_user_headers)
    assert r.status_code == 200
    providers = {p["platform"]: p for p in r.json()}
    assert {"strava", "komoot", "garmin", "runalyze", "intervals_icu"} <= set(providers)
    assert providers["strava"]["athlete_capacity"] == 10
    assert providers["strava"]["monthly_cost_cents"] == 1199
    assert providers["strava"]["supports_webhooks"] is True
    assert providers["strava"]["tier_label"] == "Standard, self-upgraded (10 athletes)"
    assert providers["komoot"]["default_poll_min"] == 120
    assert providers["komoot"]["tier_label"] == "Unofficial (no published tier)"
    assert providers["komoot"]["notes"]


@pytest.mark.asyncio
async def test_update_provider(
    async_client: AsyncClient, free_user_headers: dict, db: AsyncSession
):
    await ensure_registry_seeded(db)
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        r = await async_client.patch(
            "/api/v1/admin/providers/komoot",
            json={"default_poll_min": 90, "monthly_cost_cents": 0},
            headers=free_user_headers,
        )
    assert r.status_code == 200
    assert r.json()["default_poll_min"] == 90


@pytest.mark.asyncio
async def test_update_provider_tier_label_and_notes(
    async_client: AsyncClient, free_user_headers: dict, db: AsyncSession
):
    await ensure_registry_seeded(db)
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        r = await async_client.patch(
            "/api/v1/admin/providers/strava",
            json={"tier_label": "Extended Access", "notes": "Upgraded via review."},
            headers=free_user_headers,
        )
    assert r.status_code == 200
    assert r.json()["tier_label"] == "Extended Access"
    assert r.json()["notes"] == "Upgraded via review."


@pytest.mark.asyncio
async def test_governor_get_and_validation(async_client: AsyncClient, free_user_headers: dict):
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        got = await async_client.get("/api/v1/admin/governor", headers=free_user_headers)
        assert got.status_code == 200
        assert got.json()["coverage_target_pct"] == 70

        bad = await async_client.patch(
            "/api/v1/admin/governor",
            json={"coverage_target_pct": 150},
            headers=free_user_headers,
        )
        assert bad.status_code == 422

        ok = await async_client.patch(
            "/api/v1/admin/governor",
            json={"coverage_target_pct": 80},
            headers=free_user_headers,
        )
        assert ok.status_code == 200
        assert ok.json()["coverage_target_pct"] == 80


@pytest.mark.asyncio
async def test_strava_app_crud_never_leaks_secret(
    async_client: AsyncClient, free_user_headers: dict
):
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        created = await async_client.post(
            "/api/v1/admin/strava-apps",
            json={"client_id": "999", "client_secret": "shh", "display_name": "Second App"},
            headers=free_user_headers,
        )
        assert created.status_code == 201
        body = created.json()
        assert "client_secret" not in body
        assert body["athlete_cap"] == 10
        assert body["monthly_cost_cents"] == 1199
        app_id = body["id"]

        listed = await async_client.get("/api/v1/admin/strava-apps", headers=free_user_headers)
        assert listed.status_code == 200
        assert all("client_secret" not in a for a in listed.json())

        patched = await async_client.patch(
            f"/api/v1/admin/strava-apps/{app_id}",
            json={"athlete_cap": 20},
            headers=free_user_headers,
        )
        assert patched.status_code == 200
        assert patched.json()["athlete_cap"] == 20


@pytest.mark.asyncio
async def test_metrics_overview(async_client: AsyncClient, free_user_headers: dict):
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        # Seed an app so cost/capacity are non-zero
        await async_client.post(
            "/api/v1/admin/strava-apps",
            json={"client_id": "1", "client_secret": "s", "display_name": "App"},
            headers=free_user_headers,
        )
        r = await async_client.get("/api/v1/admin/metrics/overview", headers=free_user_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["self_hosted"] is True
    assert data["strava"]["athlete_capacity"] >= 10
    assert data["monthly_cost_cents"] >= 1199


@pytest.mark.asyncio
async def test_metrics_providers_overview(
    async_client: AsyncClient, free_user, free_user_headers: dict, db: AsyncSession
):
    """Cross-provider overview aggregates real connected-user counts and, for
    Strava, rolls up cost/capacity from the app pool rather than provider_policy."""
    from datetime import UTC, datetime

    from app.db.models.connection import Connection
    from app.db.models.user import StravaApp, StravaToken

    await ensure_registry_seeded(db)

    db.add(
        StravaApp(
            id=1,
            client_id="1",
            client_secret=b"enc",
            display_name="App",
            is_active=True,
            athlete_cap=10,
            monthly_cost_cents=1199,
        )
    )
    db.add(
        StravaToken(
            user_id=free_user.id,
            strava_app_id=1,
            strava_athlete_id=1,
            access_token=b"e",
            refresh_token=b"e",
            expires_at=datetime.now(UTC),
            connected_at=datetime.now(UTC),
        )
    )
    db.add(Connection(user_id=free_user.id, platform="komoot", display_name="K", status="active"))
    await db.commit()

    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        r = await async_client.get("/api/v1/admin/metrics/providers", headers=free_user_headers)
    assert r.status_code == 200
    rows = {row["platform"]: row for row in r.json()}

    strava = rows["strava"]
    assert strava["connected_users"] == 1
    assert strava["monthly_cost_cents"] == 1199
    assert strava["capacity_note"] == "10 athlete slots across 1 app(s)"
    assert strava["tier_label"] == "Standard, self-upgraded (10 athletes)"

    komoot = rows["komoot"]
    assert komoot["connected_users"] == 1
    assert komoot["capacity_note"] is None

    runalyze = rows["runalyze"]
    assert runalyze["connected_users"] == 0


@pytest.mark.asyncio
async def test_metrics_providers_forbidden_for_non_admin(
    async_client: AsyncClient, free_user_headers: dict
):
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "cloud"):
        r = await async_client.get("/api/v1/admin/metrics/providers", headers=free_user_headers)
    assert r.status_code == 403

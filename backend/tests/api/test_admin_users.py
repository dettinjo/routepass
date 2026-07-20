from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.connection import Connection
from app.db.models.sync import ConnectionSyncState, JobAuditLog
from app.db.models.user import User


@pytest.mark.asyncio
async def test_list_users_paginated_with_counts(
    async_client: AsyncClient, free_user, free_user_headers: dict, db: AsyncSession
):
    conn = Connection(
        user_id=free_user.id, platform="komoot", display_name="Komoot", status="error"
    )
    db.add(conn)
    await db.commit()

    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        resp = await async_client.get(
            "/api/v1/admin/users", params={"limit": 10}, headers=free_user_headers
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    row = next(u for u in body["users"] if u["email"] == free_user.email)
    assert row["connections_count"] == 1
    assert row["error_connections_count"] == 1
    assert row["tier"] == "free"


@pytest.mark.asyncio
async def test_list_users_search_filters_by_email(
    async_client: AsyncClient, free_user_headers: dict, db: AsyncSession
):
    other = User(email="zzz-nomatch@test.com", is_active=True)
    db.add(other)
    await db.commit()

    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        resp = await async_client.get(
            "/api/v1/admin/users", params={"search": "zzz-nomatch"}, headers=free_user_headers
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["users"][0]["email"] == "zzz-nomatch@test.com"


@pytest.mark.asyncio
async def test_get_user_detail_includes_connections_and_jobs(
    async_client: AsyncClient, free_user, free_user_headers: dict, db: AsyncSession
):
    conn = Connection(
        user_id=free_user.id, platform="komoot", display_name="Komoot", status="error"
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    db.add(ConnectionSyncState(connection_id=conn.id, user_id=free_user.id, last_error="bad creds"))
    db.add(
        JobAuditLog(
            job_id="job1",
            job_type="poll_user_sources",
            user_id=free_user.id,
            status="failed",
            error_message="boom",
            enqueued_at=datetime.now(UTC),
        )
    )
    await db.commit()

    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        resp = await async_client.get(
            f"/api/v1/admin/users/{free_user.id}", headers=free_user_headers
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == free_user.email
    assert len(body["connections"]) == 1
    assert body["connections"][0]["last_error"] == "bad creds"
    assert body["connections"][0]["poll_interval_effective_min"] == 120  # komoot default
    assert len(body["recent_jobs"]) == 1
    assert body["recent_jobs"][0]["status"] == "failed"
    assert "strava" in body["usage_today"]


@pytest.mark.asyncio
async def test_get_user_detail_404(async_client: AsyncClient, free_user_headers: dict):
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        resp = await async_client.get(
            "/api/v1/admin/users/00000000-0000-0000-0000-000000000000",
            headers=free_user_headers,
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_metrics_revenue_selfhosted_is_zero(
    async_client: AsyncClient, free_user_headers: dict
):
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        resp = await async_client.get("/api/v1/admin/metrics/revenue", headers=free_user_headers)
    assert resp.status_code == 200
    assert resp.json()["monthly_revenue_cents"] == 0


@pytest.mark.asyncio
async def test_alerts_no_active_alerts_by_default(
    async_client: AsyncClient, free_user_headers: dict
):
    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        resp = await async_client.get("/api/v1/admin/alerts", headers=free_user_headers)
    assert resp.status_code == 200
    alerts = resp.json()
    assert any(a["severity"] == "ok" for a in alerts)


@pytest.mark.asyncio
async def test_alerts_flag_error_connections(
    async_client: AsyncClient, free_user, free_user_headers: dict, db: AsyncSession
):
    db.add(Connection(user_id=free_user.id, platform="komoot", display_name="K", status="error"))
    await db.commit()

    with patch("app.api.deps.settings.DEPLOYMENT_MODE", "selfhosted"):
        resp = await async_client.get("/api/v1/admin/alerts", headers=free_user_headers)
    assert resp.status_code == 200
    alerts = resp.json()
    assert any("error state" in a["message"] for a in alerts)

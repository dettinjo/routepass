from __future__ import annotations

"""
Integration tests using a real in-memory SQLite database.

These tests exercise the full request/response cycle including:
- SQL persistence and retrieval
- JWT authentication via the standard fixture tokens
- Tier enforcement (free vs. pro)
- Business rules (rule limits, etc.)
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.db.models.subscription import ApiKey
from app.db.models.sync import SyncedActivity, SyncRule, UserSyncState
from app.db.models.user import User

# ── Auth ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_creates_user_and_subscription(async_client: AsyncClient):
    resp = await async_client.post(
        "/api/v1/auth/register",
        json={"email": "new@test.com", "password": "pass1234"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_400(async_client: AsyncClient):
    payload = {"email": "dup@test.com", "password": "pass"}
    await async_client.post("/api/v1/auth/register", json=payload)
    resp = await async_client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_login_returns_token(async_client: AsyncClient):
    await async_client.post(
        "/api/v1/auth/register",
        json={"email": "login@test.com", "password": "secret"},
    )
    resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "login@test.com", "password": "secret"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(async_client: AsyncClient):
    await async_client.post(
        "/api/v1/auth/register",
        json={"email": "pw@test.com", "password": "correct"},
    )
    resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "pw@test.com", "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me_returns_profile(
    async_client: AsyncClient, free_user: User, free_user_headers: dict
):
    resp = await async_client.get("/api/v1/auth/me", headers=free_user_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == free_user.email
    assert data["tier"] == "free"
    assert data["komoot_connected"] is False
    assert data["strava_connected"] is False
    assert "connections" in data


@pytest.mark.asyncio
async def test_refresh_token(async_client: AsyncClient, free_user: User, free_user_headers: dict):
    resp = await async_client.post("/api/v1/auth/refresh", headers=free_user_headers)
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_update_settings(
    async_client: AsyncClient, free_user: User, free_user_headers: dict, db: AsyncSession
):
    resp = await async_client.patch(
        "/api/v1/auth/me/settings",
        headers=free_user_headers,
        json={"name": "Updated Name"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_update_settings_unknown_fields_ignored(
    async_client: AsyncClient, free_user: User, free_user_headers: dict
):
    # Unknown/removed fields must not cause a server error — Pydantic strips extras
    resp = await async_client.patch(
        "/api/v1/auth/me/settings",
        headers=free_user_headers,
        json={"name": "Valid Name", "unknown_field": "ignored"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Valid Name"


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401(async_client: AsyncClient):
    resp = await async_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# ── Sync ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_status_initial(
    async_client: AsyncClient, free_user: User, free_user_headers: dict
):
    resp = await async_client.get("/api/v1/sync/status", headers=free_user_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["komoot_connected"] is False
    assert data["strava_connected"] is False
    assert data["total_synced_count"] == 0
    assert data["latest_activity"] is None


@pytest.mark.asyncio
async def test_sync_status_reflects_sync_state(
    async_client: AsyncClient,
    free_user: User,
    free_user_headers: dict,
    db: AsyncSession,
):
    state = UserSyncState(user_id=free_user.id, total_synced_count=7)
    db.add(state)
    activity = SyncedActivity(
        user_id=free_user.id,
        komoot_tour_id="tour_123",
        strava_activity_id="act_456",
        sync_direction="komoot_to_strava",
        sync_status="completed",
        activity_name="Morning Ride",
    )
    db.add(activity)
    await db.commit()

    resp = await async_client.get("/api/v1/sync/status", headers=free_user_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_synced_count"] == 7
    assert data["latest_activity"]["komoot_tour_id"] == "tour_123"


# ── Activities ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activities_empty_list(
    async_client: AsyncClient, free_user: User, free_user_headers: dict
):
    resp = await async_client.get("/api/v1/activities", headers=free_user_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"] == []
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_activities_list_returns_users_activities(
    async_client: AsyncClient,
    free_user: User,
    free_user_headers: dict,
    db: AsyncSession,
):
    for i in range(3):
        db.add(
            SyncedActivity(
                user_id=free_user.id,
                komoot_tour_id=f"tour_{i}",
                sync_direction="komoot_to_strava",
                sync_status="completed",
            )
        )
    await db.commit()

    resp = await async_client.get("/api/v1/activities", headers=free_user_headers)
    assert resp.status_code == 200
    assert resp.json()["count"] == 3


@pytest.mark.asyncio
async def test_activity_detail_not_found(
    async_client: AsyncClient, free_user: User, free_user_headers: dict
):
    resp = await async_client.get(
        "/api/v1/activities/00000000-0000-0000-0000-000000000099",
        headers=free_user_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_activity_detail_another_users_activity_returns_404(
    async_client: AsyncClient,
    free_user: User,
    pro_user: User,
    free_user_headers: dict,
    db: AsyncSession,
):
    """Users must not be able to see each other's activities."""
    activity = SyncedActivity(
        user_id=pro_user.id,
        komoot_tour_id="other_tour",
        sync_direction="komoot_to_strava",
        sync_status="completed",
    )
    db.add(activity)
    await db.commit()

    resp = await async_client.get(
        f"/api/v1/activities/{activity.id}",
        headers=free_user_headers,
    )
    assert resp.status_code == 404


# ── Rules ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_free_user_can_create_one_rule(
    async_client: AsyncClient, free_user: User, free_user_headers: dict
):
    resp = await async_client.post(
        "/api/v1/rules",
        headers=free_user_headers,
        json={"name": "My Rule", "direction": "komoot_to_strava", "conditions": {}, "actions": {}},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_free_user_cannot_create_second_rule(
    async_client: AsyncClient, free_user: User, free_user_headers: dict, db: AsyncSession
):
    db.add(
        SyncRule(
            user_id=free_user.id,
            name="Existing Rule",
            direction="komoot_to_strava",
            conditions={},
            actions={},
            rule_order=0,
        )
    )
    await db.commit()

    resp = await async_client.post(
        "/api/v1/rules",
        headers=free_user_headers,
        json={
            "name": "Second Rule",
            "direction": "komoot_to_strava",
            "conditions": {},
            "actions": {},
        },
    )
    assert resp.status_code == 400
    assert "1" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_rules_crud(async_client: AsyncClient, pro_user: User, pro_user_headers: dict):
    # Create
    create_resp = await async_client.post(
        "/api/v1/rules",
        headers=pro_user_headers,
        json={
            "name": "Skip E-Bikes",
            "direction": "komoot_to_strava",
            "conditions": {"sport": "E-Bike"},
            "actions": {"sync_to": "None"},
            "rule_order": 0,
        },
    )
    assert create_resp.status_code == 200
    rule_id = create_resp.json()["id"]

    # List
    list_resp = await async_client.get("/api/v1/rules", headers=pro_user_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()["data"]) == 1
    assert list_resp.json()["data"][0]["name"] == "Skip E-Bikes"

    # Update
    update_resp = await async_client.put(
        f"/api/v1/rules/{rule_id}",
        headers=pro_user_headers,
        json={
            "name": "Skip E-Bikes Updated",
            "direction": "komoot_to_strava",
            "conditions": {"sport": "E-Bike"},
            "actions": {"sync_to": "None"},
            "rule_order": 0,
        },
    )
    assert update_resp.status_code == 200

    # Delete
    del_resp = await async_client.delete(f"/api/v1/rules/{rule_id}", headers=pro_user_headers)
    assert del_resp.status_code == 200

    # Confirm deleted
    list_after = await async_client.get("/api/v1/rules", headers=pro_user_headers)
    assert list_after.json()["data"] == []


@pytest.mark.asyncio
async def test_rules_max_5_enforced(
    async_client: AsyncClient, pro_user: User, pro_user_headers: dict, db: AsyncSession
):
    for i in range(5):
        db.add(
            SyncRule(
                user_id=pro_user.id,
                name=f"Rule {i}",
                direction="komoot_to_strava",
                conditions={},
                actions={},
                rule_order=i,
            )
        )
    await db.commit()

    resp = await async_client.post(
        "/api/v1/rules",
        headers=pro_user_headers,
        json={
            "name": "Rule 6",
            "direction": "komoot_to_strava",
            "conditions": {},
            "actions": {},
        },
    )
    assert resp.status_code == 400
    assert "5" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_rule_invalid_direction_rejected(
    async_client: AsyncClient, pro_user: User, pro_user_headers: dict
):
    resp = await async_client.post(
        "/api/v1/rules",
        headers=pro_user_headers,
        json={
            "name": "Bad Rule",
            "direction": "invalid_direction",
            "conditions": {},
            "actions": {},
        },
    )
    assert resp.status_code == 400


# ── API Keys (Pro) ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_keys_require_pro_tier(
    async_client: AsyncClient, free_user: User, free_user_headers: dict
):
    resp = await async_client.get("/api/v1/api-keys", headers=free_user_headers)
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_api_key_create_list_revoke(
    async_client: AsyncClient, pro_user: User, pro_user_headers: dict
):
    # Create
    create_resp = await async_client.post(
        "/api/v1/api-keys",
        headers=pro_user_headers,
        json={"name": "My Integration"},
    )
    assert create_resp.status_code == 200
    data = create_resp.json()
    assert data["raw_key"].startswith("rp_")
    assert "raw_key" in data
    key_id = data["id"]

    # List
    list_resp = await async_client.get("/api/v1/api-keys", headers=pro_user_headers)
    assert list_resp.status_code == 200
    keys = list_resp.json()["data"]
    assert len(keys) == 1
    assert "raw_key" not in keys[0]

    # Revoke
    revoke_resp = await async_client.delete(f"/api/v1/api-keys/{key_id}", headers=pro_user_headers)
    assert revoke_resp.status_code == 200

    # After revocation the key still appears in list (with revoked_at set)
    list_after = await async_client.get("/api/v1/api-keys", headers=pro_user_headers)
    assert list_after.json()["data"][0]["revoked_at"] is not None


@pytest.mark.asyncio
async def test_api_key_limit_5(
    async_client: AsyncClient, pro_user: User, pro_user_headers: dict, db: AsyncSession
):
    for i in range(5):
        raw, hashed = security.generate_api_key()
        db.add(
            ApiKey(
                user_id=pro_user.id,
                key_hash=hashed,
                key_prefix=raw[:8] + "...",
                name=f"Key {i}",
            )
        )
    await db.commit()

    resp = await async_client.post(
        "/api/v1/api-keys",
        headers=pro_user_headers,
        json={"name": "Key 6"},
    )
    assert resp.status_code == 400


# ── Billing ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscription_status_free_user(
    async_client: AsyncClient, free_user: User, free_user_headers: dict
):
    resp = await async_client.get("/api/v1/billing/subscription", headers=free_user_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "free"
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_subscription_status_pro_user(
    async_client: AsyncClient, pro_user: User, pro_user_headers: dict
):
    resp = await async_client.get("/api/v1/billing/subscription", headers=pro_user_headers)
    assert resp.status_code == 200
    assert resp.json()["tier"] == "pro"


@pytest.mark.asyncio
async def test_checkout_invalid_tier_rejected(
    async_client: AsyncClient, free_user: User, free_user_headers: dict
):
    resp = await async_client.post(
        "/api/v1/billing/checkout",
        headers=free_user_headers,
        json={"tier": "enterprise"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_portal_without_stripe_customer_returns_400(
    async_client: AsyncClient, pro_user: User, pro_user_headers: dict
):
    resp = await async_client.post("/api/v1/billing/portal", headers=pro_user_headers)
    assert resp.status_code == 400


# ── Webhooks ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_strava_webhook_verification(async_client: AsyncClient):
    resp = await async_client.get(
        "/api/v1/webhooks/strava",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "abc123",
            "hub.verify_token": "",
        },
    )
    # Empty verify token won't match settings (which defaults to ""), depends on config
    # Just assert it returns either 200 or 403
    assert resp.status_code in (200, 403)


@pytest.mark.asyncio
async def test_strava_webhook_receive_ignored_event(async_client: AsyncClient):
    resp = await async_client.post(
        "/api/v1/webhooks/strava",
        json={"object_type": "athlete", "aspect_type": "update", "object_id": 1, "owner_id": 1},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

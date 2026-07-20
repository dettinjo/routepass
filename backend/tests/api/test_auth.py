from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.db.models.user import StravaApp, StravaToken, User

UTC = UTC


@pytest.mark.asyncio
async def test_get_strava_login_url(async_client: AsyncClient, free_user_headers: dict, db):
    """Test generating the Strava login OAuth URI (requires authentication)."""
    # Governor admission control needs at least one Strava app with free slot
    # headroom, otherwise a brand-new free connection is correctly refused.
    db.add(StravaApp(client_id="1", client_secret=b"enc", display_name="App", is_active=True))
    await db.commit()

    response = await async_client.get("/api/v1/auth/strava/login", headers=free_user_headers)
    assert response.status_code == 200
    data = response.json()
    assert "url" in data
    assert "state" in data
    assert "https://www.strava.com/oauth/authorize" in data["url"]
    assert "response_type=code" in data["url"]
    # Redirect URI points to /strava/callback (route group doesn't add /auth/ prefix)
    assert "strava/callback" in data["url"]


@pytest.mark.asyncio
async def test_strava_callback_stores_encrypted_tokens(async_client: AsyncClient):
    """OAuth callback must encrypt Strava tokens before storing them."""
    from app.api import deps
    from app.main import app

    fake_user = User(id="00000000-0000-0000-0000-000000000000", email="test@test.com")
    added_objects = []

    app.dependency_overrides[deps.get_current_user] = lambda: fake_user

    fake_strava_app = StravaApp(id=1, client_id="12345", is_active=True)

    class FakeScalars:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class FakeStravaAppResult:
        """A4: returns all active apps via .scalars().all()."""

        def scalars(self):
            return FakeScalars([fake_strava_app])

    class FakeNoneResult:
        def scalar_one_or_none(self):
            return None

    # execute() is called in order:
    #   1. select(StravaApp).where(is_active) → [fake_strava_app]  (A4 multi-app)
    #   2. select(StravaToken) by user_id     → None  (new token path)
    #   3. select(StravaToken) by athlete_id  → None  (orphan check)
    #   4. select(ConnectionModel)            → None  (new connection row)
    _execute_results = iter(
        [
            FakeStravaAppResult(),
            FakeNoneResult(),
            FakeNoneResult(),
            FakeNoneResult(),
        ]
    )

    class FakeDB:
        def add(self, obj):
            added_objects.append(obj)

        async def commit(self):
            pass

        async def execute(self, _stmt):
            return next(_execute_results)

    app.dependency_overrides[deps.get_db] = lambda: FakeDB()

    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "access_token": "plain_access_token",
        "refresh_token": "plain_refresh_token",
        "expires_at": int(datetime(2026, 4, 18, tzinfo=UTC).timestamp()),
        "athlete": {"id": 123456},
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = fake_response

    with (
        patch("app.api.v1.auth.httpx.AsyncClient", return_value=mock_client),
        patch(
            "app.core.rate_limit.rate_limit_guard.pick_least_loaded_app",
            new=AsyncMock(return_value=1),
        ),
    ):
        response = await async_client.post(
            "/api/v1/auth/strava/callback",
            json={"code": "test_code"},
        )

    assert response.status_code == 200
    # db.add() is called for StravaToken AND ConnectionModel (to keep connections table in sync)
    assert len(added_objects) >= 1

    strava_tokens = [o for o in added_objects if isinstance(o, StravaToken)]
    assert len(strava_tokens) == 1, f"Expected 1 StravaToken in added_objects, got {added_objects}"

    token = strava_tokens[0]
    assert token.access_token != b"plain_access_token"
    assert token.refresh_token != b"plain_refresh_token"
    assert token.strava_athlete_id == 123456

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_me_reports_pro_tier_in_selfhosted(
    async_client: AsyncClient,
    free_user_headers: dict,
):
    """Self-hosted instances unlock all features, so /me reports the free user as pro."""
    with patch("app.api.v1.auth.settings.DEPLOYMENT_MODE", "selfhosted"):
        resp = await async_client.get("/api/v1/auth/me", headers=free_user_headers)
    assert resp.status_code == 200
    assert resp.json()["tier"] == "pro"


@pytest.mark.asyncio
async def test_me_reports_free_tier_in_cloud(
    async_client: AsyncClient,
    free_user_headers: dict,
):
    """In cloud mode a free user stays free (tier gating still applies)."""
    with patch("app.api.v1.auth.settings.DEPLOYMENT_MODE", "cloud"):
        resp = await async_client.get("/api/v1/auth/me", headers=free_user_headers)
    assert resp.status_code == 200
    assert resp.json()["tier"] == "free"


@pytest.mark.asyncio
async def test_me_reports_is_admin_effective(
    async_client: AsyncClient,
    free_user_headers: dict,
):
    """is_admin mirrors require_admin: true in self-hosted or for comp emails."""
    with patch("app.api.v1.auth.settings.DEPLOYMENT_MODE", "selfhosted"):
        resp = await async_client.get("/api/v1/auth/me", headers=free_user_headers)
    assert resp.json()["is_admin"] is True

    with patch("app.api.v1.auth.settings.DEPLOYMENT_MODE", "cloud"):
        resp = await async_client.get("/api/v1/auth/me", headers=free_user_headers)
    assert resp.json()["is_admin"] is False

    with (
        patch("app.api.v1.auth.settings.DEPLOYMENT_MODE", "cloud"),
        patch("app.core.tiers.settings.ADMIN_EMAILS", "free@test.com"),
    ):
        resp = await async_client.get("/api/v1/auth/me", headers=free_user_headers)
    assert resp.json()["is_admin"] is True

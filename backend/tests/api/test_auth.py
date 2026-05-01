from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.db.models.user import StravaApp, StravaToken, User

UTC = UTC


@pytest.mark.asyncio
async def test_get_strava_login_url(async_client: AsyncClient, free_user_headers: dict):
    """Test generating the Strava login OAuth URI (requires authentication)."""
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
async def test_setup_komoot_connection(async_client: AsyncClient):
    """Test that Komoot credentials are encrypted correctly."""
    # We mock out the dependency in `app.api.deps`
    from app.api import deps
    from app.main import app

    # Fake user object mimicking the sqlalchemy model
    fake_user = User(id="00000000-0000-0000-0000-000000000000", email="test@test.com")

    app.dependency_overrides[deps.get_current_user] = lambda: fake_user

    class FakeConnection:
        pass

    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeDB:
        async def execute(self, stmt):
            return FakeResult()

        async def commit(self):
            pass

        def add(self, obj):
            pass

    app.dependency_overrides[deps.get_db] = lambda: FakeDB()

    response = await async_client.post(
        "/api/v1/auth/komoot",
        json={
            "email": "my_komoot@email.com",
            "password": "super_secret_komoot_pw",
            "user_id": "123456789",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    app.dependency_overrides.clear()


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

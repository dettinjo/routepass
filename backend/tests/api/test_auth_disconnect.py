from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.db.models.user import StravaToken, User


@pytest.mark.asyncio
async def test_disconnect_integrations(async_client: AsyncClient):
    """Test disconnecting Komoot and Strava integrations."""
    from app.api import deps
    from app.main import app

    fake_user = User(
        id="00000000-0000-0000-0000-000000000000",
        email="test@test.com",
    )
    fake_token = StravaToken(
        user_id=fake_user.id,
        strava_app_id=1,
        strava_athlete_id=123456,
        access_token=b"encrypted",
        refresh_token=b"encrypted",
        expires_at=None,
        connected_at=None,
    )

    app.dependency_overrides[deps.get_current_user] = lambda: fake_user

    class FakeResult:
        def __init__(self, scalar_val=None):
            self._scalar = scalar_val

        def scalar_one_or_none(self):
            return self._scalar

    class FakeDB:
        async def execute(self, stmt):
            return FakeResult(scalar_val=fake_token)

        async def commit(self):
            pass

        async def delete(self, obj):
            obj.deleted = True

    app.dependency_overrides[deps.get_db] = lambda: FakeDB()

    komoot_response = await async_client.delete("/api/v1/auth/komoot/disconnect")
    assert komoot_response.status_code == 200

    strava_response = await async_client.delete("/api/v1/auth/strava/disconnect")
    assert strava_response.status_code == 200
    assert getattr(fake_token, "deleted", False) is True

    app.dependency_overrides.clear()

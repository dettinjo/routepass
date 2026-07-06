from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core import security
from app.db.models.connection import Connection
from app.db.models.sync import SyncedActivity
from app.db.models.user import User

UTC = UTC


@pytest.mark.asyncio
async def test_get_activities_empty(async_client: AsyncClient):
    """Activities list returns empty for a new user (uses real DB via async_client fixture)."""
    # async_client is wired to a real in-memory DB via conftest; register a fresh user.
    reg = await async_client.post(
        "/api/v1/auth/register",
        json={"email": "act_empty@test.com", "password": "pw1234"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await async_client.get("/api/v1/activities", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["data"] == []
    assert data["limit"] == 50
    assert data["skip"] == 0


@pytest.mark.asyncio
async def test_get_activity_detail(async_client: AsyncClient):
    """Test retrieving a single activity by id."""
    from app.api import deps
    from app.main import app

    fake_user = User(id="00000000-0000-0000-0000-000000000000", email="test@test.com")
    fake_activity = SyncedActivity(
        id="11111111-1111-1111-1111-111111111111",
        user_id=fake_user.id,
        komoot_tour_id="tour_1",
        strava_activity_id="activity_1",
        sync_direction="komoot_to_strava",
        sync_status="completed",
        activity_name="Morning Ride",
        sport_type="Ride",
        distance_m=12000,
        elevation_up_m=200,
        started_at=datetime.now(UTC),
        synced_at=datetime.now(UTC),
    )

    app.dependency_overrides[deps.get_current_user] = lambda: fake_user

    class FakeResult:
        def __init__(self, scalar_val=None):
            self._scalar = scalar_val

        def scalar_one_or_none(self):
            return self._scalar

    class FakeDB:
        async def execute(self, stmt):
            return FakeResult(scalar_val=fake_activity)

    app.dependency_overrides[deps.get_db] = lambda: FakeDB()

    response = await async_client.get(f"/api/v1/activities/{fake_activity.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(fake_activity.id)
    assert response.json()["activity_name"] == "Morning Ride"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_download_activity_gpx(async_client: AsyncClient):
    """Test downloading GPX for a synced Komoot-backed activity."""
    import json

    from app.api import deps
    from app.main import app

    fake_user = User(
        id="00000000-0000-0000-0000-000000000000",
        email="test@test.com",
    )
    fake_activity = SyncedActivity(
        id="22222222-2222-2222-2222-222222222222",
        user_id=fake_user.id,
        komoot_tour_id="tour_42",
        strava_activity_id="activity_42",
        sync_direction="komoot_to_strava",
        sync_status="completed",
        activity_name="Hill Session",
        sport_type="Ride",
        synced_at=datetime.now(UTC),
    )
    # Provide a fake Komoot Connection so the endpoint can resolve credentials
    fake_komoot_conn = Connection(
        user_id=fake_user.id,
        platform="komoot",
        display_name="Komoot",
        status="active",
        credentials_enc=security.encrypt(
            json.dumps(
                {
                    "email": "komoot@example.com",
                    "password": "secret-password",
                    "user_id": "komoot-user-1",
                }
            )
        ),
    )

    app.dependency_overrides[deps.get_current_user] = lambda: fake_user

    class FakeResult:
        def __init__(self, scalar_val=None):
            self._scalar = scalar_val

        def scalar_one_or_none(self):
            return self._scalar

    class FakeDB:
        def __init__(self):
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            if self.calls == 1:
                # select(SyncedActivity)
                return FakeResult(scalar_val=fake_activity)
            # select(Connection) for komoot credentials
            return FakeResult(scalar_val=fake_komoot_conn)

    app.dependency_overrides[deps.get_db] = lambda: FakeDB()

    with patch(
        "app.api.v1.activities.KomootClient.download_gpx",
        new=AsyncMock(return_value=b"<gpx><trk/></gpx>"),
    ) as mock_download_gpx:
        response = await async_client.get(f"/api/v1/activities/{fake_activity.id}/gpx")

    assert response.status_code == 200
    assert response.content == b"<gpx><trk/></gpx>"
    assert response.headers["content-type"].startswith("application/gpx+xml")
    assert response.headers["content-disposition"] == (
        'attachment; filename="komoot-tour-tour_42.gpx"'
    )
    mock_download_gpx.assert_awaited_once_with("tour_42")

    app.dependency_overrides.clear()

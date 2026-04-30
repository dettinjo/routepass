from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.db.models.connection import Connection
from app.db.models.sync import SyncedActivity, UserSyncState
from app.db.models.user import User

UTC = UTC


@pytest.mark.asyncio
async def test_get_sync_status(async_client: AsyncClient):
    """Test retrieving aggregate sync status for the current user."""
    from app.api import deps
    from app.main import app

    fake_user = User(
        id="00000000-0000-0000-0000-000000000000",
        email="test@test.com",
    )
    fake_state = UserSyncState(
        user_id=fake_user.id,
        total_synced_count=4,
        last_error="Temporary failure",
        last_komoot_sync_at=datetime.now(UTC),
        last_successful_sync_at=datetime.now(UTC),
    )
    fake_activity = SyncedActivity(
        id="11111111-1111-1111-1111-111111111111",
        user_id=fake_user.id,
        komoot_tour_id="tour_1",
        strava_activity_id="activity_1",
        sync_direction="komoot_to_strava",
        sync_status="completed",
        activity_name="Evening Ride",
        sport_type="Ride",
        synced_at=datetime.now(UTC),
    )
    fake_komoot_conn = Connection(
        user_id=fake_user.id,
        platform="komoot",
        display_name="Komoot",
        status="active",
    )

    app.dependency_overrides[deps.get_current_user] = lambda: fake_user

    class FakeScalarsResult:
        """Supports .scalars().all() for Connection list queries."""

        def __init__(self, items):
            self._items = items

        def scalars(self):
            return self

        def all(self):
            return self._items

        def scalar_one_or_none(self):
            return self._items[0] if self._items else None

    class FakeSingleResult:
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
                # select(UserSyncState)
                return FakeSingleResult(scalar_val=fake_state)
            if self.calls == 2:
                # select(SyncedActivity) — latest activity
                return FakeSingleResult(scalar_val=fake_activity)
            if self.calls == 3:
                # select(Connection) — returns list; komoot is connected
                return FakeScalarsResult([fake_komoot_conn])
            # select(StravaToken)
            return FakeSingleResult(scalar_val=None)

    app.dependency_overrides[deps.get_db] = lambda: FakeDB()

    response = await async_client.get("/api/v1/sync/status")

    assert response.status_code == 200
    data = response.json()
    assert data["komoot_connected"] is True
    assert data["total_synced_count"] == 4
    assert data["latest_activity"]["activity_name"] == "Evening Ride"

    app.dependency_overrides.clear()

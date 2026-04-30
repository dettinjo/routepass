from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.db.models.connection import Connection
from app.db.models.sync import ConnectionSyncState, SyncedActivity
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
        id="22222222-2222-2222-2222-222222222222",
        user_id=fake_user.id,
        platform="komoot",
        display_name="Komoot",
        status="active",
    )
    fake_css = ConnectionSyncState(
        connection_id="22222222-2222-2222-2222-222222222222",
        user_id=fake_user.id,
        last_synced_at=datetime.now(UTC),
        last_error=None,
    )

    app.dependency_overrides[deps.get_current_user] = lambda: fake_user

    class FakeScalarsResult:
        """Supports both .scalars().all() and .scalar_one_or_none()."""

        def __init__(self, items):
            self._items = items

        def scalars(self):
            return self

        def all(self):
            return self._items

        def scalar_one_or_none(self):
            return self._items[0] if self._items else None

        def scalar_one(self):
            return self._items[0] if self._items else 0

    class FakeDB:
        def __init__(self):
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            if self.calls == 1:
                # select(SyncedActivity) — latest activity
                return FakeScalarsResult([fake_activity])
            if self.calls == 2:
                # select(Connection) — list of connections
                return FakeScalarsResult([fake_komoot_conn])
            if self.calls == 3:
                # select(ConnectionSyncState) — per-connection watermarks
                return FakeScalarsResult([fake_css])
            if self.calls == 4:
                # select(StravaToken) — legacy check
                return FakeScalarsResult([])
            # select(func.count(Pipeline.id)) — active pipeline count
            return FakeScalarsResult([0])

    app.dependency_overrides[deps.get_db] = lambda: FakeDB()

    response = await async_client.get("/api/v1/sync/status")

    assert response.status_code == 200
    data = response.json()
    assert data["komoot_connected"] is True
    assert data["strava_connected"] is False
    assert data["active_pipelines"] == 0
    assert data["latest_activity"]["activity_name"] == "Evening Ride"
    assert len(data["connections"]) == 1
    assert data["connections"][0]["platform"] == "komoot"
    assert data["connections"][0]["connected"] is True
    assert data["connections"][0]["last_sync_at"] is not None

    app.dependency_overrides.clear()

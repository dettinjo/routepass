from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models.sync import SyncRule, UserSyncState
from app.db.models.user import StravaApp, User
from app.services.komoot import Tour
from app.services.sync import SyncService

UTC = timezone.utc


@pytest.mark.asyncio
async def test_sync_komoot_to_strava_evaluates_rules():
    """SyncService must skip tours that match an active rule with sync_to=None."""

    # ── Build fake in-memory DB state ─────────────────────────────────────
    sync_state = UserSyncState(
        user_id="00000000-0000-0000-0000-000000000000",
        total_synced_count=0,
    )

    block_rule = SyncRule(
        id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        user_id="00000000-0000-0000-0000-000000000000",
        name="Block E-Bikes",
        direction="komoot_to_strava",
        is_active=True,
        rule_order=0,
        conditions={"sport": "E-Bike"},
        actions={"sync_to": "None"},
    )

    added_records = []

    class FakeResult:
        """Fake SQLAlchemy result that returns different objects per query."""

        def __init__(self, scalar_val=None, items=None):
            self._scalar = scalar_val
            self._items = items or []

        def scalar_one_or_none(self):
            return self._scalar

        def scalars(self):
            items = self._items

            class _Scalars:
                def all(self):
                    return items

            return _Scalars()

    call_count = {"n": 0}

    def fake_execute(stmt):
        call_count["n"] += 1
        stmt_str = str(stmt).lower()
        if "user_sync_state" in stmt_str:
            return FakeResult(scalar_val=sync_state)
        if "sync_rules" in stmt_str:
            return FakeResult(items=[block_rule])
        # duplicate-check queries → not found
        return FakeResult()

    mock_db = AsyncMock()
    mock_db.execute.side_effect = fake_execute

    def fake_add(obj):
        added_records.append(obj)

    mock_db.add = fake_add
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()

    # Two tours: one E-Bike (should be blocked), one Run (should sync)
    mock_komoot = AsyncMock()
    mock_komoot.get_tours.return_value = [
        Tour(
            id="tour_ebike",
            name="Evening Ebike",
            description="",
            sport="E-Bike",
            strava_sport="EBikeRide",
            date=datetime.now(UTC),
            distance_m=15000,
            elevation_up_m=200,
        ),
        Tour(
            id="tour_run",
            name="Morning Run",
            description="",
            sport="Running",
            strava_sport="Run",
            date=datetime.now(UTC),
            distance_m=5000,
            elevation_up_m=50,
        ),
    ]

    mock_komoot.download_gpx = AsyncMock(return_value=b"<gpx/>")

    mock_strava = AsyncMock()
    mock_strava.upload_gpx.return_value = "upload_001"
    mock_strava.poll_upload.return_value = "activity_001"
    mock_strava.update_activity = AsyncMock()

    user = User(id="00000000-0000-0000-0000-000000000000", is_active=True)
    strava_app = StravaApp(id=1, client_id="226500", display_name="Test")

    # Patch the rate_limit_guard so it doesn't try to reach Redis
    async def passthrough(app_id, tier, fn, **kwargs):
        return await fn(**kwargs)

    with patch("app.services.sync.rate_limit_guard.call", side_effect=passthrough):
        sync = SyncService(mock_db)
        synced_count = await sync.sync_komoot_to_strava(user, strava_app, mock_komoot, mock_strava)

    # ── Assertions ────────────────────────────────────────────────────────
    assert synced_count == 1, f"Expected 1 tour synced (E-Bike blocked by rule), got {synced_count}"
    # upload_gpx should only ever be called for the Run tour
    mock_strava.upload_gpx.assert_called_once()
    called_with = mock_strava.upload_gpx.call_args
    assert called_with.kwargs.get("sport_type") == "Run"

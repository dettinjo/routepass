from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.core import security
from app.db.models.user import StravaToken, User
from app.jobs.sync_jobs import _get_valid_strava_access_token

UTC = timezone.utc


@pytest.mark.asyncio
async def test_get_valid_strava_access_token_refreshes_when_expiring():
    """Expiring Strava tokens should be refreshed and re-encrypted before use."""
    user = User(id="00000000-0000-0000-0000-000000000000", email="test@test.com")
    user.strava_token = StravaToken(
        user_id=user.id,
        strava_app_id=1,
        strava_athlete_id=123456,
        access_token=security.encrypt("old_access"),
        refresh_token=security.encrypt("old_refresh"),
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
        connected_at=datetime.now(UTC),
    )

    refreshed_payload = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "expires_at": int((datetime.now(UTC) + timedelta(hours=6)).timestamp()),
    }

    with patch(
        "app.jobs.sync_jobs.StravaClient.refresh_access_token",
        new=AsyncMock(return_value=refreshed_payload),
    ):
        access_token = await _get_valid_strava_access_token(user)

    assert access_token == "new_access"
    assert security.decrypt(user.strava_token.access_token) == "new_access"
    assert security.decrypt(user.strava_token.refresh_token) == "new_refresh"
    assert user.strava_token.last_refreshed_at is not None

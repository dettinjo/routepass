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


@pytest.mark.asyncio
async def test_activities_overview(
    async_client: AsyncClient, free_user: User, free_user_headers: dict, db
):
    """Overview aggregates totals, per-sport breakdown, and a time trend."""
    from datetime import timedelta

    now = datetime.now(UTC)
    db.add_all(
        [
            SyncedActivity(
                user_id=free_user.id,
                source="strava",
                strava_activity_id="s1",
                activity_name="Ride A",
                sport_type="Ride",
                distance_m=20000,
                duration_seconds=3600,
                elevation_up_m=300,
                calories=500,
                tss=60,
                moving_time_s=3400,
                metrics_computed_at=now,
                started_at=now - timedelta(days=1),
                synced_at=now,
            ),
            SyncedActivity(
                user_id=free_user.id,
                source="strava",
                strava_activity_id="s2",
                activity_name="Ride B",
                sport_type="Ride",
                distance_m=10000,
                duration_seconds=1800,
                elevation_up_m=100,
                started_at=now - timedelta(days=3),
                synced_at=now,
            ),
            SyncedActivity(
                user_id=free_user.id,
                source="strava",
                strava_activity_id="s3",
                activity_name="Run C",
                sport_type="Run",
                distance_m=5000,
                duration_seconds=1500,
                elevation_up_m=50,
                started_at=now - timedelta(days=2),
                synced_at=now,
            ),
        ]
    )
    await db.commit()

    resp = await async_client.get("/api/v1/activities/overview", headers=free_user_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["totals"]["count"] == 3
    assert data["totals"]["distance_m"] == 35000
    assert data["totals"]["duration_s"] == 6900
    assert data["totals"]["calories"] == 500
    assert data["totals"]["tss"] == 60
    assert data["totals"]["metrics_pending"] == 2  # two without metrics_computed_at

    # By-sport sorted by distance desc → Ride (30km) before Run (5km)
    assert [s["sport_type"] for s in data["by_sport"]] == ["Ride", "Run"]
    assert data["by_sport"][0]["count"] == 2
    assert data["by_sport"][0]["distance_m"] == 30000

    assert data["grain"] == "week"
    assert sum(b["count"] for b in data["trend"]) == 3


@pytest.mark.asyncio
async def test_activities_overview_sport_filter(
    async_client: AsyncClient, free_user: User, free_user_headers: dict, db
):
    """Overview honours the same filters as the list endpoint."""
    now = datetime.now(UTC)
    db.add_all(
        [
            SyncedActivity(
                user_id=free_user.id,
                source="strava",
                strava_activity_id="f1",
                sport_type="Ride",
                distance_m=20000,
                duration_seconds=3600,
                started_at=now,
                synced_at=now,
            ),
            SyncedActivity(
                user_id=free_user.id,
                source="strava",
                strava_activity_id="f2",
                sport_type="Run",
                distance_m=5000,
                duration_seconds=1500,
                started_at=now,
                synced_at=now,
            ),
        ]
    )
    await db.commit()

    resp = await async_client.get(
        "/api/v1/activities/overview?sport_type=Run", headers=free_user_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["totals"]["count"] == 1
    assert data["totals"]["distance_m"] == 5000
    assert [s["sport_type"] for s in data["by_sport"]] == ["Run"]


@pytest.mark.asyncio
async def test_trip_analysis_combines_stages(
    async_client: AsyncClient, free_user: User, free_user_headers: dict, db
):
    """POST /activities/analysis combines stages ordered by started_at."""
    import gzip
    import json as _json
    from datetime import timedelta

    now = datetime.now(UTC)
    track_day1 = [
        {"t": 0, "d": 0, "ele": 100, "lat": 47.0, "lon": 8.0},
        {"t": 60, "d": 1000, "ele": 120, "lat": 47.01, "lon": 8.01},
    ]
    track_day2 = [
        {"t": 0, "d": 0, "ele": 200, "lat": 47.5, "lon": 8.5},
        {"t": 60, "d": 2000, "ele": 250, "lat": 47.51, "lon": 8.51},
    ]
    day2 = SyncedActivity(
        user_id=free_user.id,
        source="strava",
        strava_activity_id="trip_day2",
        activity_name="Day 2",
        sport_type="Ride",
        distance_m=20000,
        duration_seconds=3600,
        elevation_up_m=300,
        elevation_down_m=100,
        calories=600,
        tss=70,
        moving_time_s=3400,
        metrics_computed_at=now,
        metrics_detail={
            "hr_zones": {"bounds": [100, 120, 140, 160], "seconds": [10, 20, 30, 40, 50]},
        },
        track_gz=gzip.compress(_json.dumps(track_day2).encode()),
        started_at=now - timedelta(days=1),
        synced_at=now,
    )
    day1 = SyncedActivity(
        user_id=free_user.id,
        source="strava",
        strava_activity_id="trip_day1",
        activity_name="Day 1",
        sport_type="Ride",
        distance_m=15000,
        duration_seconds=3000,
        elevation_up_m=200,
        elevation_down_m=50,
        calories=400,
        tss=50,
        moving_time_s=2800,
        metrics_computed_at=now,
        metrics_detail={
            "hr_zones": {"bounds": [100, 120, 140, 160], "seconds": [5, 15, 25, 35, 45]},
        },
        track_gz=gzip.compress(_json.dumps(track_day1).encode()),
        started_at=now - timedelta(days=2),
        synced_at=now,
    )
    db.add_all([day1, day2])
    await db.commit()
    await db.refresh(day1)
    await db.refresh(day2)

    resp = await async_client.post(
        "/api/v1/activities/analysis",
        headers=free_user_headers,
        json={"activity_ids": [str(day2.id), str(day1.id)]},  # deliberately out of order
    )
    assert resp.status_code == 200
    data = resp.json()

    # Ordered by started_at: day1 first, day2 second.
    assert [s["name"] for s in data["stages"]] == ["Day 1", "Day 2"]
    assert data["stages"][1]["cumulative_distance_start_m"] == 15000

    assert data["totals"]["count"] == 2
    assert data["totals"]["distance_m"] == 35000
    assert data["totals"]["calories"] == 1000
    assert data["totals"]["tss"] == 120

    assert len(data["day_bars"]) == 2

    # Profile concatenates both tracks with a cumulative distance offset.
    assert len(data["profile"]) == 4
    stage2_points = [p for p in data["profile"] if p["stage"] == 1]
    assert stage2_points[0]["x"] == 15.0  # 15000m offset + 0m = 15km
    assert stage2_points[1]["x"] == 17.0  # 15000m offset + 2000m = 17km

    assert len(data["map_stages"]) == 2

    # HR zone seconds summed position-wise across stages.
    assert data["hr_zones"]["seconds"] == [15, 35, 55, 75, 95]


@pytest.mark.asyncio
async def test_trip_analysis_requires_two_activities(
    async_client: AsyncClient, free_user_headers: dict
):
    resp = await async_client.post(
        "/api/v1/activities/analysis",
        headers=free_user_headers,
        json={"activity_ids": ["11111111-1111-1111-1111-111111111111"]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_trip_analysis_rejects_other_users_activity(
    async_client: AsyncClient, free_user: User, free_user_headers: dict, db
):
    from app.core import security as _security

    other = User(email="other_trip@test.com", password_hash=_security.hash_password("pw123456"))
    db.add(other)
    await db.commit()
    await db.refresh(other)

    mine = SyncedActivity(
        user_id=free_user.id,
        source="import",
        activity_name="Mine",
        distance_m=1000,
        synced_at=datetime.now(UTC),
    )
    theirs = SyncedActivity(
        user_id=other.id,
        source="import",
        activity_name="Theirs",
        distance_m=1000,
        synced_at=datetime.now(UTC),
    )
    db.add_all([mine, theirs])
    await db.commit()
    await db.refresh(mine)
    await db.refresh(theirs)

    resp = await async_client.post(
        "/api/v1/activities/analysis",
        headers=free_user_headers,
        json={"activity_ids": [str(mine.id), str(theirs.id)]},
    )
    assert resp.status_code == 404

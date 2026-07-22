from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.db.models.sync import SyncedActivity
from app.db.models.user import User

UTC = UTC


@pytest.mark.asyncio
async def test_training_load_requires_pro(async_client: AsyncClient, free_user_headers: dict):
    resp = await async_client.get("/api/v1/activities/training-load", headers=free_user_headers)
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_training_load_no_activities(async_client: AsyncClient, pro_user_headers: dict):
    resp = await async_client.get("/api/v1/activities/training-load", headers=pro_user_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["series"] == []


@pytest.mark.asyncio
async def test_training_load_builds_ctl_atl_series(
    async_client: AsyncClient, pro_user: User, pro_user_headers: dict, db
):
    now = datetime.now(UTC)
    # Steady daily TSS of 50, including today, for long enough (~5 CTL time
    # constants) to reach near-steady-state, where both EWMAs converge to the
    # daily TSS and TSB settles near 0.
    n_days = 200
    activities = [
        SyncedActivity(
            user_id=pro_user.id,
            source="strava",
            strava_activity_id=f"tl_{i}",
            activity_name=f"Steady day {i}",
            sport_type="Ride",
            tss=50.0,
            started_at=now - timedelta(days=n_days - i),
            synced_at=now,
        )
        for i in range(n_days + 1)
    ]
    db.add_all(activities)
    await db.commit()

    resp = await async_client.get(
        "/api/v1/activities/training-load?days=90", headers=pro_user_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["current"]["ctl"] == pytest.approx(50, abs=2)
    assert data["current"]["atl"] == pytest.approx(50, abs=0.5)
    assert abs(data["current"]["tsb"]) < 3
    assert data["current"]["status"] == "neutral"
    # Only the requested window is returned, even though the full history fed the recursion.
    assert len(data["series"]) == 90


@pytest.mark.asyncio
async def test_training_load_detects_high_fatigue_after_hard_block(
    async_client: AsyncClient, pro_user: User, pro_user_headers: dict, db
):
    now = datetime.now(UTC)
    # A long easy base, then a sudden hard block right up to today: ATL should
    # spike above CTL, driving TSB sharply negative (high fatigue).
    activities = [
        SyncedActivity(
            user_id=pro_user.id,
            source="strava",
            strava_activity_id=f"base_{i}",
            sport_type="Ride",
            tss=30.0,
            started_at=now - timedelta(days=100 - i),
            synced_at=now,
        )
        for i in range(90)
    ]
    activities += [
        SyncedActivity(
            user_id=pro_user.id,
            source="strava",
            strava_activity_id=f"hard_{i}",
            sport_type="Ride",
            tss=150.0,
            started_at=now - timedelta(days=6 - i),
            synced_at=now,
        )
        for i in range(6)
    ]
    db.add_all(activities)
    await db.commit()

    resp = await async_client.get("/api/v1/activities/training-load", headers=pro_user_headers)
    data = resp.json()
    assert data["current"]["tsb"] < -10
    assert data["current"]["status"] in ("fatigued", "very_fatigued")


@pytest.mark.asyncio
async def test_records_requires_pro(async_client: AsyncClient, free_user_headers: dict):
    resp = await async_client.get("/api/v1/activities/records", headers=free_user_headers)
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_records_overall_and_by_sport(
    async_client: AsyncClient, pro_user: User, pro_user_headers: dict, db
):
    now = datetime.now(UTC)
    db.add_all(
        [
            SyncedActivity(
                user_id=pro_user.id,
                source="strava",
                strava_activity_id="rec1",
                activity_name="Long ride",
                sport_type="Ride",
                distance_m=100000,
                elevation_up_m=1200,
                avg_power=210,
                started_at=now - timedelta(days=5),
                synced_at=now,
            ),
            SyncedActivity(
                user_id=pro_user.id,
                source="strava",
                strava_activity_id="rec2",
                activity_name="Short ride",
                sport_type="Ride",
                distance_m=20000,
                elevation_up_m=300,
                avg_power=250,
                started_at=now - timedelta(days=2),
                synced_at=now,
            ),
            SyncedActivity(
                user_id=pro_user.id,
                source="strava",
                strava_activity_id="rec3",
                activity_name="Long run",
                sport_type="Run",
                distance_m=21000,
                elevation_up_m=150,
                started_at=now - timedelta(days=1),
                synced_at=now,
            ),
        ]
    )
    await db.commit()

    resp = await async_client.get("/api/v1/activities/records", headers=pro_user_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["overall"]["longest_distance_m"]["name"] == "Long ride"
    assert data["overall"]["longest_distance_m"]["value"] == 100000
    assert data["overall"]["highest_avg_power_w"]["name"] == "Short ride"
    assert data["overall"]["most_elevation_gain_m"]["name"] == "Long ride"

    assert set(data["by_sport"].keys()) == {"Ride", "Run"}
    assert data["by_sport"]["Ride"]["longest_distance_m"]["name"] == "Long ride"
    assert data["by_sport"]["Run"]["longest_distance_m"]["name"] == "Long run"


@pytest.mark.asyncio
async def test_records_empty_for_new_user(async_client: AsyncClient, pro_user_headers: dict):
    resp = await async_client.get("/api/v1/activities/records", headers=pro_user_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall"]["longest_distance_m"] is None
    assert data["by_sport"] == {}

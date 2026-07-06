from __future__ import annotations

"""Tests for activity seed, GPX import, and delete endpoints."""

import io
import textwrap
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sync import SyncedActivity
from app.db.models.user import User

UTC = timezone.utc

# ── Seed ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_creates_12_activities(
    async_client: AsyncClient,
    free_user_headers: dict,
    db: AsyncSession,
) -> None:
    response = await async_client.post("/api/v1/activities/seed", headers=free_user_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["created"] == 12
    assert body["skipped_existing"] == 0
    assert body["total"] == 12


@pytest.mark.asyncio
async def test_seed_is_idempotent(
    async_client: AsyncClient,
    free_user_headers: dict,
) -> None:
    """Calling seed twice must not create duplicates."""
    await async_client.post("/api/v1/activities/seed", headers=free_user_headers)
    response = await async_client.post("/api/v1/activities/seed", headers=free_user_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["created"] == 0
    assert body["skipped_existing"] == 12


@pytest.mark.asyncio
async def test_seeded_activities_appear_in_list(
    async_client: AsyncClient,
    free_user_headers: dict,
) -> None:
    await async_client.post("/api/v1/activities/seed", headers=free_user_headers)
    response = await async_client.get("/api/v1/activities?limit=100", headers=free_user_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    local = [a for a in data if a["source"] == "import"]
    assert len(local) == 12


@pytest.mark.asyncio
async def test_seeded_activities_cover_all_sport_types(
    async_client: AsyncClient,
    free_user_headers: dict,
) -> None:
    await async_client.post("/api/v1/activities/seed", headers=free_user_headers)
    response = await async_client.get("/api/v1/activities?limit=100", headers=free_user_headers)
    sports = {a["sport_type"] for a in response.json()["data"]}
    expected = {
        "jogging",
        "trail_running",
        "touringbicycle",
        "road_cycling",
        "mtb_advanced",
        "e_touringbicycle",
        "hiking",
        "walking",
        "skitouring",
        "swimming",
        "running",
        "citybike",
    }
    assert expected == sports


@pytest.mark.asyncio
async def test_clear_seed_activities(
    async_client: AsyncClient,
    free_user_headers: dict,
) -> None:
    await async_client.post("/api/v1/activities/seed", headers=free_user_headers)
    response = await async_client.delete("/api/v1/activities/seed/clear", headers=free_user_headers)
    assert response.status_code == 200
    assert response.json()["deleted"] == 12

    # List should now be empty
    list_response = await async_client.get(
        "/api/v1/activities?limit=100", headers=free_user_headers
    )
    assert list_response.json()["count"] == 0


# ── GPX import ────────────────────────────────────────────────────────────────

_MINIMAL_GPX = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <gpx version="1.1" creator="test"
         xmlns="http://www.topografix.com/GPX/1/1">
      <metadata><name>Test Hike</name></metadata>
      <trk>
        <name>Test Hike</name>
        <trkseg>
          <trkpt lat="47.3769" lon="8.5417">
            <ele>400</ele>
            <time>2026-01-15T08:00:00Z</time>
          </trkpt>
          <trkpt lat="47.3800" lon="8.5450">
            <ele>450</ele>
            <time>2026-01-15T08:30:00Z</time>
          </trkpt>
          <trkpt lat="47.3850" lon="8.5500">
            <ele>500</ele>
            <time>2026-01-15T09:00:00Z</time>
          </trkpt>
        </trkseg>
      </trk>
    </gpx>
""")


@pytest.mark.asyncio
async def test_gpx_import_creates_activity(
    async_client: AsyncClient,
    free_user_headers: dict,
) -> None:
    response = await async_client.post(
        "/api/v1/activities/import",
        headers=free_user_headers,
        files=[("files", ("test.gpx", io.BytesIO(_MINIMAL_GPX.encode()), "application/gpx+xml"))],
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["created"]) == 1
    assert body["errors"] == []
    assert body["created"][0]["name"] == "Test Hike"


@pytest.mark.asyncio
async def test_gpx_import_rejects_non_gpx(
    async_client: AsyncClient,
    free_user_headers: dict,
) -> None:
    response = await async_client.post(
        "/api/v1/activities/import",
        headers=free_user_headers,
        files=[("files", ("workout.fit", io.BytesIO(b"FIT"), "application/octet-stream"))],
    )
    assert response.status_code == 201
    body = response.json()
    assert body["created"] == []
    assert len(body["errors"]) == 1
    assert "Not a .gpx file" in body["errors"][0]["error"]


@pytest.mark.asyncio
async def test_gpx_import_activity_has_import_source(
    async_client: AsyncClient,
    free_user_headers: dict,
) -> None:
    await async_client.post(
        "/api/v1/activities/import",
        headers=free_user_headers,
        files=[("files", ("test.gpx", io.BytesIO(_MINIMAL_GPX.encode()), "application/gpx+xml"))],
    )
    list_resp = await async_client.get("/api/v1/activities?limit=10", headers=free_user_headers)
    activities = list_resp.json()["data"]
    assert len(activities) == 1
    assert activities[0]["source"] == "import"
    assert activities[0]["sync_direction"] is None


# ── Delete ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_imported_activity(
    async_client: AsyncClient,
    free_user_headers: dict,
) -> None:
    import_resp = await async_client.post(
        "/api/v1/activities/import",
        headers=free_user_headers,
        files=[("files", ("test.gpx", io.BytesIO(_MINIMAL_GPX.encode()), "application/gpx+xml"))],
    )
    activity_id = import_resp.json()["created"][0]["id"]

    delete_resp = await async_client.delete(
        f"/api/v1/activities/{activity_id}", headers=free_user_headers
    )
    assert delete_resp.status_code == 200
    body = delete_resp.json()
    assert "deleted_from" in body
    assert "failed" in body

    # Confirm gone
    get_resp = await async_client.get(
        f"/api/v1/activities/{activity_id}", headers=free_user_headers
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_synced_activity_cascades(
    async_client: AsyncClient,
    free_user_headers: dict,
    db: AsyncSession,
    free_user: User,
) -> None:
    """Deleting any activity (including synced ones) removes it locally and reports cascade."""
    act = SyncedActivity(
        user_id=free_user.id,
        source="komoot",
        komoot_tour_id="real_tour_123",
        sync_direction="komoot_to_strava",
        sync_status="completed",
        activity_name="Real Komoot Tour",
        synced_at=datetime.now(UTC),
    )
    db.add(act)
    await db.commit()

    response = await async_client.delete(f"/api/v1/activities/{act.id}", headers=free_user_headers)
    assert response.status_code == 200
    body = response.json()
    assert "deleted_from" in body
    assert "failed" in body

    # Confirm gone locally
    get_resp = await async_client.get(f"/api/v1/activities/{act.id}", headers=free_user_headers)
    assert get_resp.status_code == 404

from __future__ import annotations

import gzip
import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sync import SyncedActivity

_GPX = b"""<?xml version="1.0"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
  <trk><trkseg>
    <trkpt lat="47.000" lon="8.000"><ele>400</ele><time>2026-07-21T10:00:00Z</time>
      <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>140</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions>
    </trkpt>
    <trkpt lat="47.010" lon="8.000"><ele>440</ele><time>2026-07-21T10:05:00Z</time>
      <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>160</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions>
    </trkpt>
    <trkpt lat="47.020" lon="8.000"><ele>420</ele><time>2026-07-21T10:10:00Z</time>
      <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>150</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions>
    </trkpt>
  </trkseg></trk>
</gpx>"""


async def _make_gpx_activity(db: AsyncSession, user, **extra) -> SyncedActivity:
    act = SyncedActivity(
        user_id=user.id,
        source="import",
        sync_status="completed",
        activity_name="Test Hike",
        sport_type="hiking",
        gpx_data=_GPX,
        **extra,
    )
    db.add(act)
    await db.commit()
    await db.refresh(act)
    return act


@pytest.mark.asyncio
async def test_metrics_endpoint_before_computation(
    async_client: AsyncClient, free_user, free_user_headers: dict, db: AsyncSession
):
    act = await _make_gpx_activity(db, free_user)
    r = await async_client.get(f"/api/v1/activities/{act.id}/metrics", headers=free_user_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["computed"] is False
    assert body["available"] == []


@pytest.mark.asyncio
async def test_compute_job_populates_metrics_and_endpoint(
    free_user, db: AsyncSession, async_client: AsyncClient, free_user_headers: dict
):
    from app.jobs.sync_jobs import compute_activity_metrics

    act = await _make_gpx_activity(db, free_user)

    # The job opens its own session via AsyncSessionLocal — point it at the test DB.
    def _factory():
        return db  # reuse the test session (context-manager compatible)

    class _CtxDB:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *a):
            return False

    from unittest.mock import patch

    with patch("app.jobs.sync_jobs.AsyncSessionLocal", lambda: _CtxDB()):
        await compute_activity_metrics({}, str(act.id))

    await db.refresh(act)
    assert act.metrics_computed_at is not None
    assert act.avg_hr == pytest.approx(150, abs=2)
    assert act.metrics_available and "heartrate" in act.metrics_available
    assert act.elevation_up_m and act.elevation_up_m > 0
    assert act.track_gz is not None

    # endpoint now reports computed metrics
    r = await async_client.get(f"/api/v1/activities/{act.id}/metrics", headers=free_user_headers)
    body = r.json()
    assert body["computed"] is True
    assert body["summary"]["avg_hr"] == pytest.approx(150, abs=2)

    # track endpoint returns points
    tr = await async_client.get(f"/api/v1/activities/{act.id}/track", headers=free_user_headers)
    tbody = tr.json()
    assert tbody["computed"] is True
    assert len(tbody["points"]) == 3
    assert tbody["points"][0]["hr"] == pytest.approx(140, abs=1)


@pytest.mark.asyncio
async def test_track_endpoint_gzip_roundtrip(
    async_client: AsyncClient, free_user, free_user_headers: dict, db: AsyncSession
):
    points = [{"t": 0, "ele": 400, "hr": 140}, {"t": 60, "ele": 420, "hr": 150}]
    act = await _make_gpx_activity(
        db, free_user, track_gz=gzip.compress(json.dumps(points).encode())
    )
    r = await async_client.get(f"/api/v1/activities/{act.id}/track", headers=free_user_headers)
    assert r.status_code == 200
    assert r.json()["points"] == points


@pytest.mark.asyncio
async def test_metrics_endpoint_404_for_other_user(
    async_client: AsyncClient, pro_user, free_user_headers: dict, db: AsyncSession
):
    act = await _make_gpx_activity(db, pro_user)
    r = await async_client.get(f"/api/v1/activities/{act.id}/metrics", headers=free_user_headers)
    assert r.status_code == 404

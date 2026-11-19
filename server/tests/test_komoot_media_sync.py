"""Tests for Komoot -> Strava title, description, and photo syncing."""

from __future__ import annotations

from datetime import datetime

from routepass.db import session_scope
from routepass.engine import sync
from routepass.models import Activity, ProviderActivity, SyncJob


class _FakeKomoot:
    def __init__(self) -> None:
        self.gpx_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def gpx(self, tour_id: str) -> bytes:
        self.gpx_calls += 1
        return b"<gpx version='1.1'></gpx>"

    def tour_details(self, tour_id: str) -> dict:
        return {
            "id": tour_id,
            "name": "Alpine Ridge Trail",
            "description": "Steep climb up to the ridge, sunny views!",
            "raw": {},
        }

    def tour_photos(self, tour_id: str) -> list[dict]:
        return [
            {"id": "p1", "url": "https://photos.komoot.de/p1.jpg", "caption": "Summit view", "lat": 47.1, "lng": 10.2},
            {"id": "p2", "url": "https://photos.komoot.de/p2.jpg", "caption": "Trailhead", "lat": 47.0, "lng": 10.1},
        ]

    def download_photo(self, url: str) -> tuple[bytes, str]:
        return b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg"


class _FakeStrava:
    def __init__(self) -> None:
        self.uploads: list[dict] = []
        self.updates: list[dict] = []
        self.photos: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def upload_gpx(self, gpx: bytes, name: str, description: str, sport_type: str, external_id: str) -> str:
        self.uploads.append({"name": name, "description": description, "sport": sport_type, "external_id": external_id})
        return "up-1"

    def wait_for_upload(self, upload_id: str) -> str:
        return "strava-999"

    def update_activity(self, activity_id: str, **fields):
        self.updates.append({"activity_id": activity_id, **fields})
        return {"id": activity_id, **fields}

    def upload_photo(
        self,
        activity_id: str,
        image_bytes: bytes,
        *,
        filename: str = "photo.jpg",
        content_type: str = "image/jpeg",
        caption: str = "",
    ):
        self.photos.append({"activity_id": activity_id, "filename": filename, "caption": caption, "size": len(image_bytes)})
        return {"id": f"ph-{len(self.photos)}"}


def test_komoot_to_strava_copies_description_and_photos(db):
    fk = _FakeKomoot()
    fs = _FakeStrava()
    with session_scope() as s:
        job = SyncJob(
            activity_id=1,
            direction="komoot_to_strava",
            source_provider="komoot",
            source_id="k-123",
            target_provider="strava",
            plan={"name": "Alpine Ridge Trail", "description": "", "sport": "TrailRun"},
            reason="rule match",
            status="running",
        )
        aid = sync._komoot_to_strava(s, job, fk, fs)
        assert aid == "strava-999"
        assert len(fs.uploads) == 1
        assert fs.uploads[0]["description"] == "Steep climb up to the ridge, sunny views!"
        assert len(fs.updates) == 1
        assert fs.updates[0]["description"] == "Steep climb up to the ridge, sunny views!"
        assert len(fs.photos) == 2
        assert fs.photos[0]["caption"] == "Summit view"
        assert "2 photo(s) synced" in job.reason


def test_sync_komoot_media_endpoint_and_photo_deduplication(client, monkeypatch):
    fk = _FakeKomoot()
    fs = _FakeStrava()
    monkeypatch.setattr(sync, "komoot_client", lambda _db: fk)
    monkeypatch.setattr(sync, "strava_client", lambda _db: fs)

    with session_scope() as s:
        act = Activity(
            start_time=datetime(2026, 7, 1, 8, 0),
            start_local=datetime(2026, 7, 1, 10, 0),
            name="Old Strava Title",
            sport="TrailRun",
            family="run",
            distance_m=18000,
            moving_time_s=6200,
            elevation_gain_m=900,
        )
        s.add(act)
        s.flush()
        s.add(
            ProviderActivity(
                activity_id=act.id,
                provider="komoot",
                external_id="k-555",
                name="Alpine Ridge Trail",
                sport="TrailRun",
                start_time=act.start_time,
                raw={"id": "k-555"},
            )
        )
        s.add(
            ProviderActivity(
                activity_id=act.id,
                provider="strava",
                external_id="s-777",
                name="Old Strava Title",
                sport="TrailRun",
                start_time=act.start_time,
                raw={"id": "s-777"},
            )
        )
        s.flush()
        act_id = act.id

    headers = {"Authorization": "Bearer test-token"}
    r1 = client.post(
        f"/api/v1/activities/{act_id}/sync-komoot-media",
        headers=headers,
        json={"sync_title": True, "sync_description": True, "sync_photos": True},
    )
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["title_synced"] is True
    assert d1["description_synced"] is True
    assert d1["photos_found"] == 2
    assert d1["photos_uploaded"] == 2
    assert d1["photos_skipped_existing"] == 0

    # Second run should not re-upload already-synced photos
    r2 = client.post(
        f"/api/v1/activities/{act_id}/sync-komoot-media",
        headers=headers,
        json={"sync_title": False, "sync_description": False, "sync_photos": True},
    )
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["photos_uploaded"] == 0
    assert d2["photos_skipped_existing"] == 2

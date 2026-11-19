"""Tests for Phase 3 (Google Calendar slot-finding & config) and Phase 4 (PWA Web Push VAPID + RFC 8291)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from routepass import push
from routepass.db import session_scope
from routepass.main import create_app
from routepass.providers import gcal


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_gcal_free_slot_finder_respects_busy_and_buffer():
    tz = ZoneInfo("Europe/Berlin")
    day = date(2026, 7, 8)  # Wednesday
    # Busy from 17:45 to 19:00 -> with 20m buffer, blocked 17:25..19:20
    busy = [
        (datetime(2026, 7, 8, 17, 45, tzinfo=tz), datetime(2026, 7, 8, 19, 0, tzinfo=tz)),
    ]
    slot = gcal.find_free_slot(
        day,
        duration_s=3600,
        preferred_slot="evening",
        busy=busy,
        tz_name="Europe/Berlin",
        buffer_minutes=20,
    )
    assert slot is not None
    start_dt, end_dt = slot
    # Should place at 19:30..20:30 (snapped to 15m after 19:20 buffer)
    assert start_dt.hour == 19 and start_dt.minute == 30
    assert end_dt - start_dt == timedelta(hours=1)

    # If the entire evening is booked, falls back cleanly to morning window (06:00..08:30)
    busy_all_evening = [
        (datetime(2026, 7, 8, 17, 0, tzinfo=tz), datetime(2026, 7, 8, 21, 30, tzinfo=tz)),
    ]
    slot2 = gcal.find_free_slot(
        day,
        duration_s=3600,
        preferred_slot="evening",
        busy=busy_all_evening,
        tz_name="Europe/Berlin",
        buffer_minutes=15,
    )
    assert slot2 is not None
    assert slot2[0].hour == 6 and slot2[0].minute == 0


def test_push_vapid_and_rfc8291_encryption(db):
    with session_scope() as s:
        keys = push.ensure_vapid_keys(s)
        assert len(keys["public_key"]) > 60
        assert "BEGIN PRIVATE KEY" in keys["private_pem"]
        # Subsequent call returns same persisted keypair
        assert push.ensure_vapid_keys(s)["public_key"] == keys["public_key"]

    # Generate fake browser P-256 subscription keys and verify RFC 8291 aes128gcm encryption runs cleanly
    ua_priv = ec.generate_private_key(ec.SECP256R1())
    ua_pub = ua_priv.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    encrypted = push.encrypt_rfc8291(
        b'{"title":"Test","body":"Hello"}',
        push._b64u_encode(ua_pub),
        push._b64u_encode(b"0123456789abcdef"),
    )
    # Header is 16 (salt) + 4 (rs) + 1 (idlen=65) + 65 (as_pub) = 86 bytes + ciphertext
    assert len(encrypted) > 86
    assert encrypted[20] == 65


def test_calendar_and_push_rest_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTEPASS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ROUTEPASS_API_TOKEN", "test-token")
    from routepass.config import get_settings

    get_settings.cache_clear()
    app = create_app(start_scheduler=False)

    with TestClient(app) as client:
        # Google Calendar status & config
        r = client.get("/api/v1/connections/google-calendar", headers=_auth_headers())
        assert r.status_code == 200
        assert r.json()["connected"] is False

        r2 = client.put(
            "/api/v1/connections/google-calendar/config",
            headers=_auth_headers(),
            json={
                "target_calendar_id": "training@group.calendar.google.com",
                "busy_calendar_ids": ["primary", "work@example.com"],
                "buffer_minutes": 25,
                "timezone": "Europe/Berlin",
            },
        )
        assert r2.status_code == 200
        assert r2.json()["buffer_minutes"] == 25
        assert len(r2.json()["busy_calendar_ids"]) == 2

        # Push config & subscription
        rp = client.get("/api/v1/push/config", headers=_auth_headers())
        assert rp.status_code == 200
        assert rp.json()["vapid_public_key"]
        assert rp.json()["subscriptions"] == 0

        ua_priv = ec.generate_private_key(ec.SECP256R1())
        ua_pub = push._b64u_encode(
            ua_priv.public_key().public_bytes(
                encoding=serialization.Encoding.X962,
                format=serialization.PublicFormat.UncompressedPoint,
            )
        )
        rs = client.post(
            "/api/v1/push/subscribe",
            headers=_auth_headers(),
            json={
                "endpoint": "https://push.example.test/sub/1",
                "keys": {"p256dh": ua_pub, "auth": push._b64u_encode(b"0123456789abcdef")},
            },
        )
        assert rs.status_code == 200
        assert rs.json()["subscriptions"] == 1

        # Quiet hours helper check
        assert push._in_quiet_hours(
            {"quiet_start_hour": 22, "quiet_end_hour": 7, "timezone": "UTC"},
            datetime(2026, 7, 8, 23, 30, tzinfo=UTC),
        ) is True
        assert push._in_quiet_hours(
            {"quiet_start_hour": 22, "quiet_end_hour": 7, "timezone": "UTC"},
            datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
        ) is False

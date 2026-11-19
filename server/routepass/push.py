"""Standards-compliant PWA Web Push (VAPID RFC 8292 + aes128gcm RFC 8291).

Zero extra dependencies — uses `cryptography`, `PyJWT`, and `httpx` already in RoutePass.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import struct
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select
from sqlalchemy.orm import Session

from routepass import store
from routepass.config import get_settings
from routepass.models import NotificationLog, PushSubscription, TrainingPlan, TrainingSession

logger = logging.getLogger(__name__)

_VAPID_SECRET_KEY = "push.vapid"
_PREFS_KEY = "push.prefs"

DEFAULT_PUSH_PREFS: dict[str, Any] = {
    "enabled": True,
    "reminder_minutes_before": 60,
    "notify_adapted": True,
    "notify_completed": True,
    "quiet_start_hour": 22,
    "quiet_end_hour": 7,
    "timezone": "Europe/Berlin",
}


def _b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def ensure_vapid_keys(db: Session) -> dict[str, str]:
    """Return persisted P-256 VAPID keypair (`private_pem`, `public_key`), generating once if needed."""
    existing = store.get_secret(db, _VAPID_SECRET_KEY)
    if existing and existing.get("private_pem") and existing.get("public_key"):
        return existing

    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    pair = {"private_pem": priv_pem, "public_key": _b64u_encode(pub_raw)}
    store.set_secret(db, _VAPID_SECRET_KEY, pair)
    return pair


def get_prefs(db: Session) -> dict[str, Any]:
    raw = store.get_value(db, _PREFS_KEY) or {}
    subs_count = len(list(db.scalars(select(PushSubscription.id))))
    return {
        **DEFAULT_PUSH_PREFS,
        **raw,
        "subscriptions": subs_count,
        "vapid_public_key": ensure_vapid_keys(db)["public_key"],
    }


def save_prefs(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    cur = dict(store.get_value(db, _PREFS_KEY) or {})
    for k in DEFAULT_PUSH_PREFS:
        if k in patch and patch[k] is not None:
            cur[k] = patch[k]
    store.set_value(db, _PREFS_KEY, cur)
    return get_prefs(db)


def save_subscription(
    db: Session, *, endpoint: str, p256dh: str, auth_secret: str, user_agent: str = ""
) -> PushSubscription:
    existing = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if existing:
        existing.p256dh = p256dh
        existing.auth = auth_secret
        existing.user_agent = user_agent[:240]
        db.flush()
        return existing
    row = PushSubscription(
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth_secret,
        user_agent=user_agent[:240],
    )
    db.add(row)
    db.flush()
    return row


def delete_subscription(db: Session, endpoint: str) -> bool:
    row = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def encrypt_rfc8291(plaintext: bytes, ua_pub_b64: str, auth_b64: str) -> bytes:
    """Encrypt push payload using RFC 8291 (`aes128gcm` content encoding)."""
    ua_pub_bytes = _b64u_decode(ua_pub_b64)
    auth_secret = _b64u_decode(auth_b64)
    ua_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub_bytes)

    as_priv = ec.generate_private_key(ec.SECP256R1())
    as_pub_bytes = as_priv.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    shared = as_priv.exchange(ec.ECDH(), ua_pub)
    salt = os.urandom(16)

    # RFC 8291 §3.3 IKM derivation
    ikm_info = b"WebPush: info\x00" + ua_pub_bytes + as_pub_bytes
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth_secret, info=ikm_info).derive(shared)

    cek = HKDF(
        algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00"
    ).derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(
        ikm
    )

    # Delimiter byte 0x02 marks final record
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    header = salt + struct.pack("!IB", 4096, len(as_pub_bytes)) + as_pub_bytes
    return header + ciphertext


def _vapid_headers(endpoint: str, vapid: dict[str, str]) -> dict[str, str]:
    parsed = urlparse(endpoint)
    aud = f"{parsed.scheme}://{parsed.netloc}"
    sub_email = get_settings().allowed_emails.split(",")[0].strip() if get_settings().allowed_emails else ""
    sub = f"mailto:{sub_email}" if "@" in sub_email else "mailto:routepass@localhost"
    token = jwt.encode(
        {"aud": aud, "exp": int(time.time()) + 12 * 3600, "sub": sub},
        vapid["private_pem"],
        algorithm="ES256",
    )
    return {
        "Authorization": f"vapid t={token}, k={vapid['public_key']}",
        "TTL": "3600",
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
    }


def _in_quiet_hours(prefs: dict[str, Any], now_utc: datetime | None = None) -> bool:
    now_utc = now_utc or datetime.now(UTC)
    try:
        tz = ZoneInfo(str(prefs.get("timezone") or "Europe/Berlin"))
    except Exception:  # noqa: BLE001
        tz = UTC
    hr = now_utc.astimezone(tz).hour
    qs = int(prefs.get("quiet_start_hour", 22))
    qe = int(prefs.get("quiet_end_hour", 7))
    if qs > qe:
        return hr >= qs or hr < qe
    return qs <= hr < qe


def send_notification(
    db: Session,
    *,
    title: str,
    body: str,
    url: str = "/insights/training",
    kind: str = "general",
    dedup_key: str | None = None,
    ignore_quiet: bool = False,
) -> dict[str, int]:
    """Send a Web Push notification to all subscribed browsers."""
    prefs = get_prefs(db)
    if not ignore_quiet and (not prefs.get("enabled", True) or _in_quiet_hours(prefs)):
        return {"sent": 0, "failed": 0, "skipped_quiet": 1}

    if dedup_key:
        if db.scalar(select(NotificationLog.id).where(NotificationLog.dedup_key == dedup_key)):
            return {"sent": 0, "failed": 0, "skipped_dedup": 1}

    subs = list(db.scalars(select(PushSubscription)))
    if not subs:
        return {"sent": 0, "failed": 0}

    vapid = ensure_vapid_keys(db)
    payload_bytes = json.dumps({"title": title, "body": body, "url": url, "tag": kind}).encode("utf-8")

    sent = failed = removed = 0
    with httpx.Client(timeout=15) as client:
        for sub in subs:
            try:
                encrypted = encrypt_rfc8291(payload_bytes, sub.p256dh, sub.auth)
                headers = _vapid_headers(sub.endpoint, vapid)
                resp = client.post(sub.endpoint, content=encrypted, headers=headers)
                if resp.status_code in (404, 410):
                    db.delete(sub)
                    removed += 1
                elif resp.status_code < 400:
                    sent += 1
                else:
                    failed += 1
                    logger.warning("Push endpoint returned %s: %s", resp.status_code, resp.text[:160])
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning("Push send failed: %s", exc)

    if dedup_key and sent > 0:
        db.add(NotificationLog(dedup_key=dedup_key, kind=kind, title=title[:200], body=body[:500]))
    db.flush()
    return {"sent": sent, "failed": failed, "removed": removed}


def dispatch_due_reminders(db: Session, *, now_utc: datetime | None = None) -> dict[str, int]:
    """Send pre-workout push reminders for sessions starting within `reminder_minutes_before`."""
    prefs = get_prefs(db)
    if not prefs.get("enabled", True) or _in_quiet_hours(prefs, now_utc):
        return {"sent": 0}
    now_utc = now_utc or datetime.now(UTC)
    lead = timedelta(minutes=int(prefs.get("reminder_minutes_before", 60)))

    active_ids = list(db.scalars(select(TrainingPlan.id).where(TrainingPlan.status == "active")))
    if not active_ids:
        return {"sent": 0}

    sessions = list(
        db.scalars(
            select(TrainingSession).where(
                TrainingSession.plan_id.in_(active_ids),
                TrainingSession.status.in_(("planned", "moved")),
                TrainingSession.scheduled_start.is_not(None),
            )
        )
    )
    total_sent = 0
    for s in sessions:
        try:
            start_dt = datetime.fromisoformat(str(s.scheduled_start)).astimezone(UTC)
        except ValueError:
            continue
        if now_utc <= start_dt <= now_utc + lead:
            mins = max(1, round((start_dt - now_utc).total_seconds() / 60))
            res = send_notification(
                db,
                title=f"Upcoming: {s.title}",
                body=f"Starts in ~{mins} min · {round(s.target_duration_s / 60)}m ({s.sport.replace('_', ' ')})",
                url="/insights/training",
                kind="reminder",
                dedup_key=f"reminder:{s.id}:{s.scheduled_start}",
            )
            total_sent += res.get("sent", 0)
    return {"sent": total_sent}

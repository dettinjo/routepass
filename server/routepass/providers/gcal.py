"""Google Calendar integration for adaptive multi-sport Training Plans.

Supports:
- OAuth2 offline connection reusing RoutePass's Google client credentials.
- Selecting your dedicated training calendar (or creating "RoutePass Training").
- Connecting multiple personal/work calendars for read-only `freeBusy` lookup.
- Smart free-slot finder respecting morning/midday/afternoon/evening windows & buffers.
- Two-way-aware rolling sync: creates, updates, marks completed (`✅`), or moves events
  automatically when workouts are adapted or missed.
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from routepass import auth, store
from routepass.config import get_settings
from routepass.models import TrainingPlan, TrainingSession

logger = logging.getLogger(__name__)

GCAL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GCAL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GCAL_API = "https://www.googleapis.com/calendar/v3"
GCAL_SCOPES = (
    "https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events"
)
# Reuse the same OAuth callback path already registered for Google Sign-In
# (disambiguated by signed `state.kind == "gcal"`), preventing redirect_uri_mismatch.
GCAL_CALLBACK_PATH = "/api/v1/auth/google/callback"

_SECRET_KEY = "gcal.credentials"
_CONFIG_KEY = "gcal.config"

DEFAULT_SLOT_WINDOWS: dict[str, tuple[str, str]] = {
    "morning": ("06:00", "08:30"),
    "midday": ("11:30", "14:00"),
    "afternoon": ("15:00", "17:30"),
    "evening": ("17:30", "21:00"),
    "weekend": ("07:30", "18:00"),
}

DEFAULT_GCAL_CONFIG: dict[str, Any] = {
    "target_calendar_id": None,
    "target_calendar_name": None,
    "busy_calendar_ids": [],
    "timezone": "Europe/Berlin",
    "buffer_minutes": 20,
    "auto_sync": True,
    "slot_windows": {k: list(v) for k, v in DEFAULT_SLOT_WINDOWS.items()},
}


class GCalError(RuntimeError):
    """Raised when Google Calendar API or OAuth fails."""


def _client_creds(db: Session) -> tuple[str, str]:
    s = get_settings()
    cid = s.google_client_id.strip()
    csec = s.google_client_secret.strip()
    if not cid or not csec:
        custom = store.get_secret(db, "gcal.app") or {}
        cid = cid or str(custom.get("client_id") or "").strip()
        csec = csec or str(custom.get("client_secret") or "").strip()
    return cid, csec


def redirect_uri() -> str:
    s = get_settings()
    base = (s.public_url or s.base_url).rstrip("/")
    return f"{base}{GCAL_CALLBACK_PATH}"


def get_config(db: Session) -> dict[str, Any]:
    raw = store.get_value(db, _CONFIG_KEY) or {}
    cfg = {**DEFAULT_GCAL_CONFIG, **raw}
    cfg["slot_windows"] = {**DEFAULT_GCAL_CONFIG["slot_windows"], **(raw.get("slot_windows") or {})}
    creds = store.get_secret(db, _SECRET_KEY)
    cid, csec = _client_creds(db)
    return {
        **cfg,
        "oauth_configured": bool(cid and csec),
        "connected": bool(creds and creds.get("refresh_token")),
        "redirect_uri": redirect_uri(),
        "connected_at": creds.get("connected_at") if creds else None,
    }


def save_config(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    cur = dict(store.get_value(db, _CONFIG_KEY) or {})
    for k in (
        "target_calendar_id",
        "target_calendar_name",
        "busy_calendar_ids",
        "timezone",
        "buffer_minutes",
        "auto_sync",
        "slot_windows",
    ):
        if k in patch and patch[k] is not None:
            cur[k] = patch[k]
    store.set_value(db, _CONFIG_KEY, cur)
    return get_config(db)


def save_oauth_app(db: Session, client_id: str, client_secret: str) -> dict[str, Any]:
    store.set_secret(db, "gcal.app", {"client_id": client_id.strip(), "client_secret": client_secret.strip()})
    return get_config(db)


def start_authorize(db: Session) -> tuple[str, str]:
    cid, csec = _client_creds(db)
    if not cid or not csec:
        raise GCalError("Google OAuth client_id / client_secret not configured")
    state = auth.sign({"nonce": secrets.token_urlsafe(12), "exp": time.time() + 900, "kind": "gcal"})
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": GCAL_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GCAL_AUTH_URL}?{urlencode(params)}", redirect_uri()


def exchange_code(db: Session, code: str, state: str | None = None) -> dict[str, Any]:
    if state is not None:
        parsed = auth.unsign(state)
        if not parsed or parsed.get("kind") != "gcal":
            raise GCalError("Invalid or expired OAuth state")
    cid, csec = _client_creds(db)
    if not cid or not csec:
        raise GCalError("Google OAuth client credentials missing")
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            GCAL_TOKEN_URL,
            data={
                "client_id": cid,
                "client_secret": csec,
                "code": code.strip(),
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(),
            },
        )
    if resp.status_code >= 400:
        raise GCalError(f"Token exchange failed ({resp.status_code}): {resp.text[:240]}")
    tok = resp.json()
    existing = store.get_secret(db, _SECRET_KEY) or {}
    refresh = tok.get("refresh_token") or existing.get("refresh_token")
    if not refresh:
        raise GCalError("Google did not return a refresh token — try reconnecting with consent.")
    store.set_secret(
        db,
        _SECRET_KEY,
        {
            "access_token": tok["access_token"],
            "refresh_token": refresh,
            "expires_at": time.time() + int(tok.get("expires_in", 3500)) - 60,
            "connected_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
    )
    return get_config(db)


def disconnect(db: Session) -> dict[str, Any]:
    store.delete_value(db, _SECRET_KEY)
    return get_config(db)


def _access_token(db: Session) -> str:
    creds = store.get_secret(db, _SECRET_KEY)
    if not creds or not creds.get("refresh_token"):
        raise GCalError("Google Calendar is not connected")
    if creds.get("access_token") and float(creds.get("expires_at", 0)) > time.time():
        return str(creds["access_token"])
    cid, csec = _client_creds(db)
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            GCAL_TOKEN_URL,
            data={
                "client_id": cid,
                "client_secret": csec,
                "refresh_token": creds["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
    if resp.status_code >= 400:
        raise GCalError(f"Failed to refresh Google token ({resp.status_code}): {resp.text[:200]}")
    tok = resp.json()
    creds["access_token"] = tok["access_token"]
    creds["expires_at"] = time.time() + int(tok.get("expires_in", 3500)) - 60
    store.set_secret(db, _SECRET_KEY, creds)
    return str(creds["access_token"])


def list_calendars(db: Session) -> list[dict[str, Any]]:
    token = _access_token(db)
    with httpx.Client(timeout=20) as client:
        resp = client.get(
            f"{GCAL_API}/users/me/calendarList",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code >= 400:
        raise GCalError(f"Failed to list calendars ({resp.status_code}): {resp.text[:200]}")
    items = resp.json().get("items") or []
    return [
        {
            "id": c["id"],
            "summary": c.get("summary") or c["id"],
            "primary": bool(c.get("primary")),
            "access_role": c.get("accessRole", "reader"),
            "color": c.get("backgroundColor"),
        }
        for c in items
    ]


def create_training_calendar(db: Session, name: str = "RoutePass Training") -> dict[str, Any]:
    token = _access_token(db)
    cfg = get_config(db)
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            f"{GCAL_API}/calendars",
            headers={"Authorization": f"Bearer {token}"},
            json={"summary": name, "timeZone": cfg["timezone"]},
        )
    if resp.status_code >= 400:
        raise GCalError(f"Failed to create calendar ({resp.status_code}): {resp.text[:200]}")
    cal = resp.json()
    save_config(db, {"target_calendar_id": cal["id"], "target_calendar_name": cal.get("summary") or name})
    return {"id": cal["id"], "summary": cal.get("summary") or name}


def query_free_busy(
    db: Session,
    calendar_ids: list[str],
    time_min: datetime,
    time_max: datetime,
) -> list[tuple[datetime, datetime]]:
    """Return sorted merged list of busy `(start, end)` aware datetimes across all given calendars."""
    if not calendar_ids:
        return []
    token = _access_token(db)
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            f"{GCAL_API}/freeBusy",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "timeMin": time_min.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "timeMax": time_max.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "items": [{"id": cid} for cid in dict.fromkeys(calendar_ids)],
            },
        )
    if resp.status_code >= 400:
        raise GCalError(f"freeBusy query failed ({resp.status_code}): {resp.text[:200]}")
    cals = resp.json().get("calendars") or {}
    raw_intervals: list[tuple[datetime, datetime]] = []
    for data in cals.values():
        for b in data.get("busy") or []:
            s = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
            if e > s:
                raw_intervals.append((s, e))
    return _merge_intervals(raw_intervals)


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda x: x[0])
    merged = [ordered[0]]
    for s, e in ordered[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


def _parse_hhmm(s: str) -> dt_time:
    h, m = s.split(":")
    return dt_time(int(h), int(m))


def find_free_slot(
    day: date,
    duration_s: float,
    preferred_slot: str,
    busy: list[tuple[datetime, datetime]],
    *,
    tz_name: str = "Europe/Berlin",
    buffer_minutes: int = 20,
    slot_windows: dict[str, list[str]] | None = None,
) -> tuple[datetime, datetime] | None:
    """Find the best conflict-free `(start, end)` datetime on `day` matching `preferred_slot`."""
    tz = ZoneInfo(tz_name)
    windows = slot_windows or {k: list(v) for k, v in DEFAULT_SLOT_WINDOWS.items()}
    dur = timedelta(seconds=max(900, int(duration_s)))
    buf = timedelta(minutes=max(0, int(buffer_minutes)))

    # Expand busy intervals by buffer on both sides
    expanded = _merge_intervals([(s.astimezone(tz) - buf, e.astimezone(tz) + buf) for s, e in busy])

    is_weekend = day.weekday() >= 5
    order: list[str] = []
    if is_weekend:
        order.append("weekend")
    if preferred_slot in windows and preferred_slot not in order:
        order.append(preferred_slot)
    for fallback in ("evening", "morning", "afternoon", "midday"):
        if fallback in windows and fallback not in order:
            order.append(fallback)

    for wname in order:
        w_start_s, w_end_s = windows[wname]
        w_start = datetime.combine(day, _parse_hhmm(w_start_s), tzinfo=tz)
        w_end = datetime.combine(day, _parse_hhmm(w_end_s), tzinfo=tz)
        if w_end - w_start < dur:
            # Allow long weekend runs/rides to extend slightly past window end if start is open
            if is_weekend and wname == "weekend":
                w_end = max(w_end, w_start + dur)
            else:
                continue

        cursor = w_start
        for bs, be in expanded:
            if be <= cursor:
                continue
            if bs >= cursor + dur:
                return (cursor, cursor + dur)
            cursor = max(cursor, be)
            # Snap cursor up to next 15-min boundary for clean calendar starts
            rem = cursor.minute % 15
            if rem:
                cursor += timedelta(minutes=15 - rem)
            if cursor + dur > w_end:
                break
        if cursor + dur <= w_end:
            return (cursor, cursor + dur)

    return None


def _event_body(
    plan: TrainingPlan, s: TrainingSession, start_dt: datetime, end_dt: datetime
) -> dict[str, Any]:
    prefix = "✅ " if s.status == "completed" else ("↻ " if s.status == "moved" else "")
    title = f"{prefix}[{s.sport.replace('_', ' ').title()}] {s.title}"
    lines = [
        f"Plan: {plan.name}",
        f"Priority: {s.priority.upper()} · Type: {s.session_type}",
        f"Target: {round(s.target_duration_s / 60)} min"
        + (f" · {s.target_distance_km:.1f} km" if s.target_distance_km else "")
        + (f" · +{int(s.target_elev_m)} m" if s.target_elev_m else "")
        + (f" · {int(s.target_tss)} TSS" if s.target_tss else ""),
    ]
    if s.description:
        lines.append("")
        lines.append(s.description)
    if s.workout_steps:
        lines.append("")
        lines.append("Workout steps:")
        lines.extend(f"• {st}" for st in s.workout_steps)
    if s.adaptation_note:
        lines.append("")
        lines.append(f"Coach note: {s.adaptation_note}")
    base_url = get_settings().base_url.rstrip("/")
    lines.append("")
    lines.append(f"Open in RoutePass: {base_url}/insights/training")
    return {
        "summary": title,
        "description": "\n".join(lines),
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
    }


def sync_plan_to_calendar(
    db: Session,
    plan: TrainingPlan,
    *,
    today: date | None = None,
    horizon_days: int = 14,
) -> dict[str, Any]:
    """Sync upcoming 14 days (plus recent 2 days) of `plan` to the dedicated Google Calendar."""
    cfg = get_config(db)
    if not cfg["connected"]:
        raise GCalError("Google Calendar is not connected")
    target_cal = cfg.get("target_calendar_id")
    if not target_cal:
        raise GCalError("No target training calendar selected in Settings → Google Calendar")

    today = today or date.today()
    tz = ZoneInfo(cfg["timezone"])
    win_start = today - timedelta(days=2)
    win_end = today + timedelta(days=horizon_days)

    sessions = list(
        db.scalars(
            select(TrainingSession)
            .where(
                TrainingSession.plan_id == plan.id,
                TrainingSession.scheduled_date >= win_start.isoformat(),
                TrainingSession.scheduled_date <= win_end.isoformat(),
            )
            .order_by(TrainingSession.scheduled_date.asc(), TrainingSession.id.asc())
        )
    )

    busy_ids = list(cfg.get("busy_calendar_ids") or [])
    if not busy_ids:
        busy_ids = ["primary"]
    time_min = datetime.combine(win_start, dt_time(0, 0), tzinfo=tz)
    time_max = datetime.combine(win_end + timedelta(days=1), dt_time(0, 0), tzinfo=tz)
    busy = query_free_busy(db, busy_ids, time_min, time_max)
    # Keep track of newly placed training sessions so two sessions on the same day don't overlap
    placed_busy = list(busy)

    token = _access_token(db)
    headers = {"Authorization": f"Bearer {token}"}
    created = updated = deleted = conflicts = 0

    with httpx.Client(timeout=20) as client:
        for s in sessions:
            if s.sport == "rest":
                continue
            if s.status == "skipped":
                if s.gcal_event_id:
                    client.delete(
                        f"{GCAL_API}/calendars/{target_cal}/events/{s.gcal_event_id}", headers=headers
                    )
                    s.gcal_event_id = None
                    deleted += 1
                continue

            s_day = date.fromisoformat(s.scheduled_date)
            slot = find_free_slot(
                s_day,
                s.target_duration_s or 3600,
                s.scheduled_slot or "evening",
                placed_busy,
                tz_name=cfg["timezone"],
                buffer_minutes=int(cfg.get("buffer_minutes", 20)),
                slot_windows=cfg.get("slot_windows"),
            )
            if slot is None:
                # Fallback: place at default morning start and flag conflict
                conflicts += 1
                start_dt = datetime.combine(s_day, dt_time(7, 0), tzinfo=tz)
                end_dt = start_dt + timedelta(seconds=max(1800, int(s.target_duration_s or 3600)))
            else:
                start_dt, end_dt = slot

            placed_busy.append((start_dt, end_dt))
            s.scheduled_start = start_dt.isoformat()
            s.scheduled_end = end_dt.isoformat()
            body = _event_body(plan, s, start_dt, end_dt)

            if s.gcal_event_id:
                resp = client.patch(
                    f"{GCAL_API}/calendars/{target_cal}/events/{s.gcal_event_id}",
                    headers=headers,
                    json=body,
                )
                if resp.status_code == 404:
                    resp = client.post(
                        f"{GCAL_API}/calendars/{target_cal}/events",
                        headers=headers,
                        json=body,
                    )
                    if resp.status_code < 400:
                        s.gcal_event_id = resp.json().get("id")
                        created += 1
                elif resp.status_code < 400:
                    updated += 1
            else:
                resp = client.post(
                    f"{GCAL_API}/calendars/{target_cal}/events",
                    headers=headers,
                    json=body,
                )
                if resp.status_code < 400:
                    s.gcal_event_id = resp.json().get("id")
                    created += 1

    db.flush()
    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "conflicts": conflicts,
        "synced_sessions": len(sessions),
    }

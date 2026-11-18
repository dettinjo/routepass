"""Strava API v3 client (single athlete, own API application)."""

from __future__ import annotations

import io
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

BASE = "https://www.strava.com"
API = f"{BASE}/api/v3"
SCOPES = "read,activity:read_all,activity:write,profile:read_all"
STREAM_KEYS = "time,latlng,altitude,heartrate,watts,cadence,temp,velocity_smoothed,moving,distance"


class StravaError(Exception):
    pass


class StravaAuthError(StravaError):
    pass


class RateLimited(StravaError):
    def __init__(self, retry_at: datetime, detail: str = "") -> None:
        super().__init__(f"Strava rate limit reached; retry after {retry_at.isoformat()} {detail}")
        self.retry_at = retry_at


@dataclass
class RateWindow:
    """Usage as last reported by Strava's X-(Read)RateLimit-* headers."""

    limit_15: int = 200
    limit_day: int = 2000
    read_limit_15: int = 100
    read_limit_day: int = 1000
    used_15: int = 0
    used_day: int = 0
    read_used_15: int = 0
    read_used_day: int = 0
    observed_at: float = field(default=0.0)

    def _current(self) -> RateWindow:
        # Usage counters reset at quarter-hours and at midnight UTC.
        now = time.time()
        if self.observed_at and int(now // 900) != int(self.observed_at // 900):
            self.used_15 = self.read_used_15 = 0
        if self.observed_at and int(now // 86400) != int(self.observed_at // 86400):
            self.used_day = self.read_used_day = 0
        return self

    def as_dict(self) -> dict[str, Any]:
        self._current()
        return {
            "overall": {"15min": [self.used_15, self.limit_15], "day": [self.used_day, self.limit_day]},
            "read": {
                "15min": [self.read_used_15, self.read_limit_15],
                "day": [self.read_used_day, self.read_limit_day],
            },
            "observed_at": datetime.fromtimestamp(self.observed_at, UTC).isoformat()
            if self.observed_at
            else None,
        }

    def headroom(self, *, read: bool) -> tuple[int, int]:
        self._current()
        if read:
            return (
                min(self.read_limit_15 - self.read_used_15, self.limit_15 - self.used_15),
                min(self.read_limit_day - self.read_used_day, self.limit_day - self.used_day),
            )
        return self.limit_15 - self.used_15, self.limit_day - self.used_day

    def next_reset(self, daily: bool) -> datetime:
        now = time.time()
        ts = (now // 86400 + 1) * 86400 if daily else (now // 900 + 1) * 900
        return datetime.fromtimestamp(ts + 5, UTC)

    def update(self, headers: httpx.Headers) -> None:
        def pair(name: str) -> tuple[int, int] | None:
            raw = headers.get(name)
            if not raw:
                return None
            try:
                a, b = raw.split(",")[:2]
                return int(a), int(b)
            except ValueError:
                return None

        if lim := pair("X-RateLimit-Limit"):
            self.limit_15, self.limit_day = lim
        if use := pair("X-RateLimit-Usage"):
            self.used_15, self.used_day = use
        if lim := pair("X-ReadRateLimit-Limit"):
            self.read_limit_15, self.read_limit_day = lim
        if use := pair("X-ReadRateLimit-Usage"):
            self.read_used_15, self.read_used_day = use
        self.observed_at = time.time()


RATE = RateWindow()
_rate_lock = threading.Lock()


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "approval_prompt": "auto",
            "scope": SCOPES,
            "state": state,
        }
    )
    return f"{BASE}/oauth/authorize?{query}"


def exchange_code(client_id: str, client_secret: str, code: str) -> dict[str, Any]:
    resp = httpx.post(
        f"{BASE}/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        raise StravaAuthError(f"Token exchange failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


class StravaClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tokens: dict[str, Any],
        on_refresh: Callable[[dict[str, Any]], None] | None = None,
        reserve_15: int = 0,
        reserve_day: int = 0,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.tokens = tokens
        self.on_refresh = on_refresh
        # Requests to keep free in each window (background work leaves room for interactive use).
        self.reserve_15 = reserve_15
        self.reserve_day = reserve_day
        self._http = httpx.Client(timeout=httpx.Timeout(45.0))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> StravaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── auth ───────────────────────────────────────────────────────────
    def _access_token(self) -> str:
        if self.tokens.get("expires_at", 0) - 120 < time.time():
            resp = self._http.post(
                f"{BASE}/oauth/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": self.tokens["refresh_token"],
                },
            )
            if resp.status_code >= 400:
                raise StravaAuthError(f"Token refresh failed ({resp.status_code}): {resp.text[:200]}")
            data = resp.json()
            self.tokens = {
                **self.tokens,
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
                "expires_at": data["expires_at"],
            }
            if self.on_refresh:
                self.on_refresh(self.tokens)
        return self.tokens["access_token"]

    # ── transport ──────────────────────────────────────────────────────
    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        read = method == "GET"
        with _rate_lock:
            h15, hday = RATE.headroom(read=read)
            if hday <= self.reserve_day:
                raise RateLimited(RATE.next_reset(daily=True), "(daily)")
            if h15 <= self.reserve_15:
                raise RateLimited(RATE.next_reset(daily=False), "(15 min)")
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        resp = self._http.request(method, f"{API}{path}", headers=headers, **kwargs)
        with _rate_lock:
            RATE.update(resp.headers)
        if resp.status_code == 429:
            raise RateLimited(RATE.next_reset(daily=RATE.used_day >= RATE.limit_day))
        if resp.status_code == 401:
            raise StravaAuthError(f"Strava rejected the token: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise StravaError(f"Strava {method} {path} → {resp.status_code}: {resp.text[:300]}")
        return resp

    # ── endpoints ──────────────────────────────────────────────────────
    def athlete(self) -> dict[str, Any]:
        return self._request("GET", "/athlete").json()

    def list_activities(
        self, after: int | None = None, before: int | None = None, page: int = 1, per_page: int = 200
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before
        return self._request("GET", "/athlete/activities", params=params).json()

    def activity(self, activity_id: str) -> dict[str, Any]:
        return self._request("GET", f"/activities/{activity_id}").json()

    def streams(self, activity_id: str) -> dict[str, Any]:
        resp = self._request(
            "GET",
            f"/activities/{activity_id}/streams",
            params={"keys": STREAM_KEYS, "key_by_type": "true"},
        )
        data = resp.json()
        if isinstance(data, list):  # older API shape
            data = {s["type"]: s for s in data}
        return data

    def upload_gpx(self, gpx: bytes, name: str, description: str, sport_type: str, external_id: str) -> str:
        resp = self._request(
            "POST",
            "/uploads",
            data={
                "data_type": "gpx",
                "name": name,
                "description": description,
                "sport_type": sport_type,
                "external_id": external_id,
            },
            files={"file": (f"{external_id}.gpx", io.BytesIO(gpx), "application/gpx+xml")},
        )
        return str(resp.json()["id"])

    def wait_for_upload(self, upload_id: str, attempts: int = 30, delay: float = 3.0) -> str:
        for _ in range(attempts):
            data = self._request("GET", f"/uploads/{upload_id}").json()
            if data.get("error"):
                raise StravaError(f"Strava upload failed: {data['error']}")
            if data.get("activity_id"):
                return str(data["activity_id"])
            time.sleep(delay)
        raise StravaError(f"Strava upload {upload_id} still processing after {attempts * delay:.0f}s")

    def update_activity(self, activity_id: str, **fields: Any) -> dict[str, Any]:
        return self._request("PUT", f"/activities/{activity_id}", json=fields).json()

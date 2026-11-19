"""Strava API v3 client and cookie-based Strava Web Session client (zero-cost fallback)."""

from __future__ import annotations

import gzip
import html
import io
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlencode

import httpx

from routepass.analysis import track as trk
from routepass.providers import sports

logger = logging.getLogger(__name__)

BASE = "https://www.strava.com"
API = f"{BASE}/api/v3"
SCOPES = "read,activity:read_all,activity:write,profile:read_all"
STREAM_KEYS = "time,latlng,altitude,heartrate,watts,cadence,temp,velocity_smoothed,moving,distance"
WEB_STREAM_TYPES = [
    "time",
    "latlng",
    "altitude",
    "heartrate",
    "watts",
    "cadence",
    "temp",
    "velocity_smoothed",
    "moving",
    "distance",
]
WEB_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class StravaError(Exception):
    pass


class StravaAuthError(StravaError):
    pass


class StravaInactiveAppError(StravaError):
    """Raised when Strava returns 403 Application Status: Inactive (no paid subscription on app owner)."""


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
        web_fallback: StravaWebClient | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.tokens = tokens
        self.on_refresh = on_refresh
        # Requests to keep free in each window (background work leaves room for interactive use).
        self.reserve_15 = reserve_15
        self.reserve_day = reserve_day
        self.web_fallback = web_fallback
        self._use_web = False
        self._http = httpx.Client(timeout=httpx.Timeout(45.0))

    def close(self) -> None:
        self._http.close()
        if self.web_fallback is not None:
            self.web_fallback.close()

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
        if resp.status_code == 403 and "Inactive" in resp.text:
            raise StravaInactiveAppError(f"Strava {method} {path} → {resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 400:
            raise StravaError(f"Strava {method} {path} → {resp.status_code}: {resp.text[:300]}")
        return resp

    def _call_with_fallback(
        self, fn_name: str, api_call: Callable[[], Any], *args: Any, **kwargs: Any
    ) -> Any:
        if self._use_web and self.web_fallback is not None:
            return getattr(self.web_fallback, fn_name)(*args, **kwargs)
        try:
            return api_call()
        except StravaInactiveAppError:
            if self.web_fallback is None:
                raise
            logger.info("Strava API app is inactive; falling back to Strava web session for %s", fn_name)
            self._use_web = True
            return getattr(self.web_fallback, fn_name)(*args, **kwargs)

    # ── endpoints ──────────────────────────────────────────────────────
    def athlete(self) -> dict[str, Any]:
        return self._call_with_fallback("athlete", lambda: self._request("GET", "/athlete").json())

    def list_activities(
        self, after: int | None = None, before: int | None = None, page: int = 1, per_page: int = 200
    ) -> list[dict[str, Any]]:
        def _api() -> list[dict[str, Any]]:
            params: dict[str, Any] = {"page": page, "per_page": per_page}
            if after is not None:
                params["after"] = after
            if before is not None:
                params["before"] = before
            return self._request("GET", "/athlete/activities", params=params).json()

        return self._call_with_fallback(
            "list_activities", _api, after=after, before=before, page=page, per_page=per_page
        )

    def activity(self, activity_id: str) -> dict[str, Any]:
        return self._call_with_fallback(
            "activity", lambda: self._request("GET", f"/activities/{activity_id}").json(), activity_id
        )

    def streams(self, activity_id: str) -> dict[str, Any]:
        def _api() -> dict[str, Any]:
            resp = self._request(
                "GET",
                f"/activities/{activity_id}/streams",
                params={"keys": STREAM_KEYS, "key_by_type": "true"},
            )
            data = resp.json()
            if isinstance(data, list):  # older API shape
                data = {s["type"]: s for s in data}
            return data

        return self._call_with_fallback("streams", _api, activity_id)

    def upload_gpx(self, gpx: bytes, name: str, description: str, sport_type: str, external_id: str) -> str:
        def _api() -> str:
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

        return self._call_with_fallback("upload_gpx", _api, gpx, name, description, sport_type, external_id)

    def wait_for_upload(self, upload_id: str, attempts: int = 30, delay: float = 3.0) -> str:
        def _api() -> str:
            for _ in range(attempts):
                data = self._request("GET", f"/uploads/{upload_id}").json()
                if data.get("error"):
                    raise StravaError(f"Strava upload failed: {data['error']}")
                if data.get("activity_id"):
                    return str(data["activity_id"])
                time.sleep(delay)
            raise StravaError(f"Strava upload {upload_id} still processing after {attempts * delay:.0f}s")

        return self._call_with_fallback("wait_for_upload", _api, upload_id, attempts=attempts, delay=delay)

    def update_activity(self, activity_id: str, **fields: Any) -> dict[str, Any]:
        return self._call_with_fallback(
            "update_activity",
            lambda: self._request("PUT", f"/activities/{activity_id}", json=fields).json(),
            activity_id,
            **fields,
        )


# ── Strava Web Session Client (zero-cost browser cookie client) ──────────────

_WEB_SPORT_LABELS = {
    "rockclimb": "RockClimbing",
    "canoe": "Canoeing",
    "hiit": "HighIntensityIntervalTraining",
    "weighttraining": "WeightTraining",
    "standuppaddling": "StandUpPaddling",
    "ebikeride": "EBikeRide",
    "emountainbikeride": "EMountainBikeRide",
    "mountainbikeride": "MountainBikeRide",
    "gravelride": "GravelRide",
    "trailrun": "TrailRun",
    "virtualride": "VirtualRide",
    "virtualrun": "VirtualRun",
    "alpineski": "AlpineSki",
    "backcountryski": "BackcountrySki",
    "nordicski": "NordicSki",
    "radfahrt": "Ride",
    "radfahren": "Ride",
    "lauf": "Run",
    "laufen": "Run",
    "wanderung": "Hike",
    "wandern": "Hike",
    "spaziergang": "Walk",
    "gehen": "Walk",
    "e-bike-fahrt": "EBikeRide",
    "ebike-fahrt": "EBikeRide",
    "mountainbike-fahrt": "MountainBikeRide",
    "e-mountainbike-fahrt": "EMountainBikeRide",
    "gravel-fahrt": "GravelRide",
    "schwimmen": "Swim",
    "skitour": "BackcountrySki",
    "langlauf": "NordicSki",
    "krafttraining": "WeightTraining",
    "training": "Workout",
}

_CSRF_RE = re.compile(
    r'<meta[^>]+name=["\']csrf(?:-token)?["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']csrf(?:-token)?["\']',
    re.IGNORECASE,
)
_ATHLETE_JSON_RE = re.compile(
    r'currentAthlete\s*[:=]\s*(\{[^{}]*"id"\s*:\s*\d+[^{}]*\})',
    re.DOTALL,
)
_ATHLETE_LINK_RE = re.compile(r'href=["\']/athletes/(\d+)["\']')
_ATHLETE_NAME_RE = re.compile(
    r'class=["\'][^"\']*athlete-name[^"\']*["\'][^>]*>([^<]+)<'
    r'|<div[^>]+class=["\'][^"\']*avatar-content[^"\']*["\'][^>]*>\s*<[^>]+>([^<]+)<',
    re.IGNORECASE,
)
_CURL_COOKIE_RE = re.compile(
    r"""(?:-H|--header)\s+['"]cookie:\s*([^'"]+)['"]|(?:-b|--cookie)\s+['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


def parse_web_cookies(cookie_input: str | dict[str, str], remember_token: str = "") -> dict[str, str]:
    """Parse a Cookie header, 'Copy as cURL' snippet, DevTools table row, JSON dict, or raw value."""
    cookies: dict[str, str] = {}
    if isinstance(cookie_input, dict):
        cookies = {str(k).strip(): str(v).strip() for k, v in cookie_input.items() if str(v).strip()}
    else:
        raw = (cookie_input or "").strip()
        # 1) "Copy as cURL" command (-H 'cookie: ...' or -b '...')
        if m_curl := _CURL_COOKIE_RE.search(raw):
            raw = (m_curl.group(1) or m_curl.group(2) or "").strip()
        # 2) Multi-line "Copy Request Headers" block containing `Cookie: ...`
        elif "\n" in raw:
            for line in raw.splitlines():
                stripped = line.strip()
                if stripped.lower().startswith("cookie:"):
                    raw = stripped.split(":", 1)[1].strip()
                    break
                # DevTools Application -> Cookies table copy (tab-separated: name \t value \t domain ...)
                if "\t" in stripped:
                    cols = [c.strip() for c in stripped.split("\t") if c.strip()]
                    if len(cols) >= 2 and cols[0] in (
                        "_strava4_session",
                        "strava_remember_token",
                        "_strava_idcf",
                    ):
                        cookies[cols[0]] = cols[1]
        if raw.lower().startswith("cookie:"):
            raw = raw.split(":", 1)[1].strip()
        if not cookies and "\t" in raw:
            cols = [c.strip() for c in raw.split("\t") if c.strip()]
            if len(cols) >= 2 and cols[0].startswith("_strava") or cols[0] == "strava_remember_token":
                cookies[cols[0]] = cols[1]
        if not cookies and raw.startswith("{") and raw.endswith("}"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    cookies = {str(k).strip(): str(v).strip() for k, v in parsed.items() if str(v).strip()}
            except ValueError:
                pass
        if not cookies and raw:
            if "=" in raw:
                sc = SimpleCookie()
                try:
                    sc.load(raw)
                    cookies = {k: morsel.value for k, morsel in sc.items() if morsel.value}
                except Exception:  # noqa: BLE001
                    pass
                if not cookies:
                    for part in raw.split(";"):
                        if "=" in part:
                            k, v = part.split("=", 1)
                            if k.strip() and v.strip():
                                cookies[k.strip()] = v.strip().strip('"')
            else:
                cookies["_strava4_session"] = raw
    if remember_token and remember_token.strip():
        cookies["strava_remember_token"] = remember_token.strip()
    if not cookies.get("_strava4_session") and not cookies.get("strava_remember_token"):
        raise StravaAuthError("Provide `_strava4_session` or `strava_remember_token` cookie from strava.com")
    return cookies


def _normalize_web_sport(raw: str | None) -> str:
    label = (raw or "").strip()
    if not label:
        return "Workout"
    if label in sports.STRAVA:
        return label
    collapsed = re.sub(r"[\s\-_]", "", label)
    if collapsed in sports.STRAVA:
        return collapsed
    low = collapsed.lower()
    if low in _WEB_SPORT_LABELS:
        return _WEB_SPORT_LABELS[low]
    low_hyphen = label.lower().replace(" ", "")
    if low_hyphen in _WEB_SPORT_LABELS:
        return _WEB_SPORT_LABELS[low_hyphen]
    for st in sports.STRAVA:
        if st.lower() == low:
            return st
    return "Workout"


def _parse_duration_s(val: Any) -> int | None:
    if val is None or val == "":
        return None
    if isinstance(val, int | float):
        return int(val)
    s = str(val).strip()
    try:
        return int(float(s))
    except ValueError:
        pass
    parts = s.split(":")
    if len(parts) in (2, 3) and all(p.strip().isdigit() for p in parts):
        nums = [int(p.strip()) for p in parts]
        return nums[0] * 3600 + nums[1] * 60 + nums[2] if len(nums) == 3 else nums[0] * 60 + nums[1]
    return None


def _parse_float(val: Any, scale: float = 1.0) -> float | None:
    if val is None or val == "":
        return None
    if isinstance(val, int | float):
        return float(val) * scale
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(val).replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0)) * scale
    except ValueError:
        return None


def _parse_web_start(item: dict[str, Any]) -> tuple[str | None, int | None]:
    """Extract (UTC ISO-8601 string, epoch seconds) from a Strava web activity dict."""
    for key in ("start_date", "start_time", "start_date_local"):
        val = item.get(key)
        if isinstance(val, str) and "T" in val:
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.astimezone(UTC).replace(tzinfo=None)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), int(dt.replace(tzinfo=UTC).timestamp())
            except ValueError:
                pass
    raw_ts = item.get("start_date_local_raw") or item.get("start_time_raw") or item.get("timestamp")
    if isinstance(raw_ts, int | float) and raw_ts > 0:
        # Note: Strava web's start_date_local_raw is a unix epoch integer.
        dt = datetime.fromtimestamp(float(raw_ts), UTC).replace(tzinfo=None)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), int(raw_ts)
    for fmt in ("%b %d, %Y, %I:%M:%S %p", "%b %d, %Y", "%d.%m.%Y", "%Y-%m-%d"):
        for key in ("start_date", "start_time"):
            val = item.get(key)
            if isinstance(val, str):
                try:
                    dt = datetime.strptime(val.strip(), fmt)
                    return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), int(dt.replace(tzinfo=UTC).timestamp())
                except ValueError:
                    continue
    return None, None


def _normalize_web_activity(item: dict[str, Any]) -> dict[str, Any] | None:
    act_id = item.get("id") or item.get("activity_id")
    if not act_id:
        return None
    start_iso, start_ts = _parse_web_start(item)
    if not start_iso:
        return None
    sport = _normalize_web_sport(
        item.get("sport_type") or item.get("type") or item.get("display_type") or item.get("activity_type")
    )
    # Strava web `/athlete/training_activities` supplies `distance_raw` in meters (or `distance` in km/m).
    dist_m = _parse_float(item.get("distance_raw"))
    if dist_m is None and item.get("distance") is not None:
        raw_d = item.get("distance")
        # In v3 JSON `distance` is already meters; on web strings like "25.4 km" it's km.
        if isinstance(raw_d, str) and "km" in raw_d.lower():
            dist_m = _parse_float(raw_d, 1000.0)
        else:
            dist_m = _parse_float(raw_d)
    moving_s = _parse_duration_s(item.get("moving_time_raw") or item.get("moving_time"))
    elapsed_s = _parse_duration_s(item.get("elapsed_time_raw") or item.get("elapsed_time")) or moving_s
    elev_m = _parse_float(
        item.get("elevation_gain_raw")
        if item.get("elevation_gain_raw") is not None
        else (item.get("total_elevation_gain") or item.get("elevation_gain"))
    )
    avg_speed = _parse_float(item.get("average_speed"))
    if avg_speed is None and dist_m and moving_s and moving_s > 0:
        avg_speed = dist_m / moving_s
    visibility = item.get("visibility") or ("only_me" if item.get("private") else "everyone")
    poly = item.get("summary_polyline") or (item.get("map") or {}).get("summary_polyline")

    out: dict[str, Any] = {
        "id": int(act_id) if str(act_id).isdigit() else str(act_id),
        "name": html.unescape(str(item.get("name") or item.get("title") or "Strava activity")).strip(),
        "sport_type": sport,
        "type": sport,
        "start_date": start_iso,
        "distance": dist_m,
        "moving_time": moving_s,
        "elapsed_time": elapsed_s,
        "total_elevation_gain": elev_m,
        "average_speed": avg_speed,
        "max_speed": _parse_float(item.get("max_speed")),
        "average_heartrate": _parse_float(item.get("average_heartrate") or item.get("avg_hr")),
        "max_heartrate": _parse_float(item.get("max_heartrate") or item.get("max_hr")),
        "average_watts": _parse_float(item.get("average_watts") or item.get("avg_watts")),
        "weighted_average_watts": _parse_float(item.get("weighted_average_watts") or item.get("np_watts")),
        "kilojoules": _parse_float(item.get("kilojoules")),
        "calories": _parse_float(item.get("calories")),
        "suffer_score": _parse_float(item.get("suffer_score")),
        "trainer": bool(item.get("trainer")),
        "commute": bool(item.get("commute")),
        "manual": bool(item.get("manual")),
        "private": visibility == "only_me" or bool(item.get("private")),
        "visibility": visibility,
        "gear_id": item.get("gear_id") or item.get("bike_id") or item.get("athlete_gear_id"),
        "description": item.get("description"),
        "external_id": item.get("external_id"),
        "source": "web",
        "_start_ts": start_ts,
    }
    if poly:
        out["summary_polyline"] = poly
    return {k: v for k, v in out.items() if v is not None}


def _normalized_track_to_streams(track: trk.NormalizedTrack) -> dict[str, Any]:
    """Convert a NormalizedTrack (from FIT/GPX/TCX) into the Strava streams dict shape."""
    out: dict[str, Any] = {"time": {"data": track.time.tolist()}}
    if track.has_gps:
        out["latlng"] = {
            "data": [
                [float(a), float(b)] for a, b in zip(track.lat.tolist(), track.lon.tolist(), strict=True)
            ]
        }
    if track.ele is not None:
        out["altitude"] = {"data": [None if x != x else float(x) for x in track.ele.tolist()]}
    if track.hr is not None:
        out["heartrate"] = {"data": [None if x != x else float(x) for x in track.hr.tolist()]}
    if track.power is not None:
        out["watts"] = {"data": [None if x != x else float(x) for x in track.power.tolist()]}
    if track.cadence is not None:
        out["cadence"] = {"data": [None if x != x else float(x) for x in track.cadence.tolist()]}
    if track.temp is not None:
        out["temp"] = {"data": [None if x != x else float(x) for x in track.temp.tolist()]}
    if track.distance is not None:
        out["distance"] = {"data": [None if x != x else float(x) for x in track.distance.tolist()]}
    if track.speed is not None:
        out["velocity_smoothed"] = {"data": [None if x != x else float(x) for x in track.speed.tolist()]}
    if track.moving is not None:
        out["moving"] = {"data": [bool(x) for x in track.moving.tolist()]}
    return out


class StravaWebClient:
    """Client for Strava's own web endpoints using the user's browser session cookie."""

    def __init__(
        self,
        cookies: dict[str, str] | str,
        on_refresh: Callable[[dict[str, str]], None] | None = None,
    ) -> None:
        self.cookies = parse_web_cookies(cookies)
        self.on_refresh = on_refresh
        self._csrf_token: str | None = None
        self._pending_uploads: dict[str, dict[str, Any]] = {}
        self._last_request = 0.0
        self._http = httpx.Client(
            cookies=self.cookies,
            headers={"User-Agent": WEB_UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=httpx.Timeout(45.0),
            event_hooks={"request": [self._pace]},
            follow_redirects=False,
        )

    WEB_MIN_INTERVAL_S = 1.5  # never hit strava.com faster than a person clicking through pages

    def _pace(self, _request: httpx.Request) -> None:
        wait = self._last_request + self.WEB_MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> StravaWebClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _sync_cookies(self, resp: httpx.Response) -> None:
        changed = False
        for k, v in resp.cookies.items():
            if v and self.cookies.get(k) != v:
                self.cookies[k] = v
                self._http.cookies.set(k, v)
                changed = True
        if changed and self.on_refresh:
            self.on_refresh(dict(self.cookies))

    def _is_auth_failure(self, resp: httpx.Response) -> bool:
        if resp.status_code in (401, 403):
            return True
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("location", "")
            if "/login" in loc or "/session" in loc or "/onboarding" in loc:
                return True
        return False

    def _try_renew_from_remember_token(self) -> bool:
        """Use `strava_remember_token` to mint a fresh `_strava4_session` when the old session expires."""
        remember = self.cookies.get("strava_remember_token")
        if not remember:
            return False
        old_session = self.cookies.get("_strava4_session")
        self._http.cookies.delete("_strava4_session")
        self._http.cookies.set("strava_remember_token", remember)
        url = f"{BASE}/dashboard"
        resp: httpx.Response | None = None
        for _ in range(4):
            resp = self._http.get(url, headers={"Accept": "text/html,application/xhtml+xml"})
            self._sync_cookies(resp)
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location", "")
                if not loc or "/login" in loc:
                    break
                url = loc if loc.startswith("http") else f"{BASE}{loc}"
                continue
            break
        new_session = self.cookies.get("_strava4_session")
        if (
            resp is not None
            and resp.status_code == 200
            and new_session
            and new_session != old_session
            and 'action="/session"' not in resp.text
        ):
            self._extract_csrf(resp.text)
            return True
        if old_session:
            self.cookies["_strava4_session"] = old_session
            self._http.cookies.set("_strava4_session", old_session)
        return False

    def _check_redirect_or_login(self, resp: httpx.Response, path: str) -> None:
        self._sync_cookies(resp)
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("location", "")
            if "/login" in loc or "/session" in loc or "/onboarding" in loc:
                raise StravaAuthError(
                    "Strava web session expired or rejected — sign in again in Settings → Strava"
                )
        if resp.status_code in (401, 403):
            raise StravaAuthError(f"Strava web session rejected on {path} ({resp.status_code})")
        if resp.status_code >= 400:
            raise StravaError(f"Strava web {path} → {resp.status_code}: {resp.text[:300]}")

    def _extract_csrf(self, html_text: str) -> str | None:
        m = _CSRF_RE.search(html_text)
        if m:
            self._csrf_token = html.unescape(m.group(1) or m.group(2))
        return self._csrf_token

    def _ensure_csrf(self) -> str:
        if self._csrf_token:
            return self._csrf_token
        self.athlete()
        if not self._csrf_token:
            raise StravaAuthError("Could not obtain CSRF token from Strava web session")
        return self._csrf_token

    # ── endpoints ──────────────────────────────────────────────────────
    def athlete(self) -> dict[str, Any]:
        resp = self._http.get(f"{BASE}/dashboard", headers={"Accept": "text/html,application/xhtml+xml"})
        self._sync_cookies(resp)
        if self._is_auth_failure(resp) and self._try_renew_from_remember_token():
            resp = self._http.get(f"{BASE}/dashboard", headers={"Accept": "text/html,application/xhtml+xml"})
            self._sync_cookies(resp)
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("location", "")
            if "/login" in loc or "/session" in loc:
                raise StravaAuthError("Strava web session expired — sign in again in Settings → Strava")
            if loc.startswith("/"):
                resp = self._http.get(f"{BASE}{loc}", headers={"Accept": "text/html,application/xhtml+xml"})
        self._check_redirect_or_login(resp, "/dashboard")
        body = resp.text
        if 'action="/session"' in body and "login" in body.lower() and "/athletes/" not in body:
            raise StravaAuthError("Strava web session is not signed in — sign in again in Settings → Strava")
        self._extract_csrf(body)

        athlete_id: int | str | None = None
        firstname = ""
        lastname = ""
        full_name = ""

        if m_json := _ATHLETE_JSON_RE.search(body):
            try:
                obj = json.loads(m_json.group(1))
                athlete_id = obj.get("id")
                firstname = obj.get("firstname") or ""
                lastname = obj.get("lastname") or ""
                full_name = obj.get("display_name") or obj.get("name") or f"{firstname} {lastname}".strip()
            except ValueError:
                pass
        if not athlete_id:
            if m_link := _ATHLETE_LINK_RE.search(body):
                athlete_id = int(m_link.group(1))
        if not full_name:
            if m_name := _ATHLETE_NAME_RE.search(body):
                full_name = html.unescape((m_name.group(1) or m_name.group(2) or "").strip())
        if full_name and not firstname:
            parts = full_name.split(" ", 1)
            firstname = parts[0]
            lastname = parts[1] if len(parts) > 1 else ""
        if not athlete_id:
            raise StravaAuthError("Could not verify Strava athlete from web session cookie")
        return {
            "id": athlete_id,
            "firstname": firstname or full_name or f"Athlete {athlete_id}",
            "lastname": lastname,
            "name": full_name or f"{firstname} {lastname}".strip() or f"Athlete {athlete_id}",
        }

    def _fetch_training_page(self, web_page: int) -> list[dict[str, Any]]:
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{BASE}/athlete/training",
        }
        params = {"new_activity_only": "false", "page": web_page, "per_page": 20}
        resp = self._http.get(f"{BASE}/athlete/training_activities", params=params, headers=headers)
        self._sync_cookies(resp)
        if self._is_auth_failure(resp) and self._try_renew_from_remember_token():
            resp = self._http.get(f"{BASE}/athlete/training_activities", params=params, headers=headers)
            self._sync_cookies(resp)
        self._check_redirect_or_login(resp, "/athlete/training_activities")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise StravaAuthError(
                "Strava web training log returned HTML instead of JSON (session expired)"
            ) from exc
        models = payload.get("models") if isinstance(payload, dict) else payload
        if not isinstance(models, list):
            return []
        out: list[dict[str, Any]] = []
        for item in models:
            if isinstance(item, dict):
                norm = _normalize_web_activity(item)
                if norm is not None:
                    out.append(norm)
        return out

    def list_activities(
        self, after: int | None = None, before: int | None = None, page: int = 1, per_page: int = 200
    ) -> list[dict[str, Any]]:
        """Fetch activities via `/athlete/training_activities`, aggregating 20-item web pages up to `per_page`."""
        subpages = max(1, (per_page + 19) // 20)
        start_web_page = (page - 1) * subpages + 1
        collected: list[dict[str, Any]] = []

        for wp in range(start_web_page, start_web_page + subpages):
            batch = self._fetch_training_page(wp)
            if not batch:
                break
            older_than_after = 0
            for item in batch:
                ts = item.pop("_start_ts", None)
                if before is not None and ts is not None and ts > before:
                    continue
                if after is not None and ts is not None and ts < after:
                    older_than_after += 1
                    continue
                collected.append(item)
            if len(batch) < 20 or (after is not None and older_than_after == len(batch)):
                break
        return collected

    def activity(self, activity_id: str) -> dict[str, Any]:
        resp = self._http.get(
            f"{BASE}/activities/{activity_id}",
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        self._check_redirect_or_login(resp, f"/activities/{activity_id}")
        self._extract_csrf(resp.text)
        title_m = re.search(r"<title>([^<]+)</title>", resp.text, re.IGNORECASE)
        name = (
            html.unescape(title_m.group(1)).split("|")[0].split(" - ")[0].strip()
            if title_m
            else f"Activity {activity_id}"
        )
        return {"id": activity_id, "name": name, "source": "web"}

    def streams(self, activity_id: str) -> dict[str, Any]:
        """Fetch streams from `/activities/{id}/streams`, with fallback to `/export_original` and `/export_gpx`."""
        query: list[tuple[str, str]] = [("stream_types[]", t) for t in WEB_STREAM_TYPES]
        resp = self._http.get(
            f"{BASE}/activities/{activity_id}/streams",
            params=query,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": f"{BASE}/activities/{activity_id}",
            },
        )
        self._sync_cookies(resp)
        if resp.status_code == 200:
            try:
                raw = resp.json()
                if isinstance(raw, list):
                    return {s["type"]: s for s in raw if isinstance(s, dict) and "type" in s}
                if isinstance(raw, dict) and raw:
                    out: dict[str, Any] = {}
                    for k, v in raw.items():
                        if isinstance(v, dict) and "data" in v:
                            out[k] = v
                        elif isinstance(v, list):
                            out[k] = {"data": v}
                    if out:
                        return out
            except ValueError:
                pass

        # Fallback 2: download original recording (`/activities/{id}/export_original`) or `/export_gpx`
        for suffix in ("export_original", "export_gpx"):
            r = self._http.get(
                f"{BASE}/activities/{activity_id}/{suffix}",
                headers={"Referer": f"{BASE}/activities/{activity_id}"},
                follow_redirects=True,
            )
            self._sync_cookies(r)
            if r.status_code != 200 or not r.content:
                continue
            data = r.content
            if data[:2] == b"\x1f\x8b":
                try:
                    data = gzip.decompress(data)
                except OSError:
                    pass
            disp = (r.headers.get("content-disposition") or "").lower()
            track: trk.NormalizedTrack | None = None
            if ".fit" in disp or (len(data) > 12 and data[8:12] == b".FIT"):
                track = trk.from_fit(data)
            elif ".tcx" in disp or b"<TrainingCenterDatabase" in data[:600]:
                track = trk.from_tcx(data)
            elif suffix == "export_gpx" or ".gpx" in disp or b"<gpx" in data[:600]:
                track = trk.from_gpx(data)
            if track is not None:
                return _normalized_track_to_streams(track)

        if resp.status_code in (401, 403, 301, 302):
            raise StravaAuthError(f"Strava web session could not read streams for {activity_id}")
        return {}

    def upload_gpx(self, gpx: bytes, name: str, description: str, sport_type: str, external_id: str) -> str:
        csrf = self._ensure_csrf()
        resp = self._http.post(
            f"{BASE}/upload/files",
            headers={
                "X-CSRF-Token": csrf,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": f"{BASE}/upload/select",
            },
            files={"files[]": (f"{external_id}.gpx", io.BytesIO(gpx), "application/gpx+xml")},
        )
        self._check_redirect_or_login(resp, "/upload/files")
        try:
            data = resp.json()
        except ValueError as exc:
            raise StravaError(f"Strava web upload returned non-JSON: {resp.text[:200]}") from exc
        entry = data[0] if isinstance(data, list) and data else data
        if not isinstance(entry, dict) or not entry.get("id"):
            raise StravaError(f"Strava web upload did not return an upload id: {data}")
        if entry.get("error"):
            raise StravaError(f"Strava upload failed: {entry['error']}")
        upload_id = str(entry["id"])
        self._pending_uploads[upload_id] = {
            "name": name,
            "description": description,
            "sport_type": sport_type,
        }
        return upload_id

    def wait_for_upload(self, upload_id: str, attempts: int = 30, delay: float = 3.0) -> str:
        for _ in range(attempts):
            resp = self._http.get(
                f"{BASE}/upload/progress",
                params={"ids[]": upload_id},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Referer": f"{BASE}/upload/select",
                },
            )
            self._check_redirect_or_login(resp, "/upload/progress")
            payload = resp.json()
            rows = (
                payload.get("progress")
                if isinstance(payload, dict) and isinstance(payload.get("progress"), list)
                else (payload if isinstance(payload, list) else [payload])
            )
            entry = rows[0] if rows and isinstance(rows[0], dict) else {}
            if entry.get("error"):
                raise StravaError(f"Strava upload failed: {entry['error']}")
            act_id = entry.get("activity_id") or (entry.get("activity") or {}).get("id")
            if act_id:
                activity_id = str(act_id)
                meta = self._pending_uploads.pop(upload_id, None)
                if meta:
                    try:
                        self.update_activity(activity_id, **meta)
                    except StravaError as exc:
                        logger.warning(
                            "Could not apply initial metadata on Strava web upload %s: %s", activity_id, exc
                        )
                return activity_id
            time.sleep(delay)
        raise StravaError(f"Strava upload {upload_id} still processing after {attempts * delay:.0f}s")

    def update_activity(self, activity_id: str, **fields: Any) -> dict[str, Any]:
        csrf = self._ensure_csrf()
        payload: dict[str, Any] = {}
        for k, v in fields.items():
            if v is None:
                continue
            if k == "sport_type":
                payload["sport_type"] = v
                payload["type"] = v
            elif k == "private":
                payload["private"] = bool(v)
                payload["visibility"] = "only_me" if v else "everyone"
            else:
                payload[k] = v
        if not payload:
            return {"id": activity_id}
        resp = self._http.patch(
            f"{BASE}/activities/{activity_id}",
            headers={
                "X-CSRF-Token": csrf,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": f"{BASE}/activities/{activity_id}",
            },
            json=payload,
        )
        self._check_redirect_or_login(resp, f"/activities/{activity_id}")
        try:
            return resp.json()
        except ValueError:
            return {"id": activity_id, **payload}


def list_push_subscriptions(client_id: str, client_secret: str) -> list[dict[str, Any]]:
    resp = httpx.get(
        f"{API}/push_subscriptions",
        params={"client_id": client_id, "client_secret": client_secret},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise StravaError(f"Strava push_subscriptions → {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def create_push_subscription(
    client_id: str, client_secret: str, callback_url: str, verify_token: str
) -> dict:
    # Strava calls the callback (GET hub.challenge) synchronously before answering this request.
    resp = httpx.post(
        f"{API}/push_subscriptions",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "callback_url": callback_url,
            "verify_token": verify_token,
        },
        timeout=60,
    )
    if resp.status_code >= 400:
        raise StravaError(f"Strava push_subscriptions → {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def delete_push_subscription(client_id: str, client_secret: str, subscription_id: int) -> None:
    resp = httpx.delete(
        f"{API}/push_subscriptions/{subscription_id}",
        params={"client_id": client_id, "client_secret": client_secret},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise StravaError(f"Strava push_subscriptions → {resp.status_code}: {resp.text[:300]}")

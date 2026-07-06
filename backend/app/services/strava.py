from __future__ import annotations

import asyncio
import io
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

STRAVA_BASE = "https://www.strava.com"


def streams_to_gpx(
    activity_name: str,
    sport_type: str,
    started_at: datetime | None,
    streams: dict,
) -> bytes:
    """Convert Strava stream data (latlng, altitude, time) to GPX bytes.

    Returns an empty bytes object when the streams dict contains no latlng data.
    """
    latlng: list = streams.get("latlng", {}).get("data", [])
    if not latlng:
        return b""

    altitudes: list = streams.get("altitude", {}).get("data", [])
    times: list = streams.get("time", {}).get("data", [])

    base_time = started_at or datetime(2000, 1, 1, tzinfo=UTC)

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="RoutePass"',
        '     xmlns="http://www.topografix.com/GPX/1/1">',
        "  <metadata>",
        f"    <name>{activity_name}</name>",
        f"    <time>{base_time.strftime('%Y-%m-%dT%H:%M:%SZ')}</time>",
        "  </metadata>",
        "  <trk>",
        f"    <name>{activity_name}</name>",
        f"    <type>{sport_type or 'unknown'}</type>",
        "    <trkseg>",
    ]

    for i, (lat, lon) in enumerate(latlng):
        ele = altitudes[i] if i < len(altitudes) else 0
        offset = times[i] if i < len(times) else 0
        t = base_time + timedelta(seconds=int(offset))
        ts = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(
            f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}">'
            f"<ele>{ele:.1f}</ele><time>{ts}</time></trkpt>"
        )

    lines += ["    </trkseg>", "  </trk>", "</gpx>"]
    return "\n".join(lines).encode("utf-8")


UPLOAD_POLL_INTERVAL = 3.0  # seconds between status polls
UPLOAD_MAX_ATTEMPTS = 30  # max polls before giving up (~90 s)


class StravaClient:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token
        self._auth_header = {"Authorization": f"Bearer {self.access_token}"}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self._auth_header,
            timeout=httpx.Timeout(30.0),
        )

    @staticmethod
    async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
        """Exchange a refresh token for a fresh Strava token payload."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{STRAVA_BASE}/oauth/token",
                data={
                    "client_id": settings.STRAVA_CLIENT_ID,
                    "client_secret": settings.STRAVA_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def upload_gpx(
        self,
        gpx_bytes: bytes,
        name: str,
        description: str,
        sport_type: str,
        external_id: str,
    ) -> str:
        """Upload a GPX file to Strava and return the upload_id for polling."""
        logger.info("Uploading GPX to Strava: %r (%d bytes)", name, len(gpx_bytes))

        data = {
            "data_type": "gpx",
            "name": name,
            "description": description,
            "sport_type": sport_type,
            "external_id": external_id,
        }
        files = {"file": (f"{external_id}.gpx", io.BytesIO(gpx_bytes), "application/gpx+xml")}

        async with httpx.AsyncClient(headers=self._auth_header, timeout=60.0) as client:
            resp = await client.post(f"{STRAVA_BASE}/api/v3/uploads", data=data, files=files)
            resp.raise_for_status()

            upload_id = str(resp.json()["id"])
            logger.debug("Upload accepted — upload_id=%s", upload_id)
            return upload_id

    async def poll_upload(self, upload_id: str) -> str:
        """Poll Strava until the upload is processed and return the activity_id."""
        url = f"{STRAVA_BASE}/api/v3/uploads/{upload_id}"

        async with self._client() as client:
            for attempt in range(1, UPLOAD_MAX_ATTEMPTS + 1):
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

                error = data.get("error")
                if error:
                    raise RuntimeError(f"Strava upload failed: {error}")

                activity_id = data.get("activity_id")
                if activity_id:
                    logger.info("Upload processed → activity_id=%s", activity_id)
                    return str(activity_id)

                status = data.get("status", "unknown")
                logger.debug("Upload status [%d/%d]: %s", attempt, UPLOAD_MAX_ATTEMPTS, status)
                await asyncio.sleep(UPLOAD_POLL_INTERVAL)

        raise TimeoutError(
            f"Strava upload {upload_id} did not complete after {UPLOAD_MAX_ATTEMPTS} polls"
        )

    async def update_activity(self, activity_id: str, hide_from_home: bool = True) -> None:
        """Update activity attributes after upload.

        Note: Strava removed the ability to set visibility='only_me' via API.
        Setting hide_from_home=True mutes the activity from followers' feeds,
        which is the closest available control. Users should set their default
        Strava activity privacy to "Only You" in account settings.
        """
        async with self._client() as client:
            resp = await client.put(
                f"{STRAVA_BASE}/api/v3/activities/{activity_id}",
                json={"hide_from_home": hide_from_home},
            )
            resp.raise_for_status()
            logger.debug("Updated activity %s (hide_from_home=%s)", activity_id, hide_from_home)

    async def delete_activity(self, activity_id: str) -> None:
        """Delete an activity from Strava. Requires activity:write scope."""
        async with self._client() as client:
            resp = await client.delete(f"{STRAVA_BASE}/api/v3/activities/{activity_id}")
            resp.raise_for_status()
            logger.debug("Deleted Strava activity %s", activity_id)

    async def get_activity(self, activity_id: str) -> dict[str, Any]:
        """Fetch a single activity by ID."""
        async with self._client() as client:
            resp = await client.get(f"{STRAVA_BASE}/api/v3/activities/{activity_id}")
            resp.raise_for_status()
            return resp.json()

    async def get_activities(
        self, after: int = None, page: int = 1, per_page: int = 50
    ) -> list[Any]:
        """Fetch a page of athlete activities from Strava."""
        url = f"{STRAVA_BASE}/api/v3/athlete/activities"
        params = {"page": page, "per_page": per_page}
        if after:
            params["after"] = after

        async with self._client() as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_activity_streams(self, activity_id: str) -> dict[str, Any]:
        """Fetch latlng, altitude and time streams for an activity (key_by_type=true)."""
        url = f"{STRAVA_BASE}/api/v3/activities/{activity_id}/streams"
        params = {"keys": "latlng,altitude,time", "key_by_type": "true"}
        async with self._client() as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

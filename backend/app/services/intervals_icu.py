"""Intervals.icu API client for pushing activities via GPX upload."""

from __future__ import annotations

import io
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://intervals.icu/api/v1"
_TIMEOUT = httpx.Timeout(60.0)


class IntervalsIcuClient:
    """Minimal Intervals.icu client for pushing GPX activities."""

    def __init__(self, api_key: str, athlete_id: str) -> None:
        self.athlete_id = athlete_id
        # Intervals.icu uses HTTP Basic Auth: username="API_KEY", password=<api_key>
        self._auth = ("API_KEY", api_key)

    async def upload_gpx(
        self,
        gpx_bytes: bytes,
        name: str,
        sport_type: Optional[str] = None,
        description: Optional[str] = None,
        external_id: Optional[str] = None,
    ) -> str:
        """Upload a GPX file to Intervals.icu and return the activity id.

        Endpoint: POST /api/v1/athlete/{id}/activities
        Returns the created activity id as a string.
        """
        url = f"{BASE_URL}/athlete/{self.athlete_id}/activities"

        # Intervals.icu accepts multipart form with a 'file' field
        files = {
            "file": (
                f"{external_id or 'activity'}.gpx",
                io.BytesIO(gpx_bytes),
                "application/gpx+xml",
            )
        }
        data: dict = {}
        if name:
            data["name"] = name
        if description:
            data["description"] = description
        if sport_type:
            data["type"] = sport_type

        async with httpx.AsyncClient(auth=self._auth, timeout=_TIMEOUT) as client:
            resp = await client.post(url, data=data, files=files)
            resp.raise_for_status()

        activity = resp.json()
        activity_id = str(activity.get("id", ""))
        logger.info(
            "IntervalsIcu: uploaded '%s' (external_id=%s) → activity_id=%s",
            name,
            external_id,
            activity_id,
        )
        return activity_id

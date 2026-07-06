"""Runalyze API client for pushing activities via GPX upload."""

from __future__ import annotations

import io
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://runalyze.com/api/v1"
_TIMEOUT = httpx.Timeout(60.0)


class RunalyzeClient:
    """Minimal Runalyze client for pushing GPX activities.

    Authentication: personal access token sent as ``token`` query parameter.
    Rate limit: 30 requests / minute (documented).  Callers are responsible for
    honouring this; individual uploads are not further rate-limited here.
    """

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    async def upload_gpx(
        self,
        gpx_bytes: bytes,
        external_id: Optional[str] = None,
    ) -> str:
        """Upload a GPX file to Runalyze and return the activity id.

        Endpoint: POST /api/v1/activities
        The Runalyze API accepts multipart/form-data with a 'file' field and
        the token in the query string.
        Returns the created activity id as a string.
        """
        url = f"{BASE_URL}/activities"
        filename = f"{external_id or 'activity'}.gpx"

        files = {"file": (filename, io.BytesIO(gpx_bytes), "application/gpx+xml")}
        params = {"token": self.access_token}

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, params=params, files=files)
            resp.raise_for_status()

        activity = resp.json()
        activity_id = str(activity.get("activityId", ""))
        logger.info(
            "Runalyze: uploaded '%s' → activityId=%s",
            filename,
            activity_id,
        )
        return activity_id

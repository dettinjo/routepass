"""Garmin Connect client for fetching activities and downloading GPX files.

Uses the `garminconnect` PyPI package (unofficial but widely-used, same
pattern as Komoot's unofficial v007 API). All blocking SDK calls are wrapped
in `asyncio.to_thread` so they don't stall the async event loop.

Credentials (email + password) are Fernet-encrypted in the Connection table
and decrypted immediately before constructing this client — they are never
stored as plain text anywhere.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class GarminClient:
    """Async-compatible wrapper around the synchronous garminconnect SDK."""

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._client: object | None = None  # garminconnect.Garmin

    async def _ensure_connected(self) -> None:
        """Lazy-initialise and log in to Garmin Connect (once per instance)."""
        if self._client is not None:
            return
        try:
            import garminconnect  # optional dependency
        except ImportError as exc:
            raise RuntimeError(
                "garminconnect package is not installed. "
                "Add garminconnect to requirements.txt and rebuild the image."
            ) from exc

        client = garminconnect.Garmin(self._email, self._password)
        await asyncio.to_thread(client.login)
        self._client = client
        logger.debug("GarminClient: logged in as %s", self._email)

    async def get_activities_since(
        self,
        since: datetime,
        limit: int = 100,
    ) -> list[dict]:
        """Return activities newer than *since*.

        Returns raw Garmin activity dicts (whatever the SDK provides). An
        empty list is returned on error so the caller can continue gracefully.
        """
        await self._ensure_connected()
        start_date = since.strftime("%Y-%m-%d")
        end_date = datetime.now(UTC).strftime("%Y-%m-%d")
        try:
            activities = await asyncio.to_thread(
                self._client.get_activities_by_date,  # type: ignore[union-attr]
                start_date,
                end_date,
                limit,
            )
            return activities or []
        except Exception as exc:
            logger.error(
                "GarminClient.get_activities_since(%s..%s) failed: %s", start_date, end_date, exc
            )
            return []

    async def download_gpx(self, activity_id: str) -> bytes:
        """Download a GPX file for a single Garmin activity.

        Raises on failure so the caller can decide whether to skip or retry.
        """
        await self._ensure_connected()
        try:
            import garminconnect  # noqa: F401 — needed for ActivityDownloadFormat

            gpx_data = await asyncio.to_thread(
                self._client.download_activity,  # type: ignore[union-attr]
                int(activity_id),
                dl_fmt=self._client.ActivityDownloadFormat.GPX,  # type: ignore[union-attr]
            )
            return gpx_data
        except Exception as exc:
            logger.error("GarminClient.download_gpx(%s) failed: %s", activity_id, exc)
            raise

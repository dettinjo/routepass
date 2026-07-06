from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.core.sports import KOMOOT_TO_STRAVA, STRAVA_TO_KOMOOT

UTC = timezone.utc

logger = logging.getLogger(__name__)

BASE_URL = "https://www.komoot.de/api/v007"

# All valid Komoot sport type identifiers (the keys of KOMOOT_TO_STRAVA minus sentinel)
_KOMOOT_SPORTS: frozenset[str] = frozenset(k for k in KOMOOT_TO_STRAVA if k != "_default")


def to_strava_sport(sport: str) -> str:
    """Convert any stored sport type (Komoot or Strava) to a Strava sport_type string."""
    # Already Strava format — return as-is (identity for all known Strava types)
    if sport in STRAVA_TO_KOMOOT:
        return sport
    return KOMOOT_TO_STRAVA.get(sport, KOMOOT_TO_STRAVA.get("_default", "Workout"))


def to_komoot_sport(sport: str) -> str:
    """Convert any stored sport type (Komoot or Strava) to a Komoot sport string."""
    # Already Komoot format
    if sport in _KOMOOT_SPORTS:
        return sport
    return STRAVA_TO_KOMOOT.get(sport, "touringbike")


@dataclass
class Tour:
    id: str
    name: str
    description: str
    sport: str
    strava_sport: str
    date: datetime
    distance_m: float
    elevation_up_m: float
    duration_seconds: Optional[int] = None


def _parse_date(raw: str) -> datetime:
    """Parse Komoot date strings."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse Komoot date: {raw!r}")


class KomootClient:
    def __init__(self, email: str, password: str, user_id: str) -> None:
        self.email = email
        self.password = password
        self.user_id = user_id

        # We will reuse this client per instance method call.
        self._client_kwargs: dict = {
            "auth": (email, password),
            "headers": {"Accept": "application/hal+json, application/json"},
            "timeout": httpx.Timeout(30.0),
        }

    async def _get(self, path: str, **kwargs: Any) -> Any:
        url = f"{BASE_URL}{path}"
        async with httpx.AsyncClient(**self._client_kwargs) as client:
            response = await client.get(url, **kwargs)
            response.raise_for_status()
            return response.json()

    async def _iter_tour_pages(self) -> AsyncGenerator:
        """Yield raw tour dicts from all pages."""
        page = 0
        while True:
            data = await self._get(
                f"/users/{self.user_id}/tours/",
                params={"type": "tour_recorded", "limit": 50, "page": page},
            )
            tours = data.get("_embedded", {}).get("tours", [])
            if not tours:
                break

            for tour in tours:
                yield tour

            total_pages = data.get("page", {}).get("totalPages", 1)
            page += 1
            if page >= total_pages:
                break

    async def get_tours(self, since: datetime) -> list:
        """Return recorded tours newer than `since`, sorted oldest-first."""
        results: list = []
        async for raw in self._iter_tour_pages():
            try:
                date = _parse_date(raw["date"])
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping tour %s — bad date: %s", raw.get("id"), exc)
                continue

            if date <= since:
                break

            description = raw.get("description") or ""
            sport = raw.get("sport", "")

            results.append(
                Tour(
                    id=str(raw["id"]),
                    name=raw.get("name", "Komoot Activity"),
                    description=description,
                    sport=sport,
                    strava_sport=to_strava_sport(sport),
                    date=date,
                    distance_m=float(raw.get("distance", 0)),
                    elevation_up_m=float(raw.get("elevation_up", 0)),
                    duration_seconds=int(raw["duration"]) if raw.get("duration") else None,
                )
            )

        results.sort(key=lambda t: t.date)
        logger.info("Found %d new Komoot tours since %s", len(results), since.isoformat())
        return results

    async def delete_tour(self, tour_id: str) -> None:
        """Delete a tour from Komoot. Returns silently if the API doesn't support deletion."""
        url = f"{BASE_URL}/tours/{tour_id}"
        async with httpx.AsyncClient(
            auth=(self.email, self.password),
            timeout=httpx.Timeout(30.0),
        ) as client:
            resp = await client.delete(url)
            if resp.status_code == 405:
                # Komoot's unofficial API may not expose DELETE — log and move on
                logger.warning("Komoot DELETE /tours/%s → 405 (not supported)", tour_id)
                return
            resp.raise_for_status()
            logger.debug("Deleted Komoot tour %s", tour_id)

    async def download_gpx(self, tour_id: str) -> bytes:
        """Download the GPX file for a tour and return the raw bytes."""
        url = f"{BASE_URL}/tours/{tour_id}.gpx"
        async with httpx.AsyncClient(**self._client_kwargs) as client:
            response = await client.get(url, timeout=60.0)
            response.raise_for_status()
            logger.debug("Downloaded GPX for tour %s (%d bytes)", tour_id, len(response.content))
            return response.content

    async def upload_tour(
        self,
        gpx_bytes: bytes,
        name: str,
        sport_type: str,
        description: str = "",
    ) -> str:
        """Upload a GPX file to Komoot as a recorded tour and return the new tour ID.

        Uses the unofficial Komoot API v007. The GPX is sent as application/gpx+xml
        with sport and name passed as query parameters.
        Raises httpx.HTTPStatusError on API errors, ValueError if the response
        contains no tour ID.
        """
        logger.info(
            "Uploading GPX to Komoot: %r (%d bytes, sport=%s)", name, len(gpx_bytes), sport_type
        )

        # Komoot v007 upload quirks (discovered empirically):
        # - Endpoint: POST /tours/ (not /users/{id}/tours/ — that returns 405)
        # - Content-Type must be application/octet-stream (not application/gpx+xml)
        # - data_type=gpx query param is required; without it the server returns
        #   "data_type must not be null"
        headers = {
            "Accept": "application/hal+json, application/json",
            "Content-Type": "application/octet-stream",
        }

        async with httpx.AsyncClient(
            auth=(self.email, self.password),
            timeout=httpx.Timeout(60.0),
        ) as client:
            resp = await client.post(
                f"{BASE_URL}/tours/",
                params={"sport": sport_type, "name": name, "data_type": "gpx"},
                content=gpx_bytes,
                headers=headers,
            )
            if not resp.is_success:
                logger.error(
                    "Komoot upload %s — body: %s",
                    resp.status_code,
                    resp.text[:500],
                )
            resp.raise_for_status()
            data = resp.json()
            logger.debug("Komoot upload response: %s", data)

            # Komoot may nest the tour under _embedded or return id at top level
            tour_id = (
                data.get("id")
                or (data.get("_embedded") or {}).get("tour", {}).get("id")
                or (data.get("tour") or {}).get("id")
            )
            if not tour_id:
                raise ValueError(f"Komoot upload returned no tour ID: {data!r}")

            logger.info("Komoot tour created — id=%s", tour_id)
            return str(tour_id)

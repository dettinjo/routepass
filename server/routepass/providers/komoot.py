"""Komoot client for the unofficial web API (v006 for login, v007 for tours).

The API is undocumented and may change; every call fails with KomootError so the
sync engine can retry later instead of crashing.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)

V006 = "https://api.komoot.de/v006"
V007 = "https://www.komoot.de/api/v007"
_ACCEPT = {"Accept": "application/hal+json, application/json"}


class KomootError(Exception):
    pass


class KomootAuthError(KomootError):
    pass


def login(email: str, password: str) -> dict[str, Any]:
    """Validate credentials and return {user_id, display_name}."""
    try:
        resp = httpx.get(
            f"{V006}/account/email/{email}/", auth=(email, password), headers=_ACCEPT, timeout=20
        )
    except httpx.HTTPError as exc:
        raise KomootError(f"Could not reach Komoot: {exc}") from exc
    if resp.status_code in (401, 403):
        raise KomootAuthError("Komoot rejected the email/password")
    if resp.status_code >= 400:
        raise KomootError(f"Komoot login returned {resp.status_code}")
    data = resp.json()
    user_id = str(data.get("username") or "")
    if not user_id:
        raise KomootError("Komoot login succeeded but returned no user id")
    user = data.get("user") or {}
    return {"user_id": user_id, "display_name": user.get("displayname") or data.get("displayname") or ""}


class KomootClient:
    def __init__(self, email: str, password: str, user_id: str) -> None:
        self.user_id = user_id
        self._http = httpx.Client(auth=(email, password), headers=_ACCEPT, timeout=httpx.Timeout(60.0))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> KomootClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _call(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = self._http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise KomootError(f"Komoot {method} {url}: {exc}") from exc
        if resp.status_code in (401, 403):
            raise KomootAuthError(f"Komoot {method} {url} → {resp.status_code}")
        if resp.status_code >= 400:
            raise KomootError(f"Komoot {method} {url} → {resp.status_code}: {resp.text[:300]}")
        return resp

    def iter_recorded_tours(self, page_size: int = 100) -> Iterator[dict[str, Any]]:
        """All recorded tours, newest first."""
        page = 0
        while True:
            data = self._call(
                "GET",
                f"{V007}/users/{self.user_id}/tours/",
                params={
                    "type": "tour_recorded",
                    "limit": page_size,
                    "page": page,
                    "sort_field": "date",
                    "sort_direction": "desc",
                    "status": "private,public,friends",
                },
            ).json()
            tours = (data.get("_embedded") or {}).get("tours") or []
            yield from tours
            total_pages = (data.get("page") or {}).get("totalPages", 1)
            page += 1
            if not tours or page >= total_pages:
                return

    def tour(self, tour_id: str) -> dict[str, Any]:
        return self._call("GET", f"{V007}/tours/{tour_id}").json()

    def coordinates(self, tour_id: str) -> list[dict[str, Any]]:
        """Track points: {lat, lng, alt, t} where t = ms since start."""
        data = self._call("GET", f"{V007}/tours/{tour_id}/coordinates").json()
        return data.get("items") or []

    def gpx(self, tour_id: str) -> bytes:
        return self._call("GET", f"{V007}/tours/{tour_id}.gpx").content

    def upload_gpx(self, gpx: bytes, name: str, sport: str) -> str:
        # v007 quirks: POST /tours/ with octet-stream body and data_type=gpx, else 400/405.
        resp = self._call(
            "POST",
            f"{V007}/tours/",
            params={"data_type": "gpx", "sport": sport, "name": name},
            content=gpx,
            headers={"Content-Type": "application/octet-stream"},
        )
        data = resp.json()
        tour_id = (
            data.get("id")
            or ((data.get("_embedded") or {}).get("tour") or {}).get("id")
            or (data.get("tour") or {}).get("id")
        )
        if not tour_id:
            raise KomootError(f"Komoot upload returned no tour id: {str(data)[:300]}")
        return str(tour_id)

    def update_tour(self, tour_id: str, **fields: Any) -> None:
        self._call("PATCH", f"{V007}/tours/{tour_id}", json=fields)

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

    def tour_details(self, tour_id: str) -> dict[str, Any]:
        """Fetch full tour metadata including title and description/notes."""
        data = self.tour(tour_id)
        name = str(data.get("name") or "").strip()
        desc = ""
        for key in ("description", "summary", "text", "notes"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                desc = val.strip()
                break
        return {"id": str(data.get("id") or tour_id), "name": name, "description": desc, "raw": data}

    def tour_photos(self, tour_id: str) -> list[dict[str, Any]]:
        """List photos attached to a Komoot recorded tour (from /images and /timeline)."""
        photos: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        def _normalize_url(src: str) -> str:
            # Komoot returns URI templates like https://photos.komoot.de/...{?width,height,crop,q}
            base = src.split("{", 1)[0].strip()
            if not base:
                return ""
            if "{" in src:
                sep = "&" if "?" in base else "?"
                return f"{base}{sep}width=2048&height=2048&crop=false&q=90"
            return base

        def _add_item(item: dict[str, Any]) -> None:
            if not isinstance(item, dict):
                return
            src = str(item.get("src") or item.get("url") or "").strip()
            if not src:
                return
            url = _normalize_url(src)
            if not url:
                return
            pid = str(item.get("id") or url.split("?", 1)[0])
            if pid in seen_ids:
                return
            seen_ids.add(pid)
            loc = item.get("location") if isinstance(item.get("location"), dict) else {}
            caption = str(item.get("name") or item.get("caption") or item.get("text") or "").strip()
            photos.append(
                {
                    "id": pid,
                    "url": url,
                    "caption": caption,
                    "lat": loc.get("lat"),
                    "lng": loc.get("lng"),
                }
            )

        # Primary endpoint: /v007/tours/{id}/images
        try:
            data = self._call("GET", f"{V007}/tours/{tour_id}/images", params={"limit": 100}).json()
            items = (data.get("_embedded") or {}).get("items") or data.get("items") or []
            for it in items:
                _add_item(it)
        except KomootError as exc:
            logger.debug("Komoot /images lookup skipped for tour %s: %s", tour_id, exc)

        # Fallback / supplement: /v007/tours/{id}/timeline
        if not photos:
            try:
                tl = self._call("GET", f"{V007}/tours/{tour_id}/timeline", params={"limit": 100}).json()
                items = (tl.get("_embedded") or {}).get("items") or tl.get("items") or []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    ref = (it.get("_embedded") or {}).get("reference")
                    if isinstance(ref, dict) and (it.get("type") == "image" or ref.get("src")):
                        _add_item(ref)
                    elif it.get("src"):
                        _add_item(it)
            except KomootError as exc:
                logger.debug("Komoot /timeline lookup skipped for tour %s: %s", tour_id, exc)

        return photos

    def download_photo(self, url: str) -> tuple[bytes, str]:
        """Download a Komoot photo and return (bytes, content_type)."""
        try:
            resp = httpx.get(url, follow_redirects=True, timeout=30.0)
        except httpx.HTTPError as exc:
            raise KomootError(f"Could not download Komoot photo {url}: {exc}") from exc
        if resp.status_code >= 400:
            raise KomootError(f"Komoot photo download returned {resp.status_code}")
        ctype = (resp.headers.get("content-type") or "image/jpeg").split(";", 1)[0].strip()
        if not ctype.startswith("image/"):
            ctype = "image/jpeg"
        return resp.content, ctype


# ── route suggestions (read-only) ──────────────────────────────────────────────


def _komoot_image(tour: dict[str, Any], width: int = 400, height: int = 260) -> str | None:
    """Static map of a tour from its URI template (…{?width,height,crop} or …/?width={width}…)."""
    src = ((tour.get("map_image") or {}).get("src") or "").strip()
    if not src:
        return None
    return (
        src.replace("{width}", str(width)).replace("{height}", str(height)).replace("{crop}", "true")
        if "{width}" in src
        else src.split("{", 1)[0] + f"?width={width}&height={height}&crop=true"
    )


def planned_tours(client: KomootClient, max_tours: int = 300) -> list[dict[str, Any]]:
    """The user's saved (planned) tours, newest first, up to max_tours."""
    out: list[dict[str, Any]] = []
    page = 0
    while len(out) < max_tours:
        data = client._call(
            "GET",
            f"{V007}/users/{client.user_id}/tours/",
            params={
                "type": "tour_planned",
                "limit": 100,
                "page": page,
                "sort_field": "date",
                "sort_direction": "desc",
                "status": "private,public,friends",
            },
        ).json()
        tours = (data.get("_embedded") or {}).get("tours") or []
        out.extend(tours)
        page += 1
        if not tours or page >= (data.get("page") or {}).get("totalPages", 1):
            break
    return [{**t, "_image": _komoot_image(t)} for t in out[:max_tours]]


def discover_tours(
    client: KomootClient,
    lat: float,
    lng: float,
    *,
    sport: str,
    radius_km: float,
    min_length_m: int | None = None,
    max_length_m: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Komoot's suggested tours (editorial and community) starting near a point."""
    params: dict[str, Any] = {
        "lat": f"{lat:.5f}",
        "lng": f"{lng:.5f}",
        "sport": sport,
        "max_distance": int(radius_km * 1000),
        "limit": limit,
    }
    if min_length_m:
        params["min_length"] = int(min_length_m)
    if max_length_m:
        params["max_length"] = int(max_length_m)
    data = client._call("GET", f"{V007}/discover_tours/", params=params).json()
    items = (data.get("_embedded") or {}).get("items") or []
    return [{**t, "_image": _komoot_image(t)} for t in items]


def tour_coordinates(client: KomootClient, tour_id: str, discovered: bool) -> list[tuple[float, float]]:
    if discovered:
        data = client._call(
            "GET", f"{V007}/discover_tours/{tour_id}", params={"_embedded": "coordinates"}
        ).json()
        items = ((data.get("_embedded") or {}).get("coordinates") or {}).get("items") or []
    else:
        items = client.coordinates(tour_id)
    return [(float(p["lat"]), float(p["lng"])) for p in items if p.get("lat") is not None]


def planner_url(lat: float, lng: float, sport: str) -> str:
    return f"https://www.komoot.com/plan/@{lat:.5f},{lng:.5f},13z?sport={sport}"

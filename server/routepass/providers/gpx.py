"""GPX writer and Google polyline helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from xml.sax.saxutils import escape

import numpy as np

from routepass.analysis.track import NormalizedTrack


def track_to_gpx(track: NormalizedTrack, name: str, sport: str, start: datetime) -> bytes:
    """Serialize a track with time, elevation and Garmin TrackPointExtension (hr/cad/temp)."""
    if track.lat is None or track.lon is None:
        return b""
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="RoutePass" xmlns="http://www.topografix.com/GPX/1/1"'
        ' xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">',
        f"<metadata><name>{escape(name)}</name><time>{start:%Y-%m-%dT%H:%M:%SZ}</time></metadata>",
        f"<trk><name>{escape(name)}</name><type>{escape(sport)}</type><trkseg>",
    ]

    def val(arr: np.ndarray | None, i: int) -> float | None:
        if arr is None:
            return None
        v = float(arr[i])
        return None if np.isnan(v) else v

    for i in range(track.n):
        lat, lon = val(track.lat, i), val(track.lon, i)
        if lat is None or lon is None:
            continue
        parts = [f'<trkpt lat="{lat:.7f}" lon="{lon:.7f}">']
        if (ele := val(track.elevation_m, i)) is not None:
            parts.append(f"<ele>{ele:.1f}</ele>")
        t = start + timedelta(seconds=float(track.time_s[i]))
        parts.append(f"<time>{t:%Y-%m-%dT%H:%M:%SZ}</time>")
        ext = []
        if (hr := val(track.hr, i)) is not None:
            ext.append(f"<gpxtpx:hr>{int(hr)}</gpxtpx:hr>")
        if (cad := val(track.cadence, i)) is not None:
            ext.append(f"<gpxtpx:cad>{int(cad)}</gpxtpx:cad>")
        if (temp := val(track.temp, i)) is not None:
            ext.append(f"<gpxtpx:atemp>{temp:.1f}</gpxtpx:atemp>")
        if ext or (pw := val(track.power, i)) is not None:
            parts.append("<extensions>")
            if (pw := val(track.power, i)) is not None:
                parts.append(f"<power>{int(pw)}</power>")
            if ext:
                parts.append("<gpxtpx:TrackPointExtension>" + "".join(ext) + "</gpxtpx:TrackPointExtension>")
            parts.append("</extensions>")
        parts.append("</trkpt>")
        out.append("".join(parts))
    out.append("</trkseg></trk></gpx>")
    return "\n".join(out).encode()


def encode_polyline(points: list[tuple[float, float]]) -> str:
    result = []
    prev_lat = prev_lng = 0
    for lat, lng in points:
        ilat, ilng = round(lat * 1e5), round(lng * 1e5)
        for delta in (ilat - prev_lat, ilng - prev_lng):
            v = ~(delta << 1) if delta < 0 else delta << 1
            while v >= 0x20:
                result.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            result.append(chr(v + 63))
        prev_lat, prev_lng = ilat, ilng
    return "".join(result)


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode a Google polyline; a truncated or malformed string yields the points decoded so far."""
    try:
        return _decode(encoded)
    except IndexError:
        return []


def _decode(encoded: str) -> list[tuple[float, float]]:
    coords: list[tuple[float, float]] = []
    index = lat = lng = 0
    while index < len(encoded):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lng += delta
        coords.append((lat / 1e5, lng / 1e5))
    return coords


def simplify(points: list[tuple[float, float]], max_points: int = 300) -> list[tuple[float, float]]:
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    picked = [points[int(i * step)] for i in range(max_points)]
    picked[-1] = points[-1]
    return picked

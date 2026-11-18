"""Track normalization and metric computation.

Pure numpy, no I/O. A recording from any provider (Strava streams, Komoot coordinates,
GPX) becomes a NormalizedTrack; compute() turns it into a summary, detail blocks
(zones, splits, climbs, decoupling), best efforts and a downsampled chart series.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

EARTH_RADIUS_M = 6_371_000.0
ELE_SMOOTH = 5
ELE_HYSTERESIS_M = 2.0
MOVING_SPEED_MS = 0.5
MAX_GAP_S = 60  # gaps longer than this count as paused
CHART_POINTS = 1200
HR_ZONE_FRACTIONS = (0.60, 0.70, 0.80, 0.90)
POWER_ZONE_FRACTIONS = (0.55, 0.75, 0.90, 1.05, 1.20, 1.50)
POWER_CURVE_S = (5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200)
BEST_DISTANCES_M = {
    "run": (400, 1000, 1609, 5000, 10000, 21097, 42195),
    "walk": (1000, 5000, 10000, 21097, 42195),
    "ride": (5000, 10000, 20000, 40000, 50000, 100000, 160934),
}
CLIMB_MIN_GAIN_M = 30.0
CLIMB_MAX_DIP_M = 15.0
CLIMB_MIN_GRADE_PCT = 2.0
# Fallback load per hour when neither power nor heart rate is available.
ESTIMATED_LOAD_PER_HOUR = {"ride": 45.0, "run": 65.0, "walk": 35.0, "winter": 50.0, "water": 45.0}


@dataclass
class NormalizedTrack:
    time_s: np.ndarray
    lat: np.ndarray | None = None
    lon: np.ndarray | None = None
    elevation_m: np.ndarray | None = None
    distance_m: np.ndarray | None = None
    hr: np.ndarray | None = None
    power: np.ndarray | None = None
    cadence: np.ndarray | None = None
    temp: np.ndarray | None = None
    speed_ms: np.ndarray | None = None
    moving: np.ndarray | None = None

    CHANNELS = ("lat", "lon", "elevation_m", "distance_m", "hr", "power", "cadence", "temp", "speed_ms")

    @property
    def n(self) -> int:
        return int(self.time_s.shape[0])

    @property
    def has_gps(self) -> bool:
        return self.lat is not None and self.lon is not None

    def channels(self) -> list[str]:
        return [c for c in self.CHANNELS if getattr(self, c) is not None]

    # (attribute, key, scale): values are stored as delta-encoded int32 of value*scale.
    _PACK = (
        ("time_s", "t", 10),
        ("lat", "lat", 1e6),
        ("lon", "lon", 1e6),
        ("elevation_m", "ele", 10),
        ("distance_m", "d", 10),
        ("hr", "hr", 1),
        ("power", "pw", 1),
        ("cadence", "cad", 1),
        ("temp", "temp", 10),
        ("speed_ms", "v", 100),
        ("moving", "mv", 1),
    )
    _NAN = np.iinfo(np.int32).min

    def pack(self) -> bytes:
        header: dict[str, Any] = {"n": self.n, "v": 2, "ch": []}
        blobs = []
        for attr, key, scale in self._PACK:
            a = getattr(self, attr)
            if a is None:
                continue
            a = np.asarray(a, dtype="float64")
            nan = np.isnan(a)
            q = np.round(np.where(nan, 0, a) * scale).astype(np.int64)
            delta = np.diff(q, prepend=0).astype(np.int32)
            delta[nan] = self._NAN
            # NaN positions break the delta chain; store absolute value right after a gap
            after = np.zeros_like(nan)
            after[1:] = nan[:-1]
            fix = after & ~nan
            delta[fix] = q[fix].astype(np.int32)
            header["ch"].append([key, scale, int(fix.sum() > 0 or nan.any())])
            blobs.append(delta.tobytes())
        head = json.dumps(header).encode()
        return zlib.compress(len(head).to_bytes(4, "little") + head + b"".join(blobs), 6)

    @classmethod
    def unpack(cls, blob: bytes) -> NormalizedTrack:
        raw = zlib.decompress(blob)
        hlen = int.from_bytes(raw[:4], "little")
        header = json.loads(raw[4 : 4 + hlen])
        n = header["n"]
        offset = 4 + hlen
        keymap = {key: (attr, scale) for attr, key, scale in cls._PACK}
        values: dict[str, np.ndarray] = {}
        for key, scale, gappy in header["ch"]:
            delta = np.frombuffer(raw, dtype=np.int32, count=n, offset=offset).astype(np.int64)
            offset += 4 * n
            if gappy:
                nan = delta == cls._NAN
                q = np.zeros(n, dtype=np.int64)
                acc = 0
                prev_nan = False
                for i in range(n):
                    if nan[i]:
                        prev_nan = True
                        continue
                    acc = delta[i] if prev_nan else acc + delta[i]
                    q[i] = acc
                    prev_nan = False
                out = q.astype("float64") / scale
                out[nan] = np.nan
            else:
                out = np.cumsum(delta).astype("float64") / scale
            attr, _ = keymap[key]
            values[attr] = out
        moving = values.pop("moving", None)
        return cls(**values, moving=moving.astype(bool) if moving is not None else None)


def pack_points(points: list[dict[str, Any]]) -> bytes:
    keys = list(points[0]) if points else []
    cols = {k: [p[k] for p in points] for k in keys}
    return zlib.compress(json.dumps(cols, separators=(",", ":")).encode(), 6)


def unpack_points(blob: bytes | None) -> list[dict[str, Any]]:
    if not blob:
        return []
    cols = json.loads(zlib.decompress(blob))
    keys = list(cols)
    n = len(cols[keys[0]]) if keys else 0
    return [{k: cols[k][i] for k in keys} for i in range(n)]


@dataclass
class TrackResult:
    summary: dict[str, Any]
    detail: dict[str, Any]
    points: list[dict[str, Any]]
    efforts: list[tuple[str, int, float]]  # (kind, key, value)
    channels: list[str] = field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────────────


def _arr(data: list | None) -> np.ndarray | None:
    if not data:
        return None
    a = np.asarray([np.nan if v is None else v for v in data], dtype="float64")
    if a.size == 0 or np.all(np.isnan(a)):
        return None
    return a


def haversine_cumulative(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    lat_r, lon_r = np.radians(lat), np.radians(lon)
    a = (
        np.sin(np.diff(lat_r) / 2) ** 2
        + np.cos(lat_r[:-1]) * np.cos(lat_r[1:]) * np.sin(np.diff(lon_r) / 2) ** 2
    )
    seg = 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    seg = np.nan_to_num(seg)
    return np.concatenate([[0.0], np.cumsum(seg)])


def _smooth(a: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or a.size < window:
        return a
    pad = window // 2
    padded = np.pad(a, pad, mode="edge")  # edge-pad: zero-pad would fake a cliff at the ends
    return np.convolve(padded, np.ones(window) / window, mode="valid")[: a.size]


def _fill_nan(a: np.ndarray) -> np.ndarray:
    mask = np.isnan(a)
    if not mask.any():
        return a
    if mask.all():
        return np.zeros_like(a)
    idx = np.arange(a.size)
    return np.interp(idx, idx[~mask], a[~mask])


def elevation_gain_loss(elevation: np.ndarray) -> tuple[float, float]:
    """Hysteresis accumulation: filters GPS noise without discarding steady grades."""
    valid = elevation[~np.isnan(elevation)]
    if valid.size < 2:
        return 0.0, 0.0
    s = _smooth(valid, ELE_SMOOTH)
    gain = loss = 0.0
    ref = s[0]
    for e in s[1:]:
        if e - ref >= ELE_HYSTERESIS_M:
            gain += e - ref
            ref = e
        elif ref - e >= ELE_HYSTERESIS_M:
            loss += ref - e
            ref = e
    return float(gain), float(loss)


def _stat(a: np.ndarray | None, fn) -> float | None:
    if a is None:
        return None
    v = a[~np.isnan(a)]
    return None if v.size == 0 else round(float(fn(v)), 2)


def _lttb(x: np.ndarray, y: np.ndarray, n_out: int) -> np.ndarray:
    n = x.shape[0]
    if n_out >= n or n_out < 3:
        return np.arange(n)
    out = np.empty(n_out, dtype=int)
    out[0], out[-1] = 0, n - 1
    bucket = (n - 2) / (n_out - 2)
    a = 0
    for i in range(n_out - 2):
        start = int(np.floor((i + 1) * bucket)) + 1
        end = min(int(np.floor((i + 2) * bucket)) + 1, n)
        ns = int(np.floor(i * bucket)) + 1
        ne = min(int(np.floor((i + 1) * bucket)) + 1, n)
        avg_x = np.mean(x[ns:ne]) if ne > ns else x[a]
        avg_y = np.mean(y[ns:ne]) if ne > ns else y[a]
        rng = np.arange(start, end)
        if rng.size:
            area = np.abs((x[a] - avg_x) * (y[rng] - y[a]) - (x[a] - x[rng]) * (avg_y - y[a]))
            a = int(rng[int(np.argmax(area))])
        out[i + 1] = a
    return out


# ── normalizers ──────────────────────────────────────────────────────────────


def from_strava_streams(streams: dict[str, Any]) -> NormalizedTrack | None:
    def data(key: str) -> list | None:
        return (streams.get(key) or {}).get("data")

    time = _arr(data("time"))
    latlng = data("latlng")
    n = time.shape[0] if time is not None else (len(latlng) if latlng else 0)
    if n < 2:
        return None
    if time is None:
        time = np.arange(n, dtype="float64")
    lat = lon = None
    if latlng and len(latlng) == n:
        ll = np.asarray(latlng, dtype="float64")
        lat, lon = ll[:, 0], ll[:, 1]
    dist = _arr(data("distance"))
    if dist is None and lat is not None:
        dist = haversine_cumulative(lat, lon)
    moving = data("moving")
    return NormalizedTrack(
        time_s=time,
        lat=lat,
        lon=lon,
        elevation_m=_arr(data("altitude")),
        distance_m=dist,
        hr=_arr(data("heartrate")),
        power=_arr(data("watts")),
        cadence=_arr(data("cadence")),
        temp=_arr(data("temp")),
        speed_ms=_arr(data("velocity_smoothed")),
        moving=np.asarray(moving, dtype=bool) if moving and len(moving) == n else None,
    )


def from_komoot_coordinates(items: list[dict[str, Any]]) -> NormalizedTrack | None:
    if len(items) < 2:
        return None
    lat = np.asarray([p.get("lat", np.nan) for p in items], dtype="float64")
    lon = np.asarray([p.get("lng", np.nan) for p in items], dtype="float64")
    alt = _arr([p.get("alt") for p in items])
    t_raw = [p.get("t") for p in items]
    if all(t is None for t in t_raw):
        time = np.arange(len(items), dtype="float64")
    else:
        time = _fill_nan(np.asarray([np.nan if t is None else t for t in t_raw], dtype="float64")) / 1000.0
        time = time - time[0]
    return NormalizedTrack(
        time_s=time, lat=lat, lon=lon, elevation_m=alt, distance_m=haversine_cumulative(lat, lon)
    )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def from_gpx(gpx: bytes) -> NormalizedTrack | None:
    try:
        root = ET.fromstring(gpx)
    except ET.ParseError:
        return None
    cols: dict[str, list[float]] = {k: [] for k in ("lat", "lon", "ele", "t", "hr", "cad", "temp", "pw")}
    for pt in root.iter():
        if _local(pt.tag) != "trkpt":
            continue
        try:
            lat, lon = float(pt.get("lat")), float(pt.get("lon"))
        except (TypeError, ValueError):
            continue
        row = dict.fromkeys(("ele", "t", "hr", "cad", "temp", "pw"), np.nan)
        for child in pt:
            name = _local(child.tag)
            if name == "ele" and child.text:
                row["ele"] = float(child.text)
            elif name == "time" and child.text:
                try:
                    row["t"] = datetime.fromisoformat(child.text.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    pass
            elif name == "extensions":
                for ext in child.iter():
                    en, txt = _local(ext.tag), ext.text
                    if not txt or not txt.strip():
                        continue
                    try:
                        val = float(txt)
                    except ValueError:
                        continue
                    if en in ("hr", "heartrate"):
                        row["hr"] = val
                    elif en in ("cad", "cadence"):
                        row["cad"] = val
                    elif en in ("atemp", "temp"):
                        row["temp"] = val
                    elif en in ("power", "pwr", "PowerInWatts"):
                        row["pw"] = val
        cols["lat"].append(lat)
        cols["lon"].append(lon)
        for k, v in row.items():
            cols[k].append(v)
    if len(cols["lat"]) < 2:
        return None
    lat, lon = np.asarray(cols["lat"]), np.asarray(cols["lon"])
    t = np.asarray(cols["t"])
    time = np.arange(lat.size, dtype="float64") if np.all(np.isnan(t)) else _fill_nan(t) - np.nanmin(t)

    def ch(k: str) -> np.ndarray | None:
        a = np.asarray(cols[k], dtype="float64")
        return None if np.all(np.isnan(a)) else a

    return NormalizedTrack(
        time_s=time,
        lat=lat,
        lon=lon,
        elevation_m=ch("ele"),
        distance_m=haversine_cumulative(lat, lon),
        hr=ch("hr"),
        power=ch("pw"),
        cadence=ch("cad"),
        temp=ch("temp"),
    )


# ── metrics ──────────────────────────────────────────────────────────────────


def _dt(track: NormalizedTrack) -> np.ndarray:
    dt = np.diff(track.time_s, prepend=track.time_s[0])
    dt[(dt < 0) | (dt > MAX_GAP_S)] = 0
    return dt


def _speed(track: NormalizedTrack) -> np.ndarray | None:
    if track.speed_ms is not None:
        return track.speed_ms
    if track.distance_m is None:
        return None
    dt = np.diff(track.time_s, prepend=track.time_s[0])
    dd = np.diff(track.distance_m, prepend=track.distance_m[0])
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.where(dt > 0, dd / dt, np.nan)
    return _smooth(_fill_nan(v), 5)


def _moving_mask(track: NormalizedTrack, speed: np.ndarray | None) -> np.ndarray:
    if track.moving is not None and track.moving.shape[0] == track.n:
        return track.moving
    if speed is None:
        return np.ones(track.n, dtype=bool)
    return np.nan_to_num(speed) > MOVING_SPEED_MS


def _resample_1hz(track: NormalizedTrack, values: np.ndarray) -> np.ndarray:
    t = track.time_s
    if t[-1] - t[0] > 24 * 3600:
        return np.array([])
    grid = np.arange(t[0], t[-1] + 1, 1.0)
    v = np.nan_to_num(values)
    out = np.interp(grid, t, v)
    # zero out resampled samples that fall into recording gaps
    idx = np.searchsorted(t, grid)
    idx = np.clip(idx, 1, t.size - 1)
    gaps = (t[idx] - t[idx - 1]) > MAX_GAP_S
    out[gaps] = 0
    return out


def power_curve(track: NormalizedTrack) -> dict[int, float]:
    if track.power is None:
        return {}
    p = _resample_1hz(track, track.power)
    out: dict[int, float] = {}
    if p.size == 0:
        return out
    csum = np.concatenate([[0.0], np.cumsum(p)])
    for d in POWER_CURVE_S:
        if p.size >= d:
            out[d] = round(float(np.max(csum[d:] - csum[:-d]) / d), 1)
    return out


def normalized_power(track: NormalizedTrack) -> float | None:
    if track.power is None:
        return None
    p = _resample_1hz(track, track.power)
    if p.size < 30:
        return None
    rolled = np.convolve(p, np.ones(30) / 30, mode="valid")
    return float(np.mean(rolled**4) ** 0.25)


def best_times(track: NormalizedTrack, distances: tuple[int, ...]) -> dict[int, float]:
    """Fastest elapsed time to cover each distance (two-pointer sweep)."""
    if track.distance_m is None:
        return {}
    d = np.maximum.accumulate(_fill_nan(track.distance_m))
    t = track.time_s
    out: dict[int, float] = {}
    for target in distances:
        if d[-1] - d[0] < target:
            continue
        # for every end point j, the latest start i with d[j] - d[i] >= target
        i = np.searchsorted(d, d - target, side="right") - 1
        ok = i >= 0
        if not ok.any():
            continue
        spans = t[ok] - t[i[ok]]
        spans = spans[spans > 0]
        if spans.size:
            out[target] = round(float(spans.min()), 1)
    return out


def detect_climbs(track: NormalizedTrack) -> list[dict[str, Any]]:
    if track.elevation_m is None or track.distance_m is None or track.n < 10:
        return []
    ele = _smooth(_fill_nan(track.elevation_m), 9)
    d, t = track.distance_m, track.time_s
    climbs: list[dict[str, Any]] = []
    start = low = 0
    peak = 0
    i = 1
    while i < ele.size:
        if ele[i] > ele[peak]:
            peak = i
        if ele[i] < ele[low] and peak <= low:
            start = low = i
            peak = i
        elif ele[peak] - ele[i] > CLIMB_MAX_DIP_M or i == ele.size - 1:
            gain = ele[peak] - ele[start]
            grade = gain / max(float(d[peak] - d[start]), 1.0) * 100
            if gain >= CLIMB_MIN_GAIN_M and d[peak] > d[start] and grade >= CLIMB_MIN_GRADE_PCT:
                length = float(d[peak] - d[start])
                dur = float(t[peak] - t[start])
                climbs.append(
                    {
                        "start_m": round(float(d[start]), 0),
                        "end_m": round(float(d[peak]), 0),
                        "length_m": round(length, 0),
                        "gain_m": round(float(gain), 0),
                        "grade_pct": round(float(gain) / length * 100, 1),
                        "duration_s": round(dur, 0),
                        "vam": round(float(gain) / (dur / 3600), 0) if dur > 0 else None,
                        "top_m": round(float(ele[peak]), 0),
                    }
                )
            start = low = peak = i
        i += 1
    return climbs


def _zones(values: np.ndarray, dt: np.ndarray, bounds: list[float]) -> list[float]:
    v = np.nan_to_num(values, nan=-1.0)
    idx = np.digitize(v, bounds)
    return [round(float(np.sum(dt[(idx == z) & (v >= 0)])), 0) for z in range(len(bounds) + 1)]


def _splits(track: NormalizedTrack, split_m: float) -> list[dict[str, Any]]:
    if track.distance_m is None or track.n < 2:
        return []
    d = track.distance_m
    out = []
    prev = 0
    boundary = d[0] + split_m
    while prev < track.n - 1:
        i = int(np.searchsorted(d, boundary))
        i = min(i, track.n - 1)
        if i <= prev:
            break
        seg = slice(prev, i + 1)
        dt = float(track.time_s[i] - track.time_s[prev])
        dd = float(d[i] - d[prev])
        if dd < split_m * 0.1 and out:
            break
        gain, loss = (0.0, 0.0)
        if track.elevation_m is not None:
            gain, loss = elevation_gain_loss(track.elevation_m[seg])
        out.append(
            {
                "index": len(out) + 1,
                "distance_m": round(dd, 0),
                "duration_s": round(dt, 0),
                "speed_ms": round(dd / dt, 3) if dt > 0 else None,
                "hr": _stat(track.hr[seg] if track.hr is not None else None, np.mean),
                "power": _stat(track.power[seg] if track.power is not None else None, np.mean),
                "gain_m": round(gain, 0),
                "loss_m": round(loss, 0),
            }
        )
        prev = i
        boundary += split_m
    return out


def _decoupling(track: NormalizedTrack, moving: np.ndarray, speed: np.ndarray | None) -> dict | None:
    if track.hr is None:
        return None
    metric = track.power if track.power is not None else speed
    if metric is None:
        return None
    idx = np.where(moving)[0]
    if idx.size < 4:
        return None
    t = track.time_s[idx]
    if float(t[-1] - t[0]) < 1200:
        return None
    mid = t[0] + (t[-1] - t[0]) / 2
    h1, h2 = idx[t <= mid], idx[t > mid]
    hr1, hr2 = _stat(track.hr[h1], np.mean), _stat(track.hr[h2], np.mean)
    m1, m2 = _stat(metric[h1], np.mean), _stat(metric[h2], np.mean)
    if not (hr1 and hr2 and m1 and m2):
        return None
    r1, r2 = m1 / hr1, m2 / hr2
    return {
        "metric": "power" if track.power is not None else "speed",
        "pct": round((r1 - r2) / r1 * 100, 1),
    }


def _downsample(track: NormalizedTrack, speed: np.ndarray | None) -> list[dict[str, Any]]:
    x = track.distance_m if track.distance_m is not None else track.time_s
    y = track.elevation_m if track.elevation_m is not None else (track.hr if track.hr is not None else x)
    idx = _lttb(x.astype("float64"), np.nan_to_num(y).astype("float64"), CHART_POINTS)

    def at(a: np.ndarray | None, i: int, digits: int) -> float | None:
        if a is None:
            return None
        v = float(a[i])
        return None if np.isnan(v) else round(v, digits)

    return [
        {
            "t": round(float(track.time_s[i]), 0),
            "d": at(track.distance_m, i, 0),
            "ele": at(track.elevation_m, i, 1),
            "hr": at(track.hr, i, 0),
            "pw": at(track.power, i, 0),
            "cad": at(track.cadence, i, 0),
            "v": at(speed, i, 2),
            "temp": at(track.temp, i, 1),
            "lat": at(track.lat, i, 5),
            "lon": at(track.lon, i, 5),
        }
        for i in idx
    ]


def compute_load(
    *,
    family: str,
    moving_s: float | None,
    np_power: float | None,
    avg_hr: float | None,
    ftp: int | None,
    hr_max: int | None,
    hr_rest: int | None,
) -> tuple[float | None, str | None, float | None]:
    """Training load (TSS scale): power TSS → heart-rate TSS → duration estimate."""
    if not moving_s or moving_s <= 0:
        return None, None, None
    hours = moving_s / 3600.0
    if np_power and ftp:
        intensity = np_power / ftp
        return round(hours * intensity**2 * 100, 1), "power", round(intensity, 3)
    if avg_hr and hr_max:
        rest = hr_rest or 0
        # Heart-rate reserve when resting HR is known; threshold ≈ 90% of HRmax / HRR
        frac = (avg_hr - rest) / (hr_max - rest) if hr_max > rest else avg_hr / hr_max
        intensity = max(frac, 0) / 0.9
        return round(hours * intensity**2 * 100, 1), "heartrate", round(intensity, 3)
    per_hour = ESTIMATED_LOAD_PER_HOUR.get(family)
    if per_hour:
        return round(hours * per_hour, 1), "estimate", None
    return None, None, None


def compute(
    track: NormalizedTrack,
    *,
    family: str = "other",
    ftp: int | None = None,
    hr_max: int | None = None,
    hr_rest: int | None = None,
) -> TrackResult:
    summary: dict[str, Any] = {}
    detail: dict[str, Any] = {}
    efforts: list[tuple[str, int, float]] = []
    if track.n < 2:
        return TrackResult(summary, detail, [], efforts, [])

    speed = _speed(track)
    moving = _moving_mask(track, speed)
    dt = _dt(track)
    summary["elapsed_time_s"] = round(float(track.time_s[-1] - track.time_s[0]), 0)
    summary["moving_time_s"] = round(float(np.sum(dt[moving])), 0)

    if track.distance_m is not None:
        summary["distance_m"] = round(float(track.distance_m[-1] - track.distance_m[0]), 1)
        if summary["moving_time_s"] > 0:
            summary["avg_speed_ms"] = round(summary["distance_m"] / summary["moving_time_s"], 3)
        if speed is not None:
            summary["max_speed_ms"] = _stat(_smooth(_fill_nan(speed), 5), np.max)

    if track.elevation_m is not None:
        gain, loss = elevation_gain_loss(track.elevation_m)
        summary["elevation_gain_m"] = round(gain, 0)
        summary["elevation_loss_m"] = round(loss, 0)
        summary["elevation_max_m"] = _stat(track.elevation_m, np.max)
        summary["elevation_min_m"] = _stat(track.elevation_m, np.min)
        climbs = detect_climbs(track)
        detail["climbs"] = climbs
        if climbs:
            efforts.append(("climb", 0, max(c["gain_m"] for c in climbs)))

    if track.hr is not None:
        summary["avg_hr"] = _stat(track.hr[moving] if moving.any() else track.hr, np.mean)
        summary["max_hr"] = _stat(track.hr, np.max)
        zmax = hr_max or summary["max_hr"]
        if zmax:
            bounds = [f * zmax for f in HR_ZONE_FRACTIONS]
            detail["hr_zones"] = {
                "bounds": [round(b) for b in bounds],
                "seconds": _zones(track.hr, dt, bounds),
                "basis": "profile" if hr_max else "activity max",
            }

    np_power = None
    if track.power is not None:
        summary["avg_power"] = _stat(track.power, np.mean)
        summary["max_power"] = _stat(track.power, np.max)
        np_power = normalized_power(track)
        if np_power:
            summary["normalized_power"] = round(np_power, 0)
        summary["work_kj"] = round(float(np.sum(np.nan_to_num(track.power) * dt)) / 1000, 0)
        curve = power_curve(track)
        detail["power_curve"] = curve
        efforts += [("power", k, v) for k, v in curve.items()]
        if ftp:
            bounds = [f * ftp for f in POWER_ZONE_FRACTIONS]
            detail["power_zones"] = {
                "bounds": [round(b) for b in bounds],
                "seconds": _zones(track.power, dt, bounds),
                "ftp": ftp,
            }

    load, method, intensity = compute_load(
        family=family,
        moving_s=summary.get("moving_time_s"),
        np_power=np_power,
        avg_hr=summary.get("avg_hr"),
        ftp=ftp,
        hr_max=hr_max,
        hr_rest=hr_rest,
    )
    if load is not None:
        summary["load"], summary["load_method"], summary["intensity"] = load, method, intensity

    if track.cadence is not None:
        nz = track.cadence[track.cadence > 0]
        summary["avg_cadence"] = _stat(nz if nz.size else track.cadence, np.mean)
    if track.temp is not None:
        summary["avg_temp"] = _stat(track.temp, np.mean)
        detail["temp_range"] = [_stat(track.temp, np.min), _stat(track.temp, np.max)]

    if (dec := _decoupling(track, moving, speed)) is not None:
        detail["decoupling"] = dec

    distances = BEST_DISTANCES_M.get(family)
    if distances:
        best = best_times(track, distances)
        detail["best_times"] = best
        efforts += [("time", k, v) for k, v in best.items()]

    detail["splits"] = _splits(track, 5000.0 if family == "ride" else 1000.0)
    detail["split_m"] = 5000 if family == "ride" else 1000

    if track.has_gps:
        valid = ~(np.isnan(track.lat) | np.isnan(track.lon))
        if valid.any():
            first, last = np.argmax(valid), track.n - 1 - np.argmax(valid[::-1])
            summary["start_lat"], summary["start_lng"] = float(track.lat[first]), float(track.lon[first])
            summary["end_lat"], summary["end_lng"] = float(track.lat[last]), float(track.lon[last])

    return TrackResult(summary, detail, _downsample(track, speed), efforts, track.channels())

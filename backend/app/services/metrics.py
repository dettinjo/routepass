"""Track metric computation engine.

Pure, numpy-based functions that turn a recorded track (Strava streams or a parsed
GPX with extensions) into: a scalar summary (distance/time/elevation/HR/power/…),
detail blocks (HR & power zones, per-km splits), and an LTTB-downsampled per-point
series for charts. No DB, no I/O — everything here is testable with synthetic input.

See docs/GPX_ANALYSIS_PLAN.md.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ── Tunables ────────────────────────────────────────────────────────────────

_EARTH_RADIUS_M = 6_371_000.0
_ELEVATION_SMOOTH_WINDOW = 5  # points; reduces GPS altitude noise before summing
_ELEVATION_HYSTERESIS_M = 2.0  # gain/loss only accrues after moving this far from ref
_MOVING_SPEED_THRESHOLD_MS = 0.5  # below this we treat the athlete as stopped
_NP_ROLL_SECONDS = 30  # normalized-power rolling window
_SPLIT_DISTANCE_M = 1000.0
_MAX_TRACK_POINTS = 1000  # downsample target for the chart series

# Default HR zone upper bounds as a fraction of HR max (Z1..Z5; Z5 = the rest).
_HR_ZONE_FRACTIONS = (0.60, 0.70, 0.80, 0.90)
# Coggan power zones as a fraction of FTP (Z1..Z7; Z7 = the rest).
_POWER_ZONE_FRACTIONS = (0.55, 0.75, 0.90, 1.05, 1.20, 1.50)


# ── Normalized track ─────────────────────────────────────────────────────────


@dataclass
class NormalizedTrack:
    """All channels aligned by index; any channel may be None if not recorded."""

    time_s: np.ndarray  # seconds from start (always present)
    lat: np.ndarray | None = None
    lon: np.ndarray | None = None
    elevation_m: np.ndarray | None = None
    distance_m: np.ndarray | None = None  # cumulative metres
    hr: np.ndarray | None = None
    power: np.ndarray | None = None
    cadence: np.ndarray | None = None
    temp: np.ndarray | None = None
    speed_ms: np.ndarray | None = None
    moving: np.ndarray | None = None  # bool

    @property
    def n(self) -> int:
        return int(self.time_s.shape[0]) if self.time_s is not None else 0


@dataclass
class MetricsResult:
    summary: dict[str, Any]
    detail: dict[str, Any]
    track_points: list[dict[str, Any]]
    available: list[str] = field(default_factory=list)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _arr(data: list | None) -> np.ndarray | None:
    if not data:
        return None
    a = np.asarray(data, dtype="float64")
    return a if a.size else None


def _haversine_cumulative(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)
    dlat = np.diff(lat_r)
    dlon = np.diff(lon_r)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat_r[:-1]) * np.cos(lat_r[1:]) * np.sin(dlon / 2) ** 2
    seg = 2 * _EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return np.concatenate([[0.0], np.cumsum(seg)])


def _smooth(a: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or a.size < window:
        return a
    pad = window // 2
    # Edge-pad (not zero-pad) so a non-zero baseline doesn't get a fake cliff at
    # the ends — that would inflate elevation gain massively.
    padded = np.pad(a, pad, mode="edge")
    kernel = np.ones(window) / window
    smoothed = np.convolve(padded, kernel, mode="valid")
    return smoothed[: a.size]


def _elevation_gain_loss(elevation: np.ndarray) -> tuple[float, float]:
    """Hysteresis accumulation: robust for both dense 1 Hz streams (where a naive
    per-diff threshold would zero out real climbs) and sparse GPX. Gain/loss only
    accrue once elevation has moved _ELEVATION_HYSTERESIS_M from the last reference,
    which filters GPS altitude noise without discarding steady grades."""
    valid = elevation[~np.isnan(elevation)]
    if valid.size < 2:
        return 0.0, 0.0
    smoothed = _smooth(valid, _ELEVATION_SMOOTH_WINDOW)
    thr = _ELEVATION_HYSTERESIS_M
    gain = loss = 0.0
    ref = smoothed[0]
    for e in smoothed[1:]:
        if e - ref >= thr:
            gain += e - ref
            ref = e
        elif ref - e >= thr:
            loss += ref - e
            ref = e
    return gain, loss


def _safe_stat(a: np.ndarray | None, fn) -> float | None:
    if a is None or a.size == 0:
        return None
    valid = a[~np.isnan(a)]
    if valid.size == 0:
        return None
    return float(fn(valid))


def _lttb_indices(x: np.ndarray, y: np.ndarray, n_out: int) -> np.ndarray:
    """Largest-Triangle-Three-Buckets downsampling → indices that preserve shape."""
    n = x.shape[0]
    if n_out >= n or n_out < 3:
        return np.arange(n)

    out = np.empty(n_out, dtype=int)
    out[0] = 0
    out[-1] = n - 1
    bucket = (n - 2) / (n_out - 2)
    a = 0
    for i in range(n_out - 2):
        start = int(np.floor((i + 1) * bucket)) + 1
        end = min(int(np.floor((i + 2) * bucket)) + 1, n)
        nstart = int(np.floor(i * bucket)) + 1
        nend = min(int(np.floor((i + 1) * bucket)) + 1, n)
        avg_x = np.mean(x[nstart:nend]) if nend > nstart else x[a]
        avg_y = np.mean(y[nstart:nend]) if nend > nstart else y[a]
        rng = np.arange(start, end)
        area = np.abs((x[a] - avg_x) * (y[rng] - y[a]) - (x[a] - x[rng]) * (avg_y - y[a]))
        a = int(rng[int(np.argmax(area))]) if rng.size else a
        out[i + 1] = a
    return out


# ── Normalizers ──────────────────────────────────────────────────────────────


def normalize_strava_streams(streams: dict[str, Any]) -> NormalizedTrack | None:
    """Convert a Strava streams dict (key_by_type=true) into a NormalizedTrack."""
    time = _arr((streams.get("time") or {}).get("data"))
    latlng = (streams.get("latlng") or {}).get("data")
    n = None
    if time is not None:
        n = time.shape[0]
    elif latlng:
        n = len(latlng)
    if not n:
        return None

    if time is None:
        time = np.arange(n, dtype="float64")

    lat = lon = None
    if latlng:
        ll = np.asarray(latlng, dtype="float64")
        lat, lon = ll[:, 0], ll[:, 1]

    dist = _arr((streams.get("distance") or {}).get("data"))
    if dist is None and lat is not None:
        dist = _haversine_cumulative(lat, lon)

    moving_raw = (streams.get("moving") or {}).get("data")
    moving = np.asarray(moving_raw, dtype=bool) if moving_raw else None

    return NormalizedTrack(
        time_s=time,
        lat=lat,
        lon=lon,
        elevation_m=_arr((streams.get("altitude") or {}).get("data")),
        distance_m=dist,
        hr=_arr((streams.get("heartrate") or {}).get("data")),
        power=_arr((streams.get("watts") or {}).get("data")),
        cadence=_arr((streams.get("cadence") or {}).get("data")),
        temp=_arr((streams.get("temp") or {}).get("data")),
        speed_ms=_arr((streams.get("velocity_smoothed") or {}).get("data")),
        moving=moving,
    )


_GPXTPX = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
_PWR = "http://www.garmin.com/xmlschemas/PowerExtension/v1"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_gpx(gpx_bytes: bytes) -> NormalizedTrack | None:
    """Parse GPX bytes into a NormalizedTrack, including Garmin TrackPointExtension
    (heart rate, cadence, temperature) and PowerExtension where present."""
    from datetime import datetime

    try:
        root = ET.fromstring(gpx_bytes)
    except ET.ParseError:
        return None

    lats, lons, eles, times, hrs, cads, temps, powers = [], [], [], [], [], [], [], []
    for pt in root.iter():
        if _local(pt.tag) != "trkpt":
            continue
        try:
            lats.append(float(pt.get("lat")))
            lons.append(float(pt.get("lon")))
        except (TypeError, ValueError):
            continue
        ele = t = hr = cad = temp = power = np.nan
        for child in pt:
            name = _local(child.tag)
            if name == "ele" and child.text:
                ele = float(child.text)
            elif name == "time" and child.text:
                try:
                    t = datetime.fromisoformat(child.text.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    pass
            elif name == "extensions":
                for ext in child.iter():
                    en = _local(ext.tag)
                    if not ext.text:
                        continue
                    if en in ("hr", "heartrate"):
                        hr = float(ext.text)
                    elif en in ("cad", "cadence"):
                        cad = float(ext.text)
                    elif en in ("atemp", "temp"):
                        temp = float(ext.text)
                    elif en in ("power", "pwr", "PowerInWatts"):
                        power = float(ext.text)
        eles.append(ele)
        times.append(t)
        hrs.append(hr)
        cads.append(cad)
        temps.append(temp)
        powers.append(power)

    if not lats:
        return None

    lat = np.asarray(lats)
    lon = np.asarray(lons)
    time_raw = np.asarray(times)
    if np.all(np.isnan(time_raw)):
        time_s = np.arange(lat.shape[0], dtype="float64")
    else:
        base = np.nanmin(time_raw)
        time_s = np.where(np.isnan(time_raw), np.arange(lat.shape[0]), time_raw - base)

    def _channel(vals: list) -> np.ndarray | None:
        a = np.asarray(vals, dtype="float64")
        return a if not np.all(np.isnan(a)) else None

    return NormalizedTrack(
        time_s=time_s,
        lat=lat,
        lon=lon,
        elevation_m=_channel(eles),
        distance_m=_haversine_cumulative(lat, lon),
        hr=_channel(hrs),
        power=_channel(powers),
        cadence=_channel(cads),
        temp=_channel(temps),
    )


# ── Metric computation ───────────────────────────────────────────────────────


def _moving_mask(track: NormalizedTrack) -> np.ndarray:
    if track.moving is not None and track.moving.shape[0] == track.n:
        return track.moving
    speed = track.speed_ms
    if speed is None and track.distance_m is not None and track.n > 1:
        dt = np.diff(track.time_s, prepend=track.time_s[0])
        dt[dt <= 0] = np.nan
        speed = np.diff(track.distance_m, prepend=track.distance_m[0]) / dt
    if speed is None:
        return np.ones(track.n, dtype=bool)
    return np.nan_to_num(speed) > _MOVING_SPEED_THRESHOLD_MS


def _normalized_power(power: np.ndarray, time_s: np.ndarray) -> float | None:
    if power is None or power.size < _NP_ROLL_SECONDS:
        return None
    # Assume ~1 Hz (Strava power streams are per-second); rolling 30-sample mean.
    p = np.nan_to_num(power)
    kernel = np.ones(_NP_ROLL_SECONDS) / _NP_ROLL_SECONDS
    rolled = np.convolve(p, kernel, mode="valid")
    if rolled.size == 0:
        return None
    return float(np.mean(rolled**4) ** 0.25)


_DECOUPLING_MIN_MOVING_S = 1200.0  # 20 min — shorter/non-steady efforts don't drift meaningfully


def _decoupling(track: NormalizedTrack, moving: np.ndarray) -> dict[str, Any] | None:
    """Aerobic decoupling: % drift in effort-per-heartbeat from the first half
    of the activity to the second half (Pw:Hr if power is present, else Pa:Hr
    using raw speed — not grade-adjusted). Positive = cardiac drift (HR rising
    relative to output, a sign of aerobic fatigue or heat); requires HR plus
    power or speed and >=20 min moving time, since shorter or intermittent
    efforts don't produce a stable enough ratio to compare halves.
    """
    if track.hr is None:
        return None
    metric = track.power if track.power is not None else track.speed_ms
    metric_name = "power" if track.power is not None else "speed"
    if metric is None:
        return None

    idx = np.where(moving)[0]
    if idx.size < 4:
        return None
    t = track.time_s[idx]
    if float(t[-1] - t[0]) < _DECOUPLING_MIN_MOVING_S:
        return None

    mid_time = t[0] + (t[-1] - t[0]) / 2
    half1 = idx[t <= mid_time]
    half2 = idx[t > mid_time]
    if half1.size < 2 or half2.size < 2:
        return None

    hr1 = _safe_stat(track.hr[half1], np.mean)
    hr2 = _safe_stat(track.hr[half2], np.mean)
    m1 = _safe_stat(metric[half1], np.mean)
    m2 = _safe_stat(metric[half2], np.mean)
    if not hr1 or not hr2 or not m1 or not m2:
        return None

    ratio1 = m1 / hr1
    ratio2 = m2 / hr2
    if ratio1 == 0:
        return None
    return {
        "metric": metric_name,
        "pct": round((ratio1 - ratio2) / ratio1 * 100, 1),
        "first_half_ratio": round(ratio1, 4),
        "second_half_ratio": round(ratio2, 4),
    }


def _zones(values: np.ndarray, time_s: np.ndarray, bounds: list[float]) -> list[float]:
    """Seconds spent in each zone. len == len(bounds)+1."""
    dt = np.diff(time_s, prepend=time_s[0])
    dt[dt <= 0] = 0
    dt[dt > 60] = 0  # ignore big gaps (paused)
    out = [0.0] * (len(bounds) + 1)
    v = np.nan_to_num(values, nan=-1.0)
    idx = np.digitize(v, bounds)
    for zi in range(len(out)):
        out[zi] = float(np.sum(dt[(idx == zi) & (v >= 0)]))
    return out


def _splits(track: NormalizedTrack) -> list[dict[str, Any]]:
    if track.distance_m is None or track.n < 2:
        return []
    dist = track.distance_m
    total = dist[-1]
    splits = []
    boundary = _SPLIT_DISTANCE_M
    prev_i = 0
    n_splits = int(total // _SPLIT_DISTANCE_M) + 1
    for _ in range(n_splits):
        i = int(np.searchsorted(dist, boundary))
        if i >= track.n:
            i = track.n - 1
        if i <= prev_i:
            break
        seg = slice(prev_i, i + 1)
        dt = float(track.time_s[i] - track.time_s[prev_i])
        dd = float(dist[i] - dist[prev_i])
        gain = 0.0
        if track.elevation_m is not None:
            gain, _ = _elevation_gain_loss(track.elevation_m[seg])
        splits.append(
            {
                "index": len(splits) + 1,
                "distance_m": round(dd, 1),
                "duration_s": round(dt, 1),
                "speed_ms": round(dd / dt, 3) if dt > 0 else None,
                "avg_hr": _safe_stat(track.hr[seg] if track.hr is not None else None, np.mean),
                "avg_power": _safe_stat(
                    track.power[seg] if track.power is not None else None, np.mean
                ),
                "elevation_gain_m": round(gain, 1),
            }
        )
        prev_i = i
        boundary += _SPLIT_DISTANCE_M
    return splits


def _downsample(track: NormalizedTrack) -> list[dict[str, Any]]:
    if track.n == 0:
        return []
    x = track.distance_m if track.distance_m is not None else track.time_s
    y = track.elevation_m if track.elevation_m is not None else track.time_s
    idx = _lttb_indices(x.astype("float64"), np.nan_to_num(y).astype("float64"), _MAX_TRACK_POINTS)

    def at(a: np.ndarray | None, i: int):
        if a is None:
            return None
        v = a[i]
        return None if isinstance(v, float) and np.isnan(v) else round(float(v), 3)

    points = []
    for i in idx:
        points.append(
            {
                "t": round(float(track.time_s[i]), 1),
                "d": at(track.distance_m, i),
                "ele": at(track.elevation_m, i),
                "hr": at(track.hr, i),
                "power": at(track.power, i),
                "cad": at(track.cadence, i),
                "speed": at(track.speed_ms, i),
                "temp": at(track.temp, i),
                "lat": at(track.lat, i),
                "lon": at(track.lon, i),
            }
        )
    return points


def compute_metrics(
    track: NormalizedTrack,
    *,
    sport_type: str | None = None,
    ftp: int | None = None,
    hr_max: int | None = None,
    calories_hint: float | None = None,
) -> MetricsResult:
    """Compute the full metric set from a NormalizedTrack."""
    summary: dict[str, Any] = {}
    detail: dict[str, Any] = {}
    available: list[str] = []

    if track.n < 2:
        return MetricsResult(summary=summary, detail=detail, track_points=[], available=available)

    moving = _moving_mask(track)
    dt = np.diff(track.time_s, prepend=track.time_s[0])
    dt[dt < 0] = 0
    dt[dt > 60] = 0  # drop paused gaps

    summary["elapsed_time_s"] = round(float(track.time_s[-1] - track.time_s[0]), 1)
    summary["moving_time_s"] = round(float(np.sum(dt[moving])), 1)

    if track.distance_m is not None:
        available.append("distance")
        total_d = float(track.distance_m[-1])
        summary["distance_m"] = round(total_d, 1)
        if summary["moving_time_s"] > 0:
            summary["avg_speed_ms"] = round(total_d / summary["moving_time_s"], 3)
        summary["max_speed_ms"] = _safe_stat(track.speed_ms, np.max)

    if track.elevation_m is not None:
        available.append("elevation")
        gain, loss = _elevation_gain_loss(track.elevation_m)
        summary["elevation_gain_m"] = round(gain, 1)
        summary["elevation_loss_m"] = round(loss, 1)
        summary["elevation_min_m"] = _safe_stat(track.elevation_m, np.min)
        summary["elevation_max_m"] = _safe_stat(track.elevation_m, np.max)
        if summary["moving_time_s"] and summary["moving_time_s"] > 0:
            summary["vam_mh"] = round(gain / (summary["moving_time_s"] / 3600.0), 1)

    if track.hr is not None:
        available.append("heartrate")
        summary["avg_hr"] = _safe_stat(track.hr, np.mean)
        summary["max_hr"] = _safe_stat(track.hr, np.max)
        zmax = hr_max or summary["max_hr"]
        if zmax:
            bounds = [f * zmax for f in _HR_ZONE_FRACTIONS]
            detail["hr_zones"] = {
                "bounds": [round(b, 1) for b in bounds],
                "seconds": [round(s, 1) for s in _zones(track.hr, track.time_s, bounds)],
                "hr_max_used": round(float(zmax), 1),
            }

    if track.power is not None:
        available.append("power")
        summary["avg_power"] = _safe_stat(track.power, np.mean)
        summary["max_power"] = _safe_stat(track.power, np.max)
        np_power = _normalized_power(track.power, track.time_s)
        if np_power is not None:
            summary["normalized_power"] = round(np_power, 1)
            if ftp:
                intensity = np_power / ftp
                summary["intensity_factor"] = round(intensity, 3)
                summary["tss"] = round(
                    (summary["moving_time_s"] * np_power * intensity) / (ftp * 3600) * 100, 1
                )
                detail["tss_method"] = "power"
        # Work in kJ (∫ power dt); for cycling kcal ≈ kJ (human ~24% efficiency).
        work_kj = float(np.sum(np.nan_to_num(track.power) * dt) / 1000.0)
        summary["work_kj"] = round(work_kj, 1)
        if calories_hint is None:
            calories_hint = work_kj
        if ftp:
            bounds = [f * ftp for f in _POWER_ZONE_FRACTIONS]
            detail["power_zones"] = {
                "bounds": [round(b, 1) for b in bounds],
                "seconds": [round(s, 1) for s in _zones(track.power, track.time_s, bounds)],
                "ftp_used": ftp,
            }

    # hrTSS fallback: mirrors the power-TSS formula shape (moving_hours *
    # IF^2 * 100) with %HRmax standing in for IF, for sports/activities with
    # no power meter — the only way most runners/hikers get a TSS at all.
    if "tss" not in summary and track.hr is not None and hr_max and summary.get("avg_hr"):
        hr_intensity = summary["avg_hr"] / hr_max
        if hr_intensity > 0 and summary.get("moving_time_s"):
            summary["tss"] = round((summary["moving_time_s"] / 3600.0) * (hr_intensity**2) * 100, 1)
            detail["tss_method"] = "hr_estimate"

    decoupling = _decoupling(track, moving)
    if decoupling is not None:
        detail["decoupling"] = decoupling
        available.append("decoupling")

    if track.cadence is not None:
        available.append("cadence")
        nz = track.cadence[track.cadence > 0]
        summary["avg_cadence"] = _safe_stat(nz if nz.size else track.cadence, np.mean)
        summary["max_cadence"] = _safe_stat(track.cadence, np.max)

    if track.temp is not None:
        available.append("temperature")
        summary["avg_temp"] = _safe_stat(track.temp, np.mean)
        summary["min_temp"] = _safe_stat(track.temp, np.min)
        summary["max_temp"] = _safe_stat(track.temp, np.max)

    if calories_hint is not None:
        summary["calories"] = round(float(calories_hint), 0)

    detail["splits"] = _splits(track)
    if sport_type:
        summary["sport_type"] = sport_type

    return MetricsResult(
        summary=summary,
        detail=detail,
        track_points=_downsample(track),
        available=available,
    )

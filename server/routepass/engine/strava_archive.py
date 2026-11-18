"""Import Strava's bulk data export ("Download your account" archive).

Every Strava user may export their own data for free (Strava API Policy §6.6). The archive holds
`activities.csv` plus the original recordings (FIT / GPX / TCX, often gzipped). This module turns it into
`strava` provider records — keyed by Strava's activity id, so a later API import updates the same rows —
and stores the recordings as tracks. Deduplication against Komoot happens through the normal matching.
"""

from __future__ import annotations

import csv
import gzip
import io
import logging
import re
import threading
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from routepass import store
from routepass.analysis import track as trk
from routepass.config import get_settings
from routepass.db import session_scope
from routepass.engine import ingest
from routepass.models import Activity, ProviderActivity
from routepass.providers import sports
from routepass.providers.gpx import encode_polyline, simplify
from routepass.timeutil import iso, utcnow

logger = logging.getLogger(__name__)
STATE_KEY = "strava_archive"
_lock = threading.Lock()

# Display labels in activities.csv → Strava sport_type (English labels collapse automatically).
LABEL_FIXES = {
    "rockclimb": "RockClimbing",
    "canoe": "Canoeing",
    "hiit": "HighIntensityIntervalTraining",
    "highintensityintervaltraining": "HighIntensityIntervalTraining",
    "weighttraining": "WeightTraining",
    "standuppaddling": "StandUpPaddling",
    "ebikeride": "EBikeRide",
    "emountainbikeride": "EMountainBikeRide",
    "football(soccer)": "Soccer",
    "football": "Soccer",
    # German account exports
    "radfahrt": "Ride",
    "radfahren": "Ride",
    "lauf": "Run",
    "laufen": "Run",
    "wanderung": "Hike",
    "wandern": "Hike",
    "spaziergang": "Walk",
    "gehen": "Walk",
    "e-bike-fahrt": "EBikeRide",
    "ebike-fahrt": "EBikeRide",
    "mountainbike-fahrt": "MountainBikeRide",
    "e-mountainbike-fahrt": "EMountainBikeRide",
    "gravel-fahrt": "GravelRide",
    "virtuelleradfahrt": "VirtualRide",
    "virtuellerlauf": "VirtualRun",
    "trailrun": "TrailRun",
    "schwimmen": "Swim",
    "alpinski": "AlpineSki",
    "skitour": "BackcountrySki",
    "langlauf": "NordicSki",
    "schneeschuhwandern": "Snowshoe",
    "krafttraining": "WeightTraining",
    "training": "Workout",
}
DATE_FORMATS = (
    "%b %d, %Y, %I:%M:%S %p",
    "%b %d, %Y, %H:%M:%S",
    "%d.%m.%Y, %H:%M:%S",
    "%d %b %Y, %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
)


def sport_from_label(label: str) -> str:
    raw = (label or "").strip()
    collapsed = re.sub(r"[\s\-]", "", raw)
    if collapsed in sports.STRAVA:
        return collapsed
    key = raw.lower().replace(" ", "")
    if key in LABEL_FIXES:
        return LABEL_FIXES[key]
    key2 = collapsed.lower()
    if key2 in LABEL_FIXES:
        return LABEL_FIXES[key2]
    for st in sports.STRAVA:  # case-insensitive match on the type key itself
        if st.lower() == key2:
            return st
    return "Workout"


def parse_date(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _num(raw: str | None) -> float | None:
    if raw is None:
        return None
    raw = raw.strip().replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class Row:
    """activities.csv has repeated headers (e.g. Distance in km, later Distance in m); the later,
    detailed occurrence wins."""

    def __init__(self, header: list[str], values: list[str]) -> None:
        self.cols: dict[str, list[str]] = {}
        for name, value in zip(header, values, strict=False):
            self.cols.setdefault(name.strip(), []).append(value)

    def first(self, name: str) -> str:
        v = self.cols.get(name)
        return v[0] if v else ""

    def last(self, name: str) -> str:
        v = self.cols.get(name)
        return v[-1] if v else ""

    def num(self, name: str) -> float | None:
        return _num(self.last(name))


def _read_file(zf: zipfile.ZipFile, name: str) -> tuple[bytes, str] | None:
    if not name:
        return None
    candidates = [n for n in (name, name.lstrip("./")) if n in zf.NameToInfo]
    if not candidates:
        base = name.rsplit("/", 1)[-1]
        candidates = [n for n in zf.namelist() if n.endswith("/" + base) or n == base]
    if not candidates:
        return None
    data = zf.read(candidates[0])
    lower = candidates[0].lower()
    if lower.endswith(".gz"):
        data = gzip.decompress(data)
        lower = lower[:-3]
    kind = lower.rsplit(".", 1)[-1]
    return data, kind


def parse_recording(data: bytes, kind: str) -> trk.NormalizedTrack | None:
    if kind == "fit":
        return trk.from_fit(data)
    if kind == "gpx":
        return trk.from_gpx(data)
    if kind == "tcx":
        return trk.from_tcx(data)
    return None


def _set(**fields: Any) -> None:
    with session_scope() as db:
        st = store.get_value(db, STATE_KEY) or {}
        st.update(fields)
        store.set_value(db, STATE_KEY, st)


def state(db: Session) -> dict[str, Any]:
    return store.get_value(db, STATE_KEY) or {"phase": "idle"}


def archive_dir() -> Path:
    d = get_settings().data_dir / "imports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def import_archive(path: Path) -> dict[str, Any]:
    """Synchronous import; use start() for background runs."""
    if not _lock.acquire(blocking=False):
        return {"phase": "busy"}
    try:
        return _import(path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Strava archive import failed")
        _set(phase="error", error=str(exc)[:500], finished_at=iso(utcnow()))
        return {"phase": "error", "error": str(exc)}
    finally:
        _lock.release()


def start(path: Path) -> None:
    _set(phase="queued", file=path.name, error=None, started_at=iso(utcnow()))
    threading.Thread(target=import_archive, args=(path,), daemon=True).start()


def _import(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        csv_name = next((n for n in zf.namelist() if n.lower().rsplit("/", 1)[-1] == "activities.csv"), None)
        if not csv_name:
            raise ValueError("activities.csv not found — is this Strava's 'Download your account' archive?")
        text = zf.read(csv_name).decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        rows = [Row(header, r) for r in reader if r and any(c.strip() for c in r)]
        _set(
            phase="importing",
            file=path.name,
            total=len(rows),
            done=0,
            new=0,
            updated=0,
            tracks=0,
            skipped=0,
            error=None,
            started_at=iso(utcnow()),
        )

        stats = {"new": 0, "updated": 0, "tracks": 0, "skipped": 0}
        pending_tracks: list[tuple[str, str]] = []
        with session_scope() as db:
            for i, row in enumerate(rows):
                activity_id = row.first("Activity ID").strip()
                if not activity_id:
                    stats["skipped"] += 1
                    continue
                filename = row.first("Filename").strip()
                rec_file = _read_file(zf, filename) if filename else None
                start_utc = None
                if rec_file:
                    epoch = trk.start_epoch(*rec_file)
                    if epoch:
                        start_utc = datetime.fromtimestamp(epoch, UTC).replace(tzinfo=None)
                start_utc = start_utc or parse_date(row.first("Activity Date"))
                if start_utc is None:
                    stats["skipped"] += 1
                    continue
                distance = row.num("Distance")
                if distance is not None and len(row.cols.get("Distance", [])) == 1:
                    distance *= 1000  # only the km column exists
                raw = {
                    "id": activity_id,
                    "name": row.first("Activity Name") or "Strava activity",
                    "sport_type": sport_from_label(row.first("Activity Type")),
                    "start_date": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "distance": distance,
                    "moving_time": row.num("Moving Time"),
                    "elapsed_time": _num(row.first("Elapsed Time")),
                    "total_elevation_gain": row.num("Elevation Gain"),
                    "elev_high": row.num("Elevation High"),
                    "max_speed": row.num("Max Speed"),
                    "average_speed": row.num("Average Speed"),
                    "average_heartrate": row.num("Average Heart Rate"),
                    "max_heartrate": row.num("Max Heart Rate"),
                    "average_watts": row.num("Average Watts"),
                    "weighted_average_watts": row.num("Weighted Average Power"),
                    "max_watts": row.num("Max Watts"),
                    "average_cadence": row.num("Average Cadence"),
                    "average_temp": row.num("Average Temperature"),
                    "kilojoules": (row.num("Total Work") or 0) / 1000 or None,
                    "commute": row.last("Commute").strip().lower() in ("true", "1", "1.0"),
                    "gear_id": row.first("Activity Gear") or None,
                    "description": row.first("Activity Description"),
                    "source": "archive",
                }
                raw = {k: v for k, v in raw.items() if v not in (None, "")}
                track = parse_recording(*rec_file) if rec_file else None
                if track is not None and track.has_gps:
                    pts = [
                        (a, b)
                        for a, b in zip(track.lat.tolist(), track.lon.tolist(), strict=True)
                        if a == a and b == b
                    ]
                    if len(pts) > 1:
                        raw["summary_polyline"] = encode_polyline(simplify(pts, 300))
                existed = db.scalar(
                    select(ProviderActivity.id).where(
                        ProviderActivity.provider == "strava", ProviderActivity.external_id == activity_id
                    )
                )
                result = ingest.ImportStats()
                rec = ingest.upsert_provider_record(db, "strava", raw, result)
                if rec is None:
                    stats["skipped"] += 1
                    continue
                stats["updated" if existed else "new"] += 1
                rec.track_status = "done" if track is not None else "none"
                if track is not None:
                    pending_tracks.append((activity_id, filename))
                if i % 50 == 0:
                    db.commit()  # release the write lock before the progress update (separate session)
                    _set(done=i + 1, **stats)
            db.flush()
            ingest.match_unlinked(db)
        _set(phase="tracks", done=len(rows), **stats)

        # Second pass: attach recordings to the (now matched) activities.
        for n, (activity_id, filename) in enumerate(pending_tracks):
            rec_file = _read_file(zf, filename)
            track = parse_recording(*rec_file) if rec_file else None
            if track is None:
                continue
            with session_scope() as db:
                rec = db.scalar(
                    select(ProviderActivity).where(
                        ProviderActivity.provider == "strava", ProviderActivity.external_id == activity_id
                    )
                )
                act = db.get(Activity, rec.activity_id) if rec and rec.activity_id else None
                if act is not None:
                    ingest.store_track(db, act, "strava", track)
                    stats["tracks"] += 1
            if n % 25 == 0:
                _set(tracks=stats["tracks"])

    with session_scope() as db:
        store.set_value(
            db,
            "strava.import",
            {**(store.get_value(db, "strava.import") or {}), "last_archive": iso(utcnow())},
        )
    _set(phase="finished", finished_at=iso(utcnow()), **stats)
    logger.info("Strava archive imported: %s", stats)
    return {"phase": "finished", **stats}

from __future__ import annotations

import io
import json
import logging
import math
from datetime import UTC, datetime, timedelta
from uuid import UUID

import gpxpy
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core import security
from app.core.config import settings
from app.core.rate_limit import rate_limit_guard
from app.core.sports import GPX_SPORT_TYPE_MAP
from app.db.models.connection import Connection
from app.db.models.subscription import Subscription
from app.db.models.sync import SyncedActivity
from app.db.models.user import StravaApp, User
from app.services.komoot import KomootClient
from app.services.storage import StorageService
from app.services.strava import StravaClient
from app.services.strava import streams_to_gpx as _strava_streams_to_gpx

_logger = logging.getLogger(__name__)

UTC = UTC

router = APIRouter(tags=["activities"])

_ACTIVITY_HISTORY_DAYS: dict = {"free": 30, "pro": 365, "lifetime": 365, "business": 365}


def _map_gpx_sport_type(raw: str | None) -> str | None:
    """Normalise a GPX <type> string to an internal sport_type key."""
    if not raw:
        return None
    normalised = raw.strip().lower().replace(" ", "_").replace("-", "_")
    return GPX_SPORT_TYPE_MAP.get(normalised, normalised)


# ── GPX generation ────────────────────────────────────────────────────────────


def _generate_gpx(
    name: str,
    sport_type: str,
    center_lat: float,
    center_lon: float,
    distance_m: float,
    elevation_base_m: float,
    elevation_up_m: float,
    duration_seconds: int,
    started_at: datetime,
) -> bytes:
    """Generate a valid oval-loop GPX track with realistic coordinates."""
    circumference_km = distance_m / 1000
    radius_lat = circumference_km / (2 * math.pi * 111.0)
    radius_lon = radius_lat / math.cos(math.radians(center_lat))
    n_points = max(30, min(300, int(distance_m / 100)))

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="RoutePass"',
        '     xmlns="http://www.topografix.com/GPX/1/1"',
        '     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        '     xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">',
        "  <metadata>",
        f"    <name>{name}</name>",
        f"    <time>{started_at.strftime('%Y-%m-%dT%H:%M:%SZ')}</time>",
        "  </metadata>",
        "  <trk>",
        f"    <name>{name}</name>",
        f"    <type>{sport_type}</type>",
        "    <trkseg>",
    ]

    for i in range(n_points + 1):
        frac = i / n_points
        angle = 2 * math.pi * frac
        lat = center_lat + radius_lat * math.sin(angle)
        lon = center_lon + radius_lon * math.cos(angle)
        ele = elevation_base_m + elevation_up_m * max(0.0, math.sin(math.pi * frac))
        t = started_at + timedelta(seconds=int(duration_seconds * frac))
        ts = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(
            f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}">'
            f"<ele>{ele:.1f}</ele><time>{ts}</time></trkpt>"
        )

    lines += ["    </trkseg>", "  </trk>", "</gpx>"]
    return "\n".join(lines).encode("utf-8")


# ── Strava stream → GPX conversion ───────────────────────────────────────────


def _streams_to_gpx(
    activity_name: str,
    sport_type: str,
    started_at: datetime | None,
    streams: dict,
) -> bytes:
    """Convert Strava stream data (latlng, altitude, time) to GPX bytes."""
    return _strava_streams_to_gpx(activity_name, sport_type, started_at, streams)


# ── Seed templates ────────────────────────────────────────────────────────────

_SEED_ACTIVITIES = [
    {
        "activity_name": "Morning Run",
        "sport_type": "jogging",
        "distance_m": 5200,
        "elevation_up_m": 45,
        "elevation_base_m": 408,
        "duration_seconds": 28 * 60,
        "started_at_offset_days": 1,
        "center_lat": 47.3769,
        "center_lon": 8.5417,  # Zürich
    },
    {
        "activity_name": "Long Trail Run",
        "sport_type": "trail_running",
        "distance_m": 22500,
        "elevation_up_m": 820,
        "elevation_base_m": 1034,
        "duration_seconds": 135 * 60,
        "started_at_offset_days": 2,
        "center_lat": 46.6237,
        "center_lon": 8.0342,  # Grindelwald
    },
    {
        "activity_name": "Easy Bike Ride",
        "sport_type": "touringbicycle",
        "distance_m": 12100,
        "elevation_up_m": 150,
        "elevation_base_m": 520,
        "duration_seconds": 45 * 60,
        "started_at_offset_days": 3,
        "center_lat": 48.1351,
        "center_lon": 11.5820,  # Munich
    },
    {
        "activity_name": "Road Century",
        "sport_type": "road_cycling",
        "distance_m": 102000,
        "elevation_up_m": 1200,
        "elevation_base_m": 175,
        "duration_seconds": 240 * 60,
        "started_at_offset_days": 4,
        "center_lat": 45.7640,
        "center_lon": 4.8357,  # Lyon
    },
    {
        "activity_name": "MTB Enduro",
        "sport_type": "mtb_advanced",
        "distance_m": 35000,
        "elevation_up_m": 1800,
        "elevation_base_m": 278,
        "duration_seconds": 210 * 60,
        "started_at_offset_days": 5,
        "center_lat": 47.9990,
        "center_lon": 7.8421,  # Freiburg im Breisgau
    },
    {
        "activity_name": "E-Bike Tour",
        "sport_type": "e_touringbicycle",
        "distance_m": 80000,
        "elevation_up_m": 600,
        "elevation_base_m": 435,
        "duration_seconds": 180 * 60,
        "started_at_offset_days": 6,
        "center_lat": 47.0502,
        "center_lon": 8.3093,  # Lucerne
    },
    {
        "activity_name": "Alpine Hike",
        "sport_type": "hiking",
        "distance_m": 18000,
        "elevation_up_m": 1400,
        "elevation_base_m": 575,
        "duration_seconds": 360 * 60,
        "started_at_offset_days": 7,
        "center_lat": 47.2692,
        "center_lon": 11.4041,  # Innsbruck
    },
    {
        "activity_name": "City Walk",
        "sport_type": "walking",
        "distance_m": 3500,
        "elevation_up_m": 20,
        "elevation_base_m": 171,
        "duration_seconds": 42 * 60,
        "started_at_offset_days": 8,
        "center_lat": 48.2082,
        "center_lon": 16.3738,  # Vienna
    },
    {
        "activity_name": "Ski Touring",
        "sport_type": "skitouring",
        "distance_m": 8000,
        "elevation_up_m": 900,
        "elevation_base_m": 1620,
        "duration_seconds": 270 * 60,
        "started_at_offset_days": 9,
        "center_lat": 46.0207,
        "center_lon": 7.7491,  # Zermatt
    },
    {
        "activity_name": "Pool Swim",
        "sport_type": "swimming",
        "distance_m": 2000,
        "elevation_up_m": 0,
        "elevation_base_m": 375,
        "duration_seconds": 45 * 60,
        "started_at_offset_days": 10,
        "center_lat": 46.2044,
        "center_lon": 6.1432,  # Geneva
    },
    {
        "activity_name": "Ultra Run",
        "sport_type": "running",
        "distance_m": 65000,
        "elevation_up_m": 2500,
        "elevation_base_m": 1035,
        "duration_seconds": 540 * 60,
        "started_at_offset_days": 11,
        "center_lat": 45.9237,
        "center_lon": 6.8694,  # Chamonix
    },
    {
        "activity_name": "City Commute",
        "sport_type": "citybike",
        "distance_m": 4800,
        "elevation_up_m": 30,
        "elevation_base_m": 34,
        "duration_seconds": 18 * 60,
        "started_at_offset_days": 12,
        "center_lat": 52.5200,
        "center_lon": 13.4050,  # Berlin
    },
]


# ── Serializer ────────────────────────────────────────────────────────────────


def _serialize_activity(act: SyncedActivity) -> dict:
    # Only count a platform if the activity genuinely exists there.
    # Imported/seeded activities have a fake komoot_tour_id for idempotency —
    # that must NOT appear as "Present on Komoot".
    platforms: list[str] = []
    if act.source == "komoot":
        platforms.append("komoot")
    elif act.source == "strava":
        platforms.append("strava")
    # A synced strava_activity_id means it was pushed there successfully
    if act.strava_activity_id and "strava" not in platforms:
        platforms.append("strava")
    # A real komoot_tour_id (not the seed_ sentinel) means it lives on Komoot.
    # source='import' activities can be genuinely uploaded to Komoot after import,
    # so we use the ID format rather than source to distinguish.
    if (
        act.komoot_tour_id
        and not act.komoot_tour_id.startswith("seed_")
        and "komoot" not in platforms
    ):
        platforms.append("komoot")

    return {
        "id": str(act.id),
        "source": act.source,
        "komoot_tour_id": act.komoot_tour_id,
        "strava_activity_id": act.strava_activity_id,
        "destination_platform": act.destination_platform,
        "destination_activity_id": act.destination_activity_id,
        "sync_direction": act.sync_direction,
        "sync_status": act.sync_status,
        "activity_name": act.activity_name,
        "sport_type": act.sport_type,
        "distance_m": act.distance_m,
        "elevation_up_m": act.elevation_up_m,
        "started_at": act.started_at.isoformat() if act.started_at else None,
        "synced_at": act.synced_at.isoformat(),
        "duration_seconds": act.duration_seconds,
        "conflict_reason": act.conflict_reason,
        "resolved_at": act.resolved_at.isoformat() if act.resolved_at else None,
        "platforms": platforms,
        "is_synced": len(platforms) >= 2,
        "has_gpx": act.gpx_storage_key is not None
        or act.gpx_data is not None
        or (bool(act.komoot_tour_id) and not (act.komoot_tour_id or "").startswith("seed_"))
        or (act.source == "strava" and bool(act.strava_activity_id)),
    }


# ── List ──────────────────────────────────────────────────────────────────────


# ── Shared filter builder ─────────────────────────────────────────────────────


def _build_activity_filters(
    user_id: object,
    cutoff: datetime,
    source: str | None,
    sync_status: str | None,
    sport_type: str | None,
    search: str | None,
    synced: bool | None,
    date_from: str | None,
    date_to: str | None,
) -> list:
    """Return a list of SQLAlchemy WHERE conditions for activity queries."""
    filters: list = [
        SyncedActivity.user_id == user_id,
        SyncedActivity.synced_at >= cutoff,
    ]

    if source:
        filters.append(SyncedActivity.source == source)

    if sync_status:
        filters.append(SyncedActivity.sync_status == sync_status)

    if sport_type:
        filters.append(SyncedActivity.sport_type == sport_type)

    if search:
        filters.append(func.lower(SyncedActivity.activity_name).contains(search.lower()))

    # Date range filter on started_at (activities without a start date are excluded)
    if date_from:
        try:
            dt = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            filters.append(SyncedActivity.started_at.isnot(None))
            filters.append(SyncedActivity.started_at >= dt)
        except ValueError:
            pass

    if date_to:
        try:
            dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            filters.append(SyncedActivity.started_at.isnot(None))
            filters.append(SyncedActivity.started_at <= dt)
        except ValueError:
            pass

    # synced mirrors _serialize_activity's platforms logic
    if synced is True:
        filters.append(
            or_(
                and_(
                    SyncedActivity.source == "komoot", SyncedActivity.strava_activity_id.isnot(None)
                ),
                and_(SyncedActivity.source == "strava", SyncedActivity.komoot_tour_id.isnot(None)),
                and_(
                    SyncedActivity.source == "import", SyncedActivity.strava_activity_id.isnot(None)
                ),
            )
        )
    elif synced is False:
        filters.append(SyncedActivity.strava_activity_id.is_(None))
        filters.append(SyncedActivity.komoot_tour_id.is_(None))

    return filters


# ── List ──────────────────────────────────────────────────────────────────────


@router.get("")
async def get_activities(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    source: str | None = Query(None),
    sync_status: str | None = Query(None),
    sport_type: str | None = Query(None),
    search: str | None = Query(None),
    synced: bool | None = Query(None),
    date_from: str | None = Query(None, description="ISO datetime — filter by started_at ≥"),
    date_to: str | None = Query(None, description="ISO datetime — filter by started_at ≤"),
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Retrieve all activities for the current user (synced + imported)."""
    sub = (
        await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    ).scalar_one_or_none()
    tier = sub.tier if sub else "free"
    history_days = _ACTIVITY_HISTORY_DAYS.get(tier, 30)
    cutoff = datetime.now(UTC) - timedelta(days=history_days)

    filters = _build_activity_filters(
        user.id, cutoff, source, sync_status, sport_type, search, synced, date_from, date_to
    )
    stmt = (
        select(SyncedActivity)
        .where(*filters)
        .order_by(SyncedActivity.synced_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    activities = result.scalars().all()

    return {
        "data": [_serialize_activity(act) for act in activities],
        "skip": skip,
        "limit": limit,
        "count": len(activities),
    }


# ── IDs (for "select all matching" across pages) ──────────────────────────────


@router.get("/ids")
async def get_activity_ids(
    source: str | None = Query(None),
    sync_status: str | None = Query(None),
    sport_type: str | None = Query(None),
    search: str | None = Query(None),
    synced: bool | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Return all activity IDs matching the given filters (max 500, for bulk selection)."""
    sub = (
        await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    ).scalar_one_or_none()
    tier = sub.tier if sub else "free"
    history_days = _ACTIVITY_HISTORY_DAYS.get(tier, 30)
    cutoff = datetime.now(UTC) - timedelta(days=history_days)

    filters = _build_activity_filters(
        user.id, cutoff, source, sync_status, sport_type, search, synced, date_from, date_to
    )
    stmt = (
        select(SyncedActivity.id)
        .where(*filters)
        .order_by(SyncedActivity.synced_at.desc())
        .limit(500)
    )
    result = await db.execute(stmt)
    ids = [str(row[0]) for row in result.all()]
    return {"ids": ids, "count": len(ids)}


# ── Detail ────────────────────────────────────────────────────────────────────


@router.get("/{activity_id}")
async def get_activity_detail(
    activity_id: UUID,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Retrieve a single activity."""
    result = await db.execute(
        select(SyncedActivity).where(
            SyncedActivity.id == activity_id,
            SyncedActivity.user_id == user.id,
        )
    )
    activity = result.scalar_one_or_none()
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found.")
    return _serialize_activity(activity)


# ── Seed ──────────────────────────────────────────────────────────────────────


@router.post("/seed", status_code=status.HTTP_201_CREATED)
async def seed_test_activities(
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Create 12 synthetic test activities with full GPX tracks."""
    now = datetime.now(UTC)
    created = 0
    skipped = 0

    for template in _SEED_ACTIVITIES:
        started_at = now - timedelta(days=template["started_at_offset_days"])
        fake_tour_id = f"seed_{user.id}_{template['activity_name'].replace(' ', '_').lower()}"

        existing = (
            await db.execute(
                select(SyncedActivity).where(
                    SyncedActivity.user_id == user.id,
                    SyncedActivity.komoot_tour_id == fake_tour_id,
                )
            )
        ).scalar_one_or_none()

        if existing:
            skipped += 1
            continue

        gpx_bytes = _generate_gpx(
            name=template["activity_name"],
            sport_type=template["sport_type"],
            center_lat=template["center_lat"],
            center_lon=template["center_lon"],
            distance_m=template["distance_m"],
            elevation_base_m=template["elevation_base_m"],
            elevation_up_m=template["elevation_up_m"],
            duration_seconds=template["duration_seconds"],
            started_at=started_at,
        )

        db.add(
            SyncedActivity(
                user_id=user.id,
                source="import",
                komoot_tour_id=fake_tour_id,
                sync_direction=None,
                sync_status="completed",
                activity_name=template["activity_name"],
                sport_type=template["sport_type"],
                distance_m=template["distance_m"],
                elevation_up_m=template["elevation_up_m"],
                duration_seconds=template["duration_seconds"],
                started_at=started_at,
                synced_at=now - timedelta(days=template["started_at_offset_days"] - 1),
                gpx_data=gpx_bytes,
            )
        )
        created += 1

    await db.commit()
    return {"created": created, "skipped_existing": skipped, "total": len(_SEED_ACTIVITIES)}


# ── GPX Import ────────────────────────────────────────────────────────────────


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_gpx_activities(
    files: list[UploadFile] = File(...),
    names: str | None = Form(None),
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Parse one or more GPX files and create activity records.

    ``names`` is an optional JSON-encoded list of name overrides (one per file,
    in the same order as ``files``).  When provided, each non-empty entry
    replaces the name extracted from the GPX metadata.
    """
    created = []
    errors = []

    names_list: list[str] = []
    if names:
        try:
            parsed = json.loads(names)
            if isinstance(parsed, list):
                names_list = [str(n) for n in parsed]
        except (json.JSONDecodeError, ValueError):
            pass

    for i, upload in enumerate(files):
        if not upload.filename or not upload.filename.lower().endswith(".gpx"):
            errors.append({"file": upload.filename, "error": "Not a .gpx file"})
            continue

        raw = await upload.read()
        try:
            gpx = gpxpy.parse(io.BytesIO(raw))
        except Exception as exc:
            errors.append({"file": upload.filename, "error": f"Failed to parse GPX: {exc}"})
            continue

        # Name resolution priority:
        # 1. User-supplied override (from frontend editable field)
        # 2. <metadata><name> (gpx.name)
        # 3. First <trk><name> with a non-empty value
        # 4. Filename without extension
        parsed_name = (
            gpx.name
            or next((t.name for t in gpx.tracks if t.name and t.name.strip()), None)
            or upload.filename.removesuffix(".gpx")
            or "Imported activity"
        ).strip()
        override = names_list[i].strip() if i < len(names_list) else ""
        name = override if override else parsed_name
        started_at: datetime | None = None
        total_distance_m: float = 0.0
        total_elevation_up_m: float = 0.0
        total_duration_s: int = 0
        raw_sport_type: str | None = None

        for track in gpx.tracks:
            # Sport type: read from <type> inside <trk>; first non-empty value wins
            if not raw_sport_type and track.type:
                raw_sport_type = track.type.strip()

            # Time bounds — used for start time and duration fallback
            bounds = track.get_time_bounds()
            if not started_at and bounds.start_time:
                started_at = bounds.start_time.replace(tzinfo=UTC)

            # Distance: prefer moving_data (filters GPS drift); fall back to full
            # track length for route files that have no timestamps.
            md = track.get_moving_data()
            if md and (md.moving_distance or 0) > 0:
                total_distance_m += md.moving_distance
                # Duration from moving_time; if zero (e.g. very slow/stopped
                # for the whole track), fall back to elapsed time bounds.
                if (md.moving_time or 0) > 0:
                    total_duration_s += int(md.moving_time)
                elif bounds.start_time and bounds.end_time:
                    elapsed = (bounds.end_time - bounds.start_time).total_seconds()
                    total_duration_s += int(elapsed)
            else:
                # No moving data (no timestamps or all-stopped) — use raw distance
                track_len = track.length_3d() or track.length_2d() or 0
                total_distance_m += track_len
                # Duration from time bounds when available
                if bounds.start_time and bounds.end_time:
                    elapsed = (bounds.end_time - bounds.start_time).total_seconds()
                    total_duration_s += int(elapsed)

            ud = track.get_uphill_downhill()
            if ud:
                total_elevation_up_m += ud.uphill or 0

        # ── Dedup check ───────────────────────────────────────────────────────
        # For timestamped GPX: unique per (user, source=import, started_at).
        # For route GPX (no timestamps): unique per (user, source=import, name, no started_at).
        if started_at:
            dup = await db.execute(
                select(SyncedActivity.id).where(
                    SyncedActivity.user_id == user.id,
                    SyncedActivity.source == "import",
                    SyncedActivity.started_at == started_at,
                )
            )
        else:
            dup = await db.execute(
                select(SyncedActivity.id).where(
                    SyncedActivity.user_id == user.id,
                    SyncedActivity.source == "import",
                    SyncedActivity.activity_name == name,
                    SyncedActivity.started_at.is_(None),
                )
            )
        if dup.scalar_one_or_none() is not None:
            errors.append({"file": upload.filename, "error": "Already imported"})
            continue

        activity = SyncedActivity(
            user_id=user.id,
            source="import",
            sync_direction=None,
            sync_status="completed",
            activity_name=name,
            sport_type=_map_gpx_sport_type(raw_sport_type),
            distance_m=round(total_distance_m, 1) if total_distance_m else None,
            elevation_up_m=round(total_elevation_up_m, 1) if total_elevation_up_m else None,
            duration_seconds=total_duration_s or None,
            started_at=started_at,
            synced_at=datetime.now(UTC),
        )
        db.add(activity)
        await db.flush()  # populate activity.id before storage upload

        # Dual-write: try object storage first; fall back to DB column
        try:
            storage_key = await StorageService.put_gpx(
                user_id=str(user.id),
                activity_id=str(activity.id),
                data=raw,
            )
        except Exception as exc:
            _logger.warning("StorageService.put_gpx failed — falling back to DB: %s", exc)
            storage_key = None

        if storage_key:
            activity.gpx_storage_key = storage_key
            # gpx_data stays NULL when stored externally
        else:
            activity.gpx_data = raw

        created.append({"id": str(activity.id), "name": name})

    if created:
        await db.commit()

    return {"created": created, "errors": errors}


# ── Manual sync ───────────────────────────────────────────────────────────────


@router.post("/{activity_id}/sync")
async def trigger_activity_sync(
    activity_id: UUID,
    request: Request,
    destination: str | None = Body(None, embed=True, description="strava | komoot"),
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Trigger a manual re-sync for a specific activity.

    Pass ``destination`` in the JSON body to control the sync target:
    - ``"strava"`` — push to Strava (enqueues Komoot poll for komoot-sourced activities)
    - ``"komoot"`` — push to Komoot (not yet implemented)
    - omit / null — auto-detect based on activity state
    """
    result = await db.execute(
        select(SyncedActivity).where(
            SyncedActivity.id == activity_id,
            SyncedActivity.user_id == user.id,
        )
    )
    activity = result.scalar_one_or_none()
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found.")

    arq_pool = request.app.state.arq_pool

    # ── Sync to Komoot ────────────────────────────────────────────────────────
    if destination == "komoot":
        # Already on Komoot (real tour ID, not the seed_ sentinel)
        if activity.komoot_tour_id and not activity.komoot_tour_id.startswith("seed_"):
            return {"status": "ok", "message": "Activity is already on Komoot."}

        if not activity.gpx_data and not activity.gpx_storage_key:
            return {
                "status": "error",
                "message": (
                    "No GPX track available. Only activities with a GPS track"
                    " can be uploaded to Komoot."
                ),
            }

        if arq_pool:
            activity.sync_status = "pending"
            activity.conflict_reason = None
            await db.commit()
            await arq_pool.enqueue_job("sync_activity_to_komoot", str(activity.id), str(user.id))
            return {"status": "queued", "message": "Upload to Komoot queued — check back shortly."}

        return {"status": "error", "message": "Job queue unavailable."}

    # ── Sync to Strava (explicit or auto-detect) ──────────────────────────────
    if activity.strava_activity_id:
        return {"status": "ok", "message": "Activity is already on Strava."}

    has_gpx = (
        bool(activity.gpx_storage_key) or bool(activity.gpx_data) or bool(activity.komoot_tour_id)
    )
    if not has_gpx:
        return {
            "status": "error",
            "message": (
                "No GPX track available. Only activities with a GPS track can be synced to Strava."
            ),
        }

    if arq_pool:
        activity.sync_status = "pending"
        activity.conflict_reason = None
        await db.commit()
        await arq_pool.enqueue_job("sync_gpx_to_strava", str(activity.id), str(user.id))
        return {"status": "queued", "message": "Sync to Strava queued — check back shortly."}

    return {"status": "error", "message": "Job queue unavailable."}


# ── Delete single ─────────────────────────────────────────────────────────────


@router.delete("/{activity_id}", status_code=status.HTTP_200_OK)
async def delete_activity(
    activity_id: UUID,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Delete an activity from RoutePass and cascade to synced platforms.

    RoutePass is the hub — deleting here removes the activity from every
    connected platform it was pushed to (Strava, Komoot). Platform deletions
    that fail are reported but do not block the local record removal.
    """
    result = await db.execute(
        select(SyncedActivity).where(
            SyncedActivity.id == activity_id,
            SyncedActivity.user_id == user.id,
        )
    )
    activity = result.scalar_one_or_none()
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found.")

    deleted_from: list[str] = []
    failed: list[dict] = []

    # ── Delete from Strava ────────────────────────────────────────────────────
    if activity.strava_activity_id:
        try:
            # user.strava_token is eagerly loaded by get_current_user
            token = user.strava_token
            if token:
                app_res = await db.execute(
                    select(StravaApp).where(StravaApp.id == token.strava_app_id)
                )
                strava_app = app_res.scalar_one_or_none()
                if strava_app:
                    # Refresh token if near expiry
                    if token.expires_at <= datetime.now(UTC) + timedelta(minutes=5):
                        from app.services.strava import StravaClient as _SC

                        refresh_tok = security.decrypt(token.refresh_token)
                        refreshed = await _SC.refresh_access_token(refresh_tok)
                        token.access_token = security.encrypt(refreshed["access_token"])
                        token.refresh_token = security.encrypt(refreshed["refresh_token"])
                        token.expires_at = datetime.fromtimestamp(refreshed["expires_at"], tz=UTC)
                        token.last_refreshed_at = datetime.now(UTC)
                        await db.commit()
                        access_token = refreshed["access_token"]
                    else:
                        access_token = security.decrypt(token.access_token)

                    sub_res = await db.execute(
                        select(Subscription).where(Subscription.user_id == user.id)
                    )
                    sub = sub_res.scalar_one_or_none()
                    tier_str = sub.tier if sub else "free"

                    strava = StravaClient(access_token=access_token)
                    await rate_limit_guard.call(
                        strava_app.id,
                        tier_str,
                        strava.delete_activity,
                        activity.strava_activity_id,
                        user_id=str(user.id),
                    )
                    deleted_from.append("strava")
        except Exception as exc:
            _logger.warning(
                "delete_activity: Strava delete failed for %s: %s",
                activity.strava_activity_id,
                exc,
            )
            failed.append({"platform": "strava", "reason": str(exc)})

    # ── Delete from Komoot ────────────────────────────────────────────────────
    if activity.komoot_tour_id and not activity.komoot_tour_id.startswith("seed_"):
        try:
            komoot_email: str | None = None
            komoot_password: str | None = None
            komoot_uid: str | None = None
            conn_res = await db.execute(
                select(Connection).where(
                    Connection.user_id == user.id,
                    Connection.platform == "komoot",
                    Connection.status != "disconnected",
                )
            )
            conn = conn_res.scalar_one_or_none()
            if conn and conn.credentials_enc:
                creds = json.loads(security.decrypt(conn.credentials_enc))
                komoot_email = creds.get("email")
                komoot_password = creds.get("password")
                komoot_uid = creds.get("user_id")

            if komoot_email and komoot_password and komoot_uid:
                komoot = KomootClient(
                    email=komoot_email,
                    password=komoot_password,
                    user_id=komoot_uid,
                )
                await komoot.delete_tour(activity.komoot_tour_id)
                deleted_from.append("komoot")
        except Exception as exc:
            _logger.warning(
                "delete_activity: Komoot delete failed for tour %s: %s",
                activity.komoot_tour_id,
                exc,
            )
            failed.append({"platform": "komoot", "reason": str(exc)})

    # ── Remove local record ───────────────────────────────────────────────────
    # Only wipe the local row when every connected platform was cleaned up.
    # If any platform deletion failed the activity is still live there — keep
    # the row so it stays visible in the overview and the user can retry.
    if not failed:
        # Purge object storage blob before removing DB row (non-fatal).
        # Orphaned blobs that fail here are caught by a bucket lifecycle rule.
        if activity.gpx_storage_key:
            try:
                await StorageService.delete_gpx(activity.gpx_storage_key)
            except Exception as exc:
                _logger.warning(
                    "delete_activity: failed to purge storage key %s: %s",
                    activity.gpx_storage_key,
                    exc,
                )

        await db.delete(activity)
        await db.commit()

    return {"deleted_from": deleted_from, "failed": failed}


# ── Clear all seeded ──────────────────────────────────────────────────────────


@router.delete("/seed/clear", status_code=status.HTTP_200_OK)
async def clear_seed_activities(
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Delete all imported/seeded test activities for the current user."""
    result = await db.execute(
        select(SyncedActivity).where(
            SyncedActivity.user_id == user.id,
            SyncedActivity.source == "import",
        )
    )
    activities = result.scalars().all()
    count = len(activities)
    for act in activities:
        if act.gpx_storage_key:
            try:
                await StorageService.delete_gpx(act.gpx_storage_key)
            except Exception as exc:
                _logger.warning(
                    "clear_seed: failed to purge storage key %s: %s",
                    act.gpx_storage_key,
                    exc,
                )
        await db.delete(act)
    await db.commit()
    return {"deleted": count}


# ── GPX download ──────────────────────────────────────────────────────────────


@router.get("/{activity_id}/gpx")
async def download_activity_gpx(
    activity_id: UUID,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> Response:
    """Return the GPX track for an activity."""
    result = await db.execute(
        select(SyncedActivity).where(
            SyncedActivity.id == activity_id,
            SyncedActivity.user_id == user.id,
        )
    )
    activity = result.scalar_one_or_none()
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found.")

    # Resolution order:
    # 1. Object storage key (cloud / new imports)
    #    Cloud (STORAGE_BACKEND != "db"): redirect to presigned URL (TTL 5 min).
    #    Bytes never flow through the API server, reducing bandwidth costs.
    # 2. DB column (self-hosted / legacy rows)
    if activity.gpx_storage_key:
        try:
            if settings.STORAGE_BACKEND != "db":
                url = await StorageService.generate_presigned_url(activity.gpx_storage_key)
                return RedirectResponse(url, status_code=302)
            # STORAGE_BACKEND=db should never produce a storage key, but handle defensively
            gpx_bytes = await StorageService.get_gpx(activity.gpx_storage_key)
            return Response(
                content=gpx_bytes,
                media_type="application/gpx+xml",
                headers={
                    "Content-Disposition": f'attachment; filename="activity-{activity_id}.gpx"'
                },
            )
        except Exception as exc:
            _logger.error(
                "StorageService failed for activity %s: %s — falling back",
                activity_id,
                exc,
            )
            # Fall through to DB column if storage fetch fails

    if activity.gpx_data:
        return Response(
            content=activity.gpx_data,
            media_type="application/gpx+xml",
            headers={"Content-Disposition": f'attachment; filename="activity-{activity_id}.gpx"'},
        )

    # Strava-sourced activities: fetch GPS streams on demand and convert to GPX
    if activity.source == "strava" and activity.strava_activity_id:
        token = user.strava_token
        if not token:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Strava must be connected to download GPX for Strava activities.",
            )
        app_res = await db.execute(select(StravaApp).where(StravaApp.id == token.strava_app_id))
        strava_app = app_res.scalar_one_or_none()
        if not strava_app:
            raise HTTPException(status.HTTP_409_CONFLICT, "Strava app configuration not found.")

        if token.expires_at <= datetime.now(UTC) + timedelta(minutes=5):
            refresh_tok = security.decrypt(token.refresh_token)
            refreshed = await StravaClient.refresh_access_token(refresh_tok)
            token.access_token = security.encrypt(refreshed["access_token"])
            token.refresh_token = security.encrypt(refreshed["refresh_token"])
            token.expires_at = datetime.fromtimestamp(refreshed["expires_at"], tz=UTC)
            token.last_refreshed_at = datetime.now(UTC)
            await db.commit()
            access_token = refreshed["access_token"]
        else:
            access_token = security.decrypt(token.access_token)

        sub_res = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
        sub = sub_res.scalar_one_or_none()
        tier_str = sub.tier if sub else "free"

        strava = StravaClient(access_token=access_token)
        streams = await rate_limit_guard.call(
            strava_app.id,
            tier_str,
            strava.get_activity_streams,
            activity.strava_activity_id,
            user_id=str(user.id),
        )

        if not streams or not streams.get("latlng"):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "No GPS data available for this Strava activity.",
            )

        gpx_bytes = _streams_to_gpx(
            activity_name=activity.activity_name or "Strava Activity",
            sport_type=activity.sport_type or "",
            started_at=activity.started_at,
            streams=streams,
        )
        return Response(
            content=gpx_bytes,
            media_type="application/gpx+xml",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="strava-{activity.strava_activity_id}.gpx"'
                )
            },
        )

    # Real Komoot activities: fetch live
    if not activity.komoot_tour_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No GPX data available for this activity.")

    import json as _json

    conn_res = await db.execute(
        select(Connection).where(
            Connection.user_id == user.id,
            Connection.platform == "komoot",
            Connection.status != "disconnected",
        )
    )
    komoot_conn = conn_res.scalar_one_or_none()
    if not komoot_conn or not komoot_conn.credentials_enc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Komoot must be connected before GPX can be downloaded.",
        )
    creds = _json.loads(security.decrypt(komoot_conn.credentials_enc))
    komoot_email = creds.get("email")
    komoot_password = creds.get("password")
    komoot_uid = creds.get("user_id")
    if not komoot_email or not komoot_password or not komoot_uid:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Komoot credentials are incomplete. Reconnect your Komoot account.",
        )
    gpx_bytes = await KomootClient(
        email=komoot_email,
        password=komoot_password,
        user_id=komoot_uid,
    ).download_gpx(activity.komoot_tour_id)

    return Response(
        content=gpx_bytes,
        media_type="application/gpx+xml",
        headers={
            "Content-Disposition": (
                f'attachment; filename="komoot-tour-{activity.komoot_tour_id}.gpx"'
            )
        },
    )


# ── Track metrics (docs/GPX_ANALYSIS_PLAN.md) ───────────────────────────────────


async def _load_owned_activity(activity_id: UUID, user: User, db: AsyncSession) -> SyncedActivity:
    activity = (
        await db.execute(
            select(SyncedActivity).where(
                SyncedActivity.id == activity_id,
                SyncedActivity.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found.")
    return activity


@router.get("/{activity_id}/metrics")
async def get_activity_metrics(
    activity_id: UUID,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Computed summary metrics + zones + splits for an activity.

    `computed` is false when the backfill job hasn't reached this activity yet
    (or it has no usable track) — the client shows a "computing…" state.
    """
    a = await _load_owned_activity(activity_id, user, db)
    return {
        "activity_id": str(a.id),
        "computed": a.metrics_computed_at is not None,
        "computed_at": a.metrics_computed_at.isoformat() if a.metrics_computed_at else None,
        "available": a.metrics_available or [],
        "summary": {
            "distance_m": a.distance_m,
            "elapsed_time_s": a.duration_seconds,
            "moving_time_s": a.moving_time_s,
            "elevation_gain_m": a.elevation_up_m,
            "elevation_loss_m": a.elevation_down_m,
            "avg_speed_ms": a.avg_speed_ms,
            "avg_hr": a.avg_hr,
            "max_hr": a.max_hr,
            "avg_power": a.avg_power,
            "max_power": a.max_power,
            "normalized_power": a.normalized_power,
            "tss": a.tss,
            "avg_cadence": a.avg_cadence,
            "calories": a.calories,
        },
        "detail": a.metrics_detail or {},
    }


@router.get("/{activity_id}/track")
async def get_activity_track(
    activity_id: UUID,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """LTTB-downsampled per-point series for charts (elevation/HR/power/…)."""
    import gzip

    a = await _load_owned_activity(activity_id, user, db)
    if not a.track_gz:
        return {
            "activity_id": str(a.id),
            "computed": a.metrics_computed_at is not None,
            "points": [],
        }
    try:
        points = json.loads(gzip.decompress(a.track_gz).decode())
    except Exception:
        points = []
    return {"activity_id": str(a.id), "computed": True, "points": points}

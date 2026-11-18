"""Fill an empty database with ~2 years of synthetic activities (for UI development).

ROUTEPASS_DATA_DIR=./data python -m scripts.seed_demo
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

import numpy as np

from routepass.analysis import track as trk
from routepass.db import init_db, session_scope
from routepass.engine import ingest
from routepass.models import ProviderActivity
from routepass.providers.gpx import encode_polyline, simplify

SPORTS = [
    ("Ride", 0.45, 25, 90),
    ("Run", 0.3, 5, 21),
    ("Hike", 0.12, 8, 25),
    ("GravelRide", 0.08, 30, 110),
    ("EBikeRide", 0.05, 15, 50),
]
SPEED = {"Ride": 7.5, "GravelRide": 6.5, "EBikeRide": 6.8, "Run": 3.1, "Hike": 1.3}
HOMES = [(47.3769, 8.5417), (41.3874, 2.1686)]


def synth_track(sport: str, km: float, rng: random.Random) -> trk.NormalizedTrack:
    n = int(km * 1000 / SPEED[sport] / 2)  # one point every ~2 s
    t = np.arange(n) * 2.0
    lat0, lon0 = rng.choice(HOMES)
    heading = rng.uniform(0, 2 * math.pi)
    r = km / (2 * math.pi) / 111
    ang = heading + np.linspace(0, 2 * math.pi, n) + 0.15 * np.sin(np.linspace(0, 9, n))
    lat = lat0 + r * (np.sin(ang) - math.sin(heading))
    lon = lon0 + r * 1.4 * (np.cos(ang) - math.cos(heading))
    hills = rng.uniform(40, 400)
    ele = (
        400 + hills * np.sin(np.linspace(0, rng.uniform(2, 6), n)) ** 2 + np.cumsum(np.random.randn(n)) * 0.3
    )
    hr = 120 + 30 * np.sin(np.linspace(0, 3, n)) ** 2 + np.random.randn(n) * 3 + np.linspace(0, 8, n)
    power = None
    if sport in ("Ride", "GravelRide") and rng.random() < 0.7:
        power = np.clip(190 + 60 * np.sin(np.linspace(0, 20, n)) + np.random.randn(n) * 40, 0, None)
    speed = np.full(n, SPEED[sport]) * (1 + 0.15 * np.sin(np.linspace(0, 15, n)))
    return trk.NormalizedTrack(
        time_s=t,
        lat=lat,
        lon=lon,
        elevation_m=ele,
        distance_m=trk.haversine_cumulative(lat, lon),
        hr=hr,
        power=power,
        speed_ms=speed,
        cadence=np.full(n, 85.0) if power is not None else None,
    )


def main() -> None:
    init_db()
    rng = random.Random(7)
    np.random.seed(7)
    start = datetime(2024, 11, 1, 7)
    day = start
    sid = 10_000
    kid = 50_000
    with session_scope() as db:
        while day < datetime(2026, 11, 17):
            if rng.random() < 0.5:
                sport, _, lo, hi = rng.choices(SPORTS, weights=[s[1] for s in SPORTS])[0]
                km = rng.uniform(lo, hi) * (1.4 if day.weekday() >= 5 else 1)
                when = day.replace(
                    hour=rng.choice([6, 7, 12, 17, 18]) if day.weekday() < 5 else rng.choice([8, 9, 10])
                )
                track = synth_track(sport, km, rng)
                names = {
                    "Ride": ["Morning Ride", "Lake loop", "Hill repeats", "Evening Ride"],
                    "Run": ["Easy run", "Intervals", "Long run"],
                    "Hike": ["Uetliberg hike", "Ridge walk"],
                    "GravelRide": ["Gravel adventure"],
                    "EBikeRide": ["Commute"],
                }
                name = rng.choice(names[sport])
                dist = float(track.distance_m[-1])
                pts = list(zip(track.lat.tolist(), track.lon.tolist(), strict=True))
                on_strava = rng.random() < 0.85
                on_komoot = (
                    sport in ("Ride", "GravelRide", "Hike", "EBikeRide")
                    and rng.random() < 0.6
                    or not on_strava
                )
                recs = []
                if on_strava:
                    sid += 1
                    recs.append(
                        ProviderActivity(
                            provider="strava",
                            external_id=str(sid),
                            name=name,
                            sport=sport,
                            start_time=when,
                            distance_m=dist,
                            moving_time_s=float(track.time_s[-1]),
                            elevation_gain_m=None,
                            raw={
                                "id": sid,
                                "elapsed_time": float(track.time_s[-1]) * 1.1,
                                "average_heartrate": float(np.mean(track.hr)),
                                "summary_polyline": encode_polyline(simplify(pts, 200)),
                                "start_date_local": when.isoformat() + "Z",
                            },
                            track_status="done",
                            first_seen=when,
                            last_seen=when,
                        )
                    )
                if on_komoot:
                    kid += 1
                    ksport = {
                        "Ride": "touringbicycle",
                        "GravelRide": "gravelbike",
                        "Hike": "hike",
                        "EBikeRide": "e_touringbicycle",
                        "Run": "jogging",
                    }[sport]
                    recs.append(
                        ProviderActivity(
                            provider="komoot",
                            external_id=str(kid),
                            name=name if rng.random() < 0.7 else f"{name} (Komoot)",
                            sport=ksport,
                            start_time=when + timedelta(seconds=rng.randint(-90, 90)),
                            distance_m=dist * rng.uniform(0.97, 1.03),
                            moving_time_s=float(track.time_s[-1]),
                            elevation_gain_m=None,
                            raw={"id": kid},
                            track_status="done",
                            created_by_sync=on_strava and rng.random() < 0.3,
                            first_seen=when,
                            last_seen=when,
                        )
                    )
                db.add_all(recs)
                db.flush()
                ingest.match_unlinked(db)
                act_id = recs[0].activity_id
                from routepass.models import Activity

                ingest.store_track(db, db.get(Activity, act_id), recs[0].provider, track)
            day += timedelta(days=1)
    print("seeded")


if __name__ == "__main__":
    main()

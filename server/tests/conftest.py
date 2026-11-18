from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import respx
from fastapi.testclient import TestClient

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ.setdefault("ROUTEPASS_SECRET_KEY", "x" * 43 + "=")
os.environ["ROUTEPASS_SCHEDULER_ENABLED"] = "false"
os.environ["ROUTEPASS_API_TOKEN"] = "test-token"
os.environ["ROUTEPASS_STRAVA_CLIENT_ID"] = "1"
os.environ["ROUTEPASS_STRAVA_CLIENT_SECRET"] = "s"

from cryptography.fernet import Fernet  # noqa: E402

os.environ["ROUTEPASS_SECRET_KEY"] = Fernet.generate_key().decode()

from routepass import store  # noqa: E402
from routepass.config import get_settings  # noqa: E402
from routepass.db import init_db, session_scope  # noqa: E402
from routepass.engine.clients import KOMOOT_CREDENTIALS, STRAVA_TOKENS  # noqa: E402
from routepass.providers import strava as strava_mod  # noqa: E402

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("ROUTEPASS_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    init_db(f"sqlite:///{tmp_path / 'test.db'}")
    strava_mod.RATE.__init__()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from routepass.main import create_app

    app = create_app(start_scheduler=False)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def connected() -> None:
    with session_scope() as db:
        store.set_secret(
            db,
            STRAVA_TOKENS,
            {
                "access_token": "a",
                "refresh_token": "r",
                "expires_at": int(datetime.now(UTC).timestamp()) + 9999,
            },
        )
        store.set_secret(db, KOMOOT_CREDENTIALS, {"email": "e@x", "password": "p", "user_id": "42"})


def strava_activity(aid: int, start: datetime, km: float = 30, **extra) -> dict:
    return {
        "id": aid,
        "name": f"Strava {aid}",
        "sport_type": "Ride",
        "start_date": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start_date_local": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "distance": km * 1000,
        "moving_time": 3600,
        "elapsed_time": 4000,
        "total_elevation_gain": 300,
        "average_heartrate": 140,
        "map": {"summary_polyline": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
        **extra,
    }


def komoot_tour(tid: int, start: datetime, km: float = 30, sport: str = "touringbicycle") -> dict:
    return {
        "id": tid,
        "name": f"Komoot {tid}",
        "sport": sport,
        "date": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "distance": km * 1000,
        "duration": 4000,
        "time_in_motion": 3600,
        "elevation_up": 310,
        "elevation_down": 300,
        "status": "private",
        "start_point": {"lat": 47.0, "lng": 8.0, "alt": 400},
    }


def coords(n: int = 120) -> dict:
    return {"items": [{"lat": 47 + i * 0.001, "lng": 8.0, "alt": 400 + i, "t": i * 10_000} for i in range(n)]}


def streams(n: int = 400) -> list:
    return [
        {"type": "time", "data": list(range(n))},
        {"type": "latlng", "data": [[47 + i * 0.0001, 8.0] for i in range(n)]},
        {"type": "altitude", "data": [400 + (i % 50) for i in range(n)]},
        {"type": "heartrate", "data": [130 + i % 20 for i in range(n)]},
        {"type": "distance", "data": [i * 11.1 for i in range(n)]},
    ]


@pytest.fixture
def mock_apis():
    with respx.mock(assert_all_called=False) as router:
        yield router


T0 = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)


def days(n: int) -> timedelta:
    return timedelta(days=n)

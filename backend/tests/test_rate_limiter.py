from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.core import rate_limit
from app.core.rate_limit import RateLimiter, RateLimitError, current_user_id

_LIMITS = {
    "overall_15": 90,
    "overall_daily": 900,
    "read_15": 180,
    "read_daily": 1800,
    "free_reserve_daily": 800,
}


class _FakePipe:
    def __init__(self, store: dict) -> None:
        self._store = store
        self._ops: list = []

    def incr(self, key: str):
        self._ops.append(("incr", key))
        return self

    def expire(self, key: str, ttl: int):
        return self

    async def execute(self):
        for _, key in [o for o in self._ops if o[0] == "incr"]:
            self._store[key] = str(int(self._store.get(key, "0")) + 1)
        self._ops = []


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ex=None):
        self.store[key] = str(value)

    async def incr(self, key: str):
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])

    async def expire(self, key: str, ttl: int):
        return None

    def pipeline(self):
        return _FakePipe(self.store)


def _limiter() -> tuple[RateLimiter, _FakeRedis]:
    lim = RateLimiter()
    fake = _FakeRedis()
    lim._redis = fake

    async def fixed(_app_id):
        return dict(_LIMITS)

    lim._effective_limits = fixed  # type: ignore[assignment]
    return lim, fake


def _read_fn():
    async def get_activities(*a, **k):
        return "read-ok"

    return get_activities


def _write_fn():
    async def upload_gpx(*a, **k):
        return "write-ok"

    return upload_gpx


@pytest.mark.asyncio
async def test_read_call_increments_read_overall_and_user():
    lim, fake = _limiter()
    token = current_user_id.set("u1")
    try:
        res = await lim.call(1, "pro", _read_fn())
    finally:
        current_user_id.reset(token)
    assert res == "read-ok"
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    assert fake.store[f"strava:1:rl:daily:{date}"] == "1"
    assert fake.store[f"strava:1:rl:readdaily:{date}"] == "1"
    assert fake.store[f"usage:strava:user:u1:read:{date}"] == "1"
    assert fake.store[f"usage:strava:user:u1:overall:{date}"] == "1"


@pytest.mark.asyncio
async def test_write_call_only_touches_overall_not_read():
    lim, fake = _limiter()
    res = await lim.call(1, "pro", _write_fn(), user_id="u2")
    assert res == "write-ok"
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    assert fake.store[f"strava:1:rl:daily:{date}"] == "1"
    assert f"strava:1:rl:readdaily:{date}" not in fake.store
    assert fake.store[f"usage:strava:user:u2:overall:{date}"] == "1"
    assert f"usage:strava:user:u2:read:{date}" not in fake.store


@pytest.mark.asyncio
async def test_overall_daily_limit_blocks():
    lim, fake = _limiter()
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    fake.store[f"strava:1:rl:daily:{date}"] = "900"  # at effective limit
    with pytest.raises(RateLimitError):
        await lim.call(1, "pro", _read_fn())


@pytest.mark.asyncio
async def test_free_reserve_is_cloud_only():
    lim, fake = _limiter()
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    fake.store[f"strava:1:rl:daily:{date}"] = "801"  # above free reserve (800)

    with patch("app.core.rate_limit.settings.DEPLOYMENT_MODE", "cloud"):
        with pytest.raises(RateLimitError):
            await lim.call(1, "free", _read_fn())

    # Self-hosted: no free/paid split → free caller is allowed (still under 900).
    fake.store[f"strava:1:rl:daily:{date}"] = "801"
    with patch("app.core.rate_limit.settings.DEPLOYMENT_MODE", "selfhosted"):
        assert await lim.call(1, "free", _read_fn()) == "read-ok"


def test_backwards_compatible_names():
    assert rate_limit.WINDOW_15MIN_LIMIT == 90
    assert rate_limit.DAILY_LIMIT == 950
    assert rate_limit.RateLimitGuard is RateLimiter


# ── Live-limit self-correction (RateLimiter._maybe_sync_live_limits) ────────────


async def _make_test_session_factory():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.base import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _fn_with_headers(headers: dict | None):
    class _FakeClient:
        last_rate_limit_headers = headers

    async def fn():
        return "ok"

    fn.__self__ = _FakeClient()
    return fn


@pytest.mark.asyncio
async def test_maybe_sync_live_limits_corrects_drifted_app():
    from app.db.models.user import StravaApp

    engine, session_factory = await _make_test_session_factory()
    async with session_factory() as s:
        s.add(
            StravaApp(
                id=1,
                client_id="c",
                client_secret=b"enc",
                display_name="A",
                is_active=True,
                overall_limit_15min=100,
                overall_limit_daily=1000,
                read_limit_15min=100,
                read_limit_daily=1000,
            )
        )
        await s.commit()

    lim, fake = _limiter()
    fn = _fn_with_headers({"X-RateLimit-Limit": "400,4000", "X-ReadRateLimit-Limit": "200,2000"})

    with patch("app.db.session.AsyncSessionLocal", session_factory):
        await lim._maybe_sync_live_limits(1, fn)

    async with session_factory() as s:
        from sqlalchemy import select

        app = (await s.execute(select(StravaApp).where(StravaApp.id == 1))).scalar_one()
    assert app.overall_limit_15min == 400
    assert app.overall_limit_daily == 4000
    assert app.read_limit_15min == 200
    assert app.read_limit_daily == 2000

    # Cache invalidated so the corrected numbers apply on the next call.
    assert fake.store.get("routepass:limits:strava:1") is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_maybe_sync_live_limits_noop_without_headers():
    lim, fake = _limiter()
    fn = _fn_with_headers(None)

    with patch("app.db.session.AsyncSessionLocal") as mock_session:
        await lim._maybe_sync_live_limits(1, fn)
        mock_session.assert_not_called()

    assert "routepass:limits:strava:1:live_sync" not in fake.store


@pytest.mark.asyncio
async def test_maybe_sync_live_limits_throttled_within_ttl():
    from app.db.models.user import StravaApp

    engine, session_factory = await _make_test_session_factory()
    async with session_factory() as s:
        s.add(
            StravaApp(
                id=1,
                client_id="c",
                client_secret=b"enc",
                display_name="A",
                is_active=True,
                overall_limit_15min=100,
                overall_limit_daily=1000,
            )
        )
        await s.commit()

    lim, fake = _limiter()
    fn = _fn_with_headers({"X-RateLimit-Limit": "400,4000"})

    with patch("app.db.session.AsyncSessionLocal", session_factory):
        await lim._maybe_sync_live_limits(1, fn)  # first call syncs

        # Reset the app back to drifted values to prove the second call is a no-op.
        async with session_factory() as s:
            from sqlalchemy import select

            app = (await s.execute(select(StravaApp).where(StravaApp.id == 1))).scalar_one()
            app.overall_limit_15min = 999
            await s.commit()

        await lim._maybe_sync_live_limits(1, fn)  # throttled — must not touch DB

        async with session_factory() as s:
            from sqlalchemy import select

            app = (await s.execute(select(StravaApp).where(StravaApp.id == 1))).scalar_one()
    assert app.overall_limit_15min == 999  # untouched by the throttled second call
    await engine.dispose()

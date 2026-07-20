from __future__ import annotations

import pytest

from app.core.rate_limit import CircuitOpenError, DestinationRateLimiter, RateLimitError


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

    async def delete(self, key: str):
        self.store.pop(key, None)


def _limiter(window_seconds=None, window_limit=None) -> tuple[DestinationRateLimiter, _FakeRedis]:
    lim = DestinationRateLimiter()
    fake = _FakeRedis()
    lim._redis = fake

    async def fixed(_platform):
        return window_seconds, window_limit

    lim._window_for = fixed  # type: ignore[assignment]
    return lim, fake


@pytest.mark.asyncio
async def test_passthrough_when_no_window_configured():
    lim, _fake = _limiter(None, None)

    async def ok():
        return "ok"

    assert await lim.call("komoot", "conn1", ok) == "ok"


@pytest.mark.asyncio
async def test_window_limit_enforced_per_connection():
    lim, fake = _limiter(60, 2)

    async def ok():
        return "ok"

    assert await lim.call("runalyze", "connA", ok) == "ok"
    assert await lim.call("runalyze", "connA", ok) == "ok"
    with pytest.raises(RateLimitError):
        await lim.call("runalyze", "connA", ok)

    # A different connection has its own independent budget.
    assert await lim.call("runalyze", "connB", ok) == "ok"


@pytest.mark.asyncio
async def test_circuit_breaker_trips_after_threshold_and_resets_on_success():
    lim, fake = _limiter(None, None)

    async def failing():
        raise ValueError("boom")

    for _ in range(4):
        with pytest.raises(ValueError):
            await lim.call("intervals_icu", "connX", failing)

    # 5th consecutive failure trips the breaker.
    with pytest.raises(ValueError):
        await lim.call("intervals_icu", "connX", failing)

    # Further calls short-circuit without invoking fn.
    async def should_not_run():
        raise AssertionError("must not be called while circuit is open")

    with pytest.raises(CircuitOpenError):
        await lim.call("intervals_icu", "connX", should_not_run)


@pytest.mark.asyncio
async def test_success_resets_failure_count():
    lim, fake = _limiter(None, None)

    async def failing():
        raise ValueError("boom")

    async def ok():
        return "ok"

    for _ in range(3):
        with pytest.raises(ValueError):
            await lim.call("intervals_icu", "connY", failing)

    assert await lim.call("intervals_icu", "connY", ok) == "ok"
    assert fake.store.get("cb:intervals_icu:connY:fails") is None

    # Fresh failure count — 4 more failures should NOT trip the breaker (needs 5
    # consecutive), so the connection is still usable afterwards.
    for _ in range(4):
        with pytest.raises(ValueError):
            await lim.call("intervals_icu", "connY", failing)
    assert await lim.call("intervals_icu", "connY", ok) == "ok"


@pytest.mark.asyncio
async def test_records_per_user_usage_on_success():
    lim, fake = _limiter(None, None)

    async def ok():
        return "ok"

    await lim.call("runalyze", "connZ", ok, user_id="user-123")
    matching = [k for k in fake.store if k.startswith("usage:runalyze:user:user-123:overall:")]
    assert len(matching) == 1
    assert fake.store[matching[0]] == "1"

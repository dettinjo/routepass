from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

UTC = UTC

TIER_PRIORITY = {"free": 5, "pro": 10, "business": 15}
WINDOW_15MIN_LIMIT = 90  # leave 10 headroom below Strava's 100
DAILY_LIMIT = 950  # leave 50 headroom below Strava's 1000


class RateLimitError(Exception):
    """Raised when a Strava API call would exceed the configured rate limits."""


class RateLimitGuard:
    """Wraps ALL outbound Strava API calls.

    Tracks per-app 15-minute and daily usage budgets in Redis using atomic
    INCR + EXPIRE operations.  Free-tier calls are suspended when the shared
    daily usage exceeds 800, reserving headroom for paid tiers.
    """

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    async def get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    async def daily_count(self, app_id: int) -> int:
        """Return the current daily Strava API call count for *app_id*."""
        r = await self.get_redis()
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        return int(await r.get(f"strava:{app_id}:rl:daily:{date_key}") or 0)

    async def pick_least_loaded_app(self, app_ids: list[int]) -> int:
        """Return the app_id with the most remaining daily headroom.

        Result is cached in Redis for 60 s to avoid per-request Redis round-trips.
        Returns the first app_id when all are equally loaded or the list has one entry.
        """
        if not app_ids:
            raise ValueError("No active Strava apps available")
        if len(app_ids) == 1:
            return app_ids[0]

        r = await self.get_redis()
        cache_key = "routepass:least_loaded_app"
        cached = await r.get(cache_key)
        if cached:
            return int(cached)

        best_id = app_ids[0]
        best_remaining = -1
        for app_id in app_ids:
            count = await self.daily_count(app_id)
            remaining = DAILY_LIMIT - count
            if remaining > best_remaining:
                best_remaining = remaining
                best_id = app_id

        await r.set(cache_key, best_id, ex=60)
        return best_id

    async def call(self, app_id: int, tier: str, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute *fn*(*args*, **kwargs*) guarded by Strava rate limits.

        Raises RateLimitError if the 15-min window OR daily budget is exhausted,
        or if a free-tier caller attempts a call when daily usage > 800.
        """
        r = await self.get_redis()
        now = datetime.now(UTC)
        window = int(now.timestamp()) // 900  # 15-min window index
        date_key = now.strftime("%Y-%m-%d")

        key_15 = f"strava:{app_id}:rl:15min:{window}"
        key_daily = f"strava:{app_id}:rl:daily:{date_key}"

        count_15 = int(await r.get(key_15) or 0)
        count_daily = int(await r.get(key_daily) or 0)

        # Free tier suspended when daily usage > 800
        if tier == "free" and count_daily > 800:
            raise RateLimitError("Daily budget reserved for paid tiers")

        if count_15 >= WINDOW_15MIN_LIMIT or count_daily >= DAILY_LIMIT:
            raise RateLimitError(
                f"Strava rate limit reached (15min={count_15}, daily={count_daily})"
            )

        # Increment counters atomically
        pipe = r.pipeline()
        pipe.incr(key_15)
        pipe.expire(key_15, 900)
        pipe.incr(key_daily)
        pipe.expire(key_daily, 86400)
        await pipe.execute()

        return await fn(*args, **kwargs)


rate_limit_guard = RateLimitGuard()

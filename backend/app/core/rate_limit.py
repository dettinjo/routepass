from __future__ import annotations

import json
import logging
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

UTC = UTC
logger = logging.getLogger(__name__)

TIER_PRIORITY = {"free": 5, "pro": 10, "business": 15}

# Fallback limits (used only if the registry can't be loaded). These match the
# historical hardcoded guard so behaviour degrades gracefully.
FALLBACK_OVERALL_15MIN = 90
FALLBACK_OVERALL_DAILY = 950
FALLBACK_HEADROOM_PCT = 10
FALLBACK_FREE_RESERVE_PCT = 20

# Backwards-compatible names (referenced by older code/tests).
WINDOW_15MIN_LIMIT = FALLBACK_OVERALL_15MIN
DAILY_LIMIT = FALLBACK_OVERALL_DAILY

# Strava client methods that are writes/uploads → count toward the *overall* bucket
# only. Everything else is a read → counts toward *both* read and overall buckets.
_STRAVA_WRITE_METHODS = {"upload_gpx", "update_activity", "delete_activity"}

_LIMITS_CACHE_TTL = 60  # seconds; admin edits take effect within this window

# Attributes the current request/job to a user so the limiter can record per-user
# usage without threading user_id through every call site. Set at job/request entry.
current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


class RateLimitError(Exception):
    """Raised when a Strava API call would exceed the configured rate limits."""


class RateLimiter:
    """Guards ALL outbound Strava API calls, driven by the admin-editable registry.

    Tracks per-app 15-minute and daily usage for the **overall** and **read** buckets
    in Redis, and per-user usage for admin insight. Limits come from the provider
    registry (strava_apps + provider_policy), cached in Redis. Free-tier economic
    suspension is skipped on self-hosted instances (rate safety still applies).
    """

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    async def get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    # ── Limit resolution (registry-driven, cached) ──────────────────────────────

    async def _effective_limits(self, app_id: int) -> dict[str, int]:
        """Resolve effective Strava limits for an app from the registry, cached 60s.

        Effective = configured limit × (100 − headroom_pct)/100. The free-tier
        reserve threshold is configured_overall_daily × (100 − free_reserve_pct)/100.
        """
        r = await self.get_redis()
        cache_key = f"routepass:limits:strava:{app_id}"
        cached = await r.get(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except (ValueError, TypeError):
                pass

        limits = await self._load_limits_from_db(app_id)
        await r.set(cache_key, json.dumps(limits), ex=_LIMITS_CACHE_TTL)
        return limits

    async def _load_limits_from_db(self, app_id: int) -> dict[str, int]:
        try:
            from sqlalchemy import select

            from app.db.models.governance import ProviderPolicy
            from app.db.models.user import StravaApp
            from app.db.session import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                app = (
                    await db.execute(select(StravaApp).where(StravaApp.id == app_id))
                ).scalar_one_or_none()
                policy = (
                    await db.execute(
                        select(ProviderPolicy).where(ProviderPolicy.platform == "strava")
                    )
                ).scalar_one_or_none()

            headroom = policy.headroom_pct if policy else FALLBACK_HEADROOM_PCT
            free_reserve = policy.free_reserve_pct if policy else FALLBACK_FREE_RESERVE_PCT
            overall_15 = app.overall_limit_15min if app else 100
            overall_daily = app.overall_limit_daily if app else 1000
            read_15 = app.read_limit_15min if app else 200
            read_daily = app.read_limit_daily if app else 2000

            keep = (100 - headroom) / 100
            return {
                "overall_15": int(overall_15 * keep),
                "overall_daily": int(overall_daily * keep),
                "read_15": int(read_15 * keep),
                "read_daily": int(read_daily * keep),
                "free_reserve_daily": int(overall_daily * (100 - free_reserve) / 100),
            }
        except Exception as exc:
            logger.warning("Rate limiter: registry load failed for app %s: %s", app_id, exc)
            return {
                "overall_15": FALLBACK_OVERALL_15MIN,
                "overall_daily": FALLBACK_OVERALL_DAILY,
                "read_15": FALLBACK_OVERALL_15MIN * 2,
                "read_daily": FALLBACK_OVERALL_DAILY * 2,
                "free_reserve_daily": 800,
            }

    # ── App-pool helpers ────────────────────────────────────────────────────────

    async def daily_count(self, app_id: int) -> int:
        """Current daily *overall* Strava call count for app_id."""
        r = await self.get_redis()
        date_key = datetime.now(UTC).strftime("%Y-%m-%d")
        return int(await r.get(f"strava:{app_id}:rl:daily:{date_key}") or 0)

    async def pick_least_loaded_app(self, app_ids: list[int]) -> int:
        """Return the app_id with the most remaining daily headroom (cached 60s)."""
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
            limits = await self._effective_limits(app_id)
            remaining = limits["overall_daily"] - count
            if remaining > best_remaining:
                best_remaining = remaining
                best_id = app_id

        await r.set(cache_key, best_id, ex=60)
        return best_id

    # ── The guarded call ────────────────────────────────────────────────────────

    async def call(
        self,
        app_id: int,
        tier: str,
        fn: Callable,
        *args: Any,
        user_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute fn(*args, **kwargs) guarded by Strava rate limits.

        Raises RateLimitError if the overall (or, for reads, the read) 15-min or daily
        budget is exhausted, or — cloud only — if a free-tier caller would consume
        capacity reserved for paying tiers.
        """
        r = await self.get_redis()
        now = datetime.now(UTC)
        window = int(now.timestamp()) // 900
        date_key = now.strftime("%Y-%m-%d")

        is_read = getattr(fn, "__name__", "") not in _STRAVA_WRITE_METHODS
        limits = await self._effective_limits(app_id)

        key_o15 = f"strava:{app_id}:rl:15min:{window}"
        key_odaily = f"strava:{app_id}:rl:daily:{date_key}"
        key_r15 = f"strava:{app_id}:rl:read15:{window}"
        key_rdaily = f"strava:{app_id}:rl:readdaily:{date_key}"

        count_o15 = int(await r.get(key_o15) or 0)
        count_odaily = int(await r.get(key_odaily) or 0)

        # Economic free-tier reservation (cloud only; self-hosted has no free/paid split).
        if (
            settings.DEPLOYMENT_MODE != "selfhosted"
            and tier == "free"
            and count_odaily > limits["free_reserve_daily"]
        ):
            raise RateLimitError("Daily budget reserved for paid tiers")

        if count_o15 >= limits["overall_15"] or count_odaily >= limits["overall_daily"]:
            raise RateLimitError(
                f"Strava overall rate limit reached (15min={count_o15}, daily={count_odaily})"
            )

        if is_read:
            count_r15 = int(await r.get(key_r15) or 0)
            count_rdaily = int(await r.get(key_rdaily) or 0)
            if count_r15 >= limits["read_15"] or count_rdaily >= limits["read_daily"]:
                raise RateLimitError(
                    f"Strava read rate limit reached (15min={count_r15}, daily={count_rdaily})"
                )

        # Increment counters atomically.
        pipe = r.pipeline()
        pipe.incr(key_o15)
        pipe.expire(key_o15, 900)
        pipe.incr(key_odaily)
        pipe.expire(key_odaily, 86400)
        if is_read:
            pipe.incr(key_r15)
            pipe.expire(key_r15, 900)
            pipe.incr(key_rdaily)
            pipe.expire(key_rdaily, 86400)

        uid = user_id or current_user_id.get()
        if uid:
            bucket = "read" if is_read else "overall"
            ukey = f"usage:strava:user:{uid}:{bucket}:{date_key}"
            pipe.incr(ukey)
            pipe.expire(ukey, 86400 * 40)  # keep ~40d for the rollup job
            if is_read:  # reads also count toward the user's overall usage
                uokey = f"usage:strava:user:{uid}:overall:{date_key}"
                pipe.incr(uokey)
                pipe.expire(uokey, 86400 * 40)
        await pipe.execute()

        return await fn(*args, **kwargs)


RateLimitGuard = RateLimiter  # backwards-compatible alias
rate_limit_guard = RateLimiter()

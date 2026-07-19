"""Per-source-platform poll cadence.

Polling is a property of a *source* connection: one poll of a provider feeds
every pipeline that reads from it. `default` is used when a connection has no
explicit `poll_interval_min`; `min` is the smallest value a user may set, chosen
to stay comfortably within each provider's API rate limits.
"""

from __future__ import annotations

# platform -> (default minutes, minimum minutes)
POLL_INTERVALS: dict[str, tuple[int, int]] = {
    "komoot": (120, 30),  # unofficial API, no webhooks — poll gently
    "garmin": (60, 30),   # unofficial SDK
    "polar": (60, 30),
    "wahoo": (60, 30),
}

# Fallback for any source platform not listed above.
_FALLBACK: tuple[int, int] = (60, 30)

MAX_POLL_INTERVAL_MIN = 1440  # once a day


def poll_interval_bounds(platform: str) -> tuple[int, int]:
    """Return (default, minimum) poll interval in minutes for a source platform."""
    return POLL_INTERVALS.get(platform, _FALLBACK)


def effective_poll_interval_min(platform: str, configured: int | None) -> int:
    """Resolve the interval to use: the configured value, clamped to the platform
    minimum, or the platform default when unset."""
    default, minimum = poll_interval_bounds(platform)
    if configured is None:
        return default
    return max(configured, minimum)

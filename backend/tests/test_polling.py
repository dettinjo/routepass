from __future__ import annotations

from app.core.polling import effective_poll_interval_min, poll_interval_bounds


def test_bounds_known_and_fallback():
    assert poll_interval_bounds("komoot") == (120, 30)
    assert poll_interval_bounds("garmin") == (60, 30)
    # Unknown platform falls back
    assert poll_interval_bounds("something") == (60, 30)


def test_effective_interval():
    # Unset → platform default
    assert effective_poll_interval_min("komoot", None) == 120
    # Valid value kept
    assert effective_poll_interval_min("komoot", 45) == 45
    # Below minimum is clamped up (defence in depth; API also rejects it)
    assert effective_poll_interval_min("komoot", 5) == 30

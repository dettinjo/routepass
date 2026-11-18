from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return to_naive_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt is not None else None

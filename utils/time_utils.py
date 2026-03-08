"""
utils/time_utils.py — Timestamp helpers.

Provides timezone-aware datetime utilities used across the system.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def ms_to_utc(ms: int) -> datetime:
    """Convert a millisecond Unix timestamp to a UTC datetime.

    Args:
        ms: Milliseconds since epoch.

    Returns:
        Timezone-aware UTC datetime.
    """
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def utc_iso(dt: datetime) -> str:
    """Format a datetime as an ISO 8601 string.

    Args:
        dt: Datetime to format.

    Returns:
        ISO 8601 formatted string.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def seconds_since(dt: datetime, now: datetime | None = None) -> float:
    """Calculate seconds elapsed since a given datetime.

    Args:
        dt: Past datetime to measure from.
        now: Current time (defaults to utcnow if not provided).

    Returns:
        Seconds elapsed as a float.
    """
    if now is None:
        now = utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds()

"""
market_data/staleness.py — Quote freshness validation.

Classifies quotes as FRESH, STALE, or DEAD based on their age
relative to configurable thresholds.
"""

from __future__ import annotations

from datetime import datetime, timezone

from normalization.schema import InstrumentQuote, StalenessStatus


def classify_staleness(
    quote: InstrumentQuote,
    stale_threshold_seconds: float = 5.0,
    dead_threshold_seconds: float = 30.0,
    now: datetime | None = None,
) -> StalenessStatus:
    """Classify the freshness of a quote based on its ingest timestamp.

    Args:
        quote: The InstrumentQuote to classify.
        stale_threshold_seconds: Age in seconds before a quote is STALE.
        dead_threshold_seconds: Age in seconds before a quote is DEAD.
        now: Current time (defaults to utcnow if not provided).

    Returns:
        StalenessStatus: FRESH, STALE, or DEAD.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Ensure we compare timezone-aware datetimes
    ingest_ts = quote.ingest_timestamp
    if ingest_ts.tzinfo is None:
        ingest_ts = ingest_ts.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    age_seconds = (now - ingest_ts).total_seconds()

    if age_seconds > dead_threshold_seconds:
        return StalenessStatus.DEAD
    elif age_seconds > stale_threshold_seconds:
        return StalenessStatus.STALE
    else:
        return StalenessStatus.FRESH


def get_quote_age_seconds(
    quote: InstrumentQuote,
    now: datetime | None = None,
) -> float:
    """Calculate the age of a quote in seconds.

    Args:
        quote: The InstrumentQuote to check.
        now: Current time (defaults to utcnow if not provided).

    Returns:
        Age in seconds as a float.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    ingest_ts = quote.ingest_timestamp
    if ingest_ts.tzinfo is None:
        ingest_ts = ingest_ts.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    return (now - ingest_ts).total_seconds()

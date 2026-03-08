"""
filters/staleness.py — Data freshness filter.

Rejects opportunities where either leg has DEAD data.
"""

from __future__ import annotations

from normalization.schema import BasisResult, FilterResult, StalenessStatus, SpotFuturesPair


def filter_staleness(
    pair: SpotFuturesPair,
    max_staleness_seconds: float = 5.0,
) -> FilterResult:
    """Reject if either leg has DEAD staleness status.

    Args:
        pair: The SpotFuturesPair to check.
        max_staleness_seconds: Not directly used — relies on staleness_status
            already set by the aggregator/staleness module.

    Returns:
        FilterResult with pass/fail.
    """
    spot_status = pair.spot.staleness_status
    fut_status = pair.futures.staleness_status

    if spot_status == StalenessStatus.DEAD:
        return FilterResult(
            filter_name="staleness",
            passed=False,
            reason=f"Spot quote is DEAD (exchange={pair.exchange}, asset={pair.asset})",
            value=None,
            threshold=max_staleness_seconds,
        )

    if fut_status == StalenessStatus.DEAD:
        return FilterResult(
            filter_name="staleness",
            passed=False,
            reason=f"Futures quote is DEAD (exchange={pair.exchange}, asset={pair.asset})",
            value=None,
            threshold=max_staleness_seconds,
        )

    return FilterResult(
        filter_name="staleness",
        passed=True,
    )

"""
filters/spread.py — Bid/ask spread filter.

Rejects opportunities where the futures bid/ask spread exceeds the maximum.
"""

from __future__ import annotations

from normalization.schema import BasisResult, FilterResult


def filter_spread(
    basis: BasisResult,
    max_spread_pct: float = 0.001,
) -> FilterResult:
    """Reject if futures bid/ask spread exceeds maximum.

    Args:
        basis: BasisResult containing spread_pct.
        max_spread_pct: Maximum allowed spread as a fraction (0.001 = 0.1%).

    Returns:
        FilterResult with pass/fail.
    """
    spread = basis.spread_pct

    if spread is None:
        return FilterResult(
            filter_name="spread",
            passed=False,
            reason="Spread data unavailable",
            value=None,
            threshold=max_spread_pct,
        )

    if spread > max_spread_pct:
        return FilterResult(
            filter_name="spread",
            passed=False,
            reason=f"Spread {spread:.4%} exceeds max {max_spread_pct:.4%}",
            value=spread,
            threshold=max_spread_pct,
        )

    return FilterResult(
        filter_name="spread",
        passed=True,
        value=spread,
        threshold=max_spread_pct,
    )

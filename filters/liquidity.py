"""
filters/liquidity.py — Volume and depth filters.

Rejects opportunities where 24h volume is below the minimum threshold.
"""

from __future__ import annotations

from normalization.schema import BasisResult, FilterResult


def filter_liquidity(
    basis: BasisResult,
    min_volume_usd_24h: float = 1_000_000,
) -> FilterResult:
    """Reject if 24h volume is below minimum threshold.

    Args:
        basis: BasisResult containing volume_usd_24h.
        min_volume_usd_24h: Minimum 24h volume in USD.

    Returns:
        FilterResult with pass/fail.
    """
    volume = basis.volume_usd_24h

    if volume is None:
        return FilterResult(
            filter_name="liquidity",
            passed=False,
            reason="24h volume data unavailable",
            value=None,
            threshold=min_volume_usd_24h,
        )

    if volume < min_volume_usd_24h:
        return FilterResult(
            filter_name="liquidity",
            passed=False,
            reason=f"24h volume ${volume:,.0f} below min ${min_volume_usd_24h:,.0f}",
            value=volume,
            threshold=min_volume_usd_24h,
        )

    return FilterResult(
        filter_name="liquidity",
        passed=True,
        value=volume,
        threshold=min_volume_usd_24h,
    )

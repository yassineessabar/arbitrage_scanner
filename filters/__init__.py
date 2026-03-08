"""
filters/__init__.py — Institutional filter pipeline runner.

Applies all filters in order and returns aggregate pass/fail results.
Filter order:
  1. Staleness  → reject DEAD data
  2. Liquidity  → reject low volume
  3. Spread     → reject wide spreads
  4. Edge       → reject non-positive net edge / low annualized basis
"""

from __future__ import annotations

from typing import List, Tuple

import structlog

from normalization.schema import BasisResult, FilterResult, SpotFuturesPair
from config.settings import Settings
from filters.staleness import filter_staleness
from filters.liquidity import filter_liquidity
from filters.spread import filter_spread
from filters.edge import filter_edge

logger = structlog.get_logger(__name__)


def run_filter_pipeline(
    pair: SpotFuturesPair,
    basis: BasisResult,
    settings: Settings,
) -> Tuple[bool, List[FilterResult]]:
    """Run the full filter pipeline on a basis result.

    Applies filters in order. Collects all results (does not short-circuit)
    so we can log all rejection reasons.

    Args:
        pair: SpotFuturesPair being evaluated.
        basis: BasisResult for the pair.
        settings: Application settings with filter thresholds.

    Returns:
        Tuple of (passed_all: bool, results: List[FilterResult]).
    """
    results: List[FilterResult] = []

    # Determine min volume for this asset
    asset_symbol = f"{pair.asset}/{pair.spot.quote_currency}"
    min_volume = settings.get_min_volume_for_asset(asset_symbol)

    # 1. Staleness filter
    results.append(
        filter_staleness(
            pair,
            max_staleness_seconds=settings.filters.max_staleness_seconds,
        )
    )

    # 2. Liquidity filter
    results.append(
        filter_liquidity(
            basis,
            min_volume_usd_24h=min_volume,
        )
    )

    # 3. Spread filter
    results.append(
        filter_spread(
            basis,
            max_spread_pct=settings.filters.max_spread_pct,
        )
    )

    # 4. Edge filter
    results.append(
        filter_edge(
            basis,
            min_annualized_basis=settings.filters.min_annualized_basis,
            min_days_to_expiry=settings.filters.min_days_to_expiry,
        )
    )

    passed_all = all(r.passed for r in results)

    if not passed_all:
        reasons = [r.reason for r in results if not r.passed]
        logger.debug(
            "filters_rejected",
            pair_id=pair.pair_id,
            reasons=reasons,
        )

    return passed_all, results

"""
scoring/ranker.py — Sort and rank opportunities by composite score.

Takes scored opportunities and returns them sorted descending by score.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import structlog

from normalization.schema import (
    BasisResult,
    FilterResult,
    Opportunity,
    Signal,
    SpotFuturesPair,
)
from config.settings import Settings
from scoring.scorer import compute_score
from filters import run_filter_pipeline

logger = structlog.get_logger(__name__)


def rank_opportunities(
    pairs: List[SpotFuturesPair],
    basis_results: List[BasisResult],
    settings: Settings,
) -> List[Opportunity]:
    """Score, filter, and rank all opportunities.

    Args:
        pairs: List of SpotFuturesPair objects.
        basis_results: Corresponding BasisResult for each pair.
        settings: Application settings.

    Returns:
        List of Opportunity objects sorted by score descending.
    """
    if len(pairs) != len(basis_results):
        logger.error(
            "pairs_basis_mismatch",
            pairs=len(pairs),
            basis=len(basis_results),
        )
        return []

    now = datetime.now(timezone.utc)
    opportunities: List[Opportunity] = []

    for pair, basis in zip(pairs, basis_results):
        # Run filters
        passed_filters, filter_results = run_filter_pipeline(pair, basis, settings)

        # Compute score
        score = compute_score(pair, basis, settings)

        # Determine signal (use basis signal if passed filters, else downgrade)
        if passed_filters:
            signal = basis.signal
        elif basis.signal in (Signal.CASH_AND_CARRY, Signal.REVERSE_CC):
            signal = Signal.WATCH
        else:
            signal = Signal.NO_TRADE

        opp = Opportunity(
            pair=pair,
            basis_result=basis,
            score=score,
            signal=signal,
            passed_filters=passed_filters,
            filter_results=filter_results,
            ranked_at=now,
        )
        opportunities.append(opp)

    # Sort by score descending
    opportunities.sort(key=lambda o: o.score, reverse=True)

    logger.info(
        "opportunities_ranked",
        total=len(opportunities),
        signals=sum(1 for o in opportunities if o.signal in (Signal.CASH_AND_CARRY, Signal.REVERSE_CC)),
    )

    return opportunities

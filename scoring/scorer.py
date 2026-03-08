"""
scoring/scorer.py — Composite 0–100 opportunity scoring.

Computes a weighted score from:
  - Annualized net edge     (weight from config, default 35%)
  - Liquidity / volume      (weight from config, default 25%)
  - Spread tightness        (weight from config, default 20%)
  - Quote freshness         (weight from config, default 10%)
  - Exchange quality        (weight from config, default 10%)

All normalization functions map raw values to [0, 1].
Score = sum(normalized * weight) * 100, capped at 100.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import structlog

from normalization.schema import BasisResult, ContractType, SpotFuturesPair
from market_data.staleness import get_quote_age_seconds
from config.settings import Settings

logger = structlog.get_logger(__name__)


def compute_score(
    pair: SpotFuturesPair,
    basis: BasisResult,
    settings: Settings,
) -> float:
    """Compute a composite score (0–100) for an arbitrage opportunity.

    Args:
        pair: SpotFuturesPair being scored.
        basis: BasisResult with computed metrics.
        settings: Application settings with scoring weights.

    Returns:
        Float score between 0 and 100.
    """
    weights = settings.scoring.weights
    max_edge = settings.scoring.max_edge_for_normalization
    max_stale = settings.scoring.max_staleness_for_normalization

    # ── 1. Edge Score ──
    # Use annualized net edge for dated, raw net edge for perps
    if basis.contract_type == ContractType.DATED_FUTURE and basis.annualized_net_edge_cc is not None:
        edge_value = max(basis.annualized_net_edge_cc, 0)
    else:
        edge_value = max(basis.net_edge_cc_pct, 0)

    edge_score = _normalize_edge(edge_value, max_edge)

    # ── 2. Liquidity Score ──
    volume = basis.volume_usd_24h or 0.0
    liquidity_score = _normalize_liquidity(volume)

    # ── 3. Spread Score ──
    spread = basis.spread_pct or 0.001
    spread_score = _normalize_spread(spread)

    # ── 4. Freshness Score ──
    # Use the worst (oldest) of the two legs
    spot_age = get_quote_age_seconds(pair.spot)
    fut_age = get_quote_age_seconds(pair.futures)
    worst_age = max(spot_age, fut_age)
    freshness_score = _normalize_freshness(worst_age, max_stale)

    # ── 5. Exchange Quality Score ──
    exchange_score = settings.get_reliability_score(pair.exchange)

    # ── Weighted Sum ──
    raw_score = (
        edge_score * weights.edge
        + liquidity_score * weights.liquidity
        + spread_score * weights.spread
        + freshness_score * weights.freshness
        + exchange_score * weights.exchange
    ) * 100.0

    final_score = min(100.0, max(0.0, raw_score))

    logger.debug(
        "score_computed",
        pair_id=pair.pair_id,
        edge_s=round(edge_score, 3),
        liq_s=round(liquidity_score, 3),
        spread_s=round(spread_score, 3),
        fresh_s=round(freshness_score, 3),
        exch_s=round(exchange_score, 3),
        score=round(final_score, 1),
    )

    return round(final_score, 2)


# ═══════════════════════════════════════════════════════════
# NORMALIZATION FUNCTIONS (all map to [0, 1])
# ═══════════════════════════════════════════════════════════


def _normalize_edge(edge: float, max_edge: float = 0.30) -> float:
    """Normalize annualized net edge to [0, 1].

    Maps 0% → 0, max_edge → 1 (linear).
    """
    return min(max(edge / max_edge, 0.0), 1.0)


def _normalize_liquidity(volume_usd: float) -> float:
    """Normalize 24h volume to [0, 1] on a log scale.

    Maps $1M → 0, $1B → 1.
    """
    if volume_usd <= 0:
        return 0.0
    log_vol = math.log10(volume_usd)
    return min(max((log_vol - 6.0) / 3.0, 0.0), 1.0)


def _normalize_spread(spread_pct: float) -> float:
    """Normalize bid/ask spread to [0, 1].

    Maps 0.1% (0.001) → 0, 0% → 1.
    Tighter spread = higher score.
    """
    return min(max(1.0 - (spread_pct / 0.001), 0.0), 1.0)


def _normalize_freshness(age_seconds: float, max_age: float = 5.0) -> float:
    """Normalize quote age to [0, 1].

    Maps 0s → 1, max_age → 0.
    Fresher = higher score.
    """
    return min(max(1.0 - (age_seconds / max_age), 0.0), 1.0)

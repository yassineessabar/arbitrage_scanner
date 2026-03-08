"""tests/test_scoring.py — Score calculation and ranking tests."""

from datetime import date, datetime, timezone

import pytest

from normalization.schema import ContractType, Signal
from arbitrage.basis import compute_basis
from scoring.scorer import (
    compute_score,
    _normalize_edge,
    _normalize_liquidity,
    _normalize_spread,
    _normalize_freshness,
)
from scoring.ranker import rank_opportunities
from config.settings import get_settings
from tests.conftest import make_pair


class TestNormalizationFunctions:
    def test_edge_boundaries(self):
        assert _normalize_edge(0.0) == 0.0
        assert _normalize_edge(0.15) == 0.5
        assert _normalize_edge(0.30) == 1.0
        assert _normalize_edge(0.50) == 1.0  # capped

    def test_liquidity_boundaries(self):
        assert _normalize_liquidity(0) == 0.0
        assert _normalize_liquidity(1e6) == 0.0  # $1M = 0
        assert _normalize_liquidity(1e9) == 1.0  # $1B = 1
        assert _normalize_liquidity(1e12) == 1.0  # capped

    def test_spread_boundaries(self):
        assert _normalize_spread(0.001) == 0.0  # 0.1% = 0
        assert _normalize_spread(0.0) == 1.0    # 0% = 1
        assert abs(_normalize_spread(0.0005) - 0.5) < 0.01

    def test_freshness_boundaries(self):
        assert _normalize_freshness(0) == 1.0
        assert _normalize_freshness(5) == 0.0
        assert abs(_normalize_freshness(2.5) - 0.5) < 0.01


class TestComputeScore:
    def test_score_in_range(self):
        settings = get_settings()
        pair = make_pair(expiry=date(2026, 9, 25))
        basis = compute_basis(pair, fee_rate=0.0004, slippage=0.0003)
        score = compute_score(pair, basis, settings)
        assert 0 <= score <= 100

    def test_better_edge_higher_score(self):
        settings = get_settings()

        # Low premium
        pair1 = make_pair(fut_bid=64100, fut_ask=64105, expiry=date(2026, 9, 25))
        basis1 = compute_basis(pair1, fee_rate=0.0004, slippage=0.0003)
        score1 = compute_score(pair1, basis1, settings)

        # High premium
        pair2 = make_pair(fut_bid=68000, fut_ask=68005, expiry=date(2026, 9, 25))
        basis2 = compute_basis(pair2, fee_rate=0.0004, slippage=0.0003)
        score2 = compute_score(pair2, basis2, settings)

        assert score2 > score1


class TestRankOpportunities:
    def test_sorted_by_score_descending(self):
        settings = get_settings()
        exp = date(2026, 9, 25)

        pair1 = make_pair(fut_bid=64100, fut_ask=64105, expiry=exp)
        pair2 = make_pair(fut_bid=68000, fut_ask=68005, expiry=exp)

        basis1 = compute_basis(pair1, fee_rate=0.0004, slippage=0.0003)
        basis2 = compute_basis(pair2, fee_rate=0.0004, slippage=0.0003)

        opps = rank_opportunities([pair1, pair2], [basis1, basis2], settings)
        assert len(opps) == 2
        assert opps[0].score >= opps[1].score

    def test_empty_input(self):
        settings = get_settings()
        opps = rank_opportunities([], [], settings)
        assert opps == []

    def test_failed_filter_downgrades_signal(self):
        settings = get_settings()
        pair = make_pair(volume=100, expiry=date(2026, 9, 25))  # very low volume
        basis = compute_basis(pair, fee_rate=0.0004, slippage=0.0003)
        opps = rank_opportunities([pair], [basis], settings)
        assert len(opps) == 1
        # Should be downgraded from CASH_AND_CARRY to WATCH
        assert opps[0].signal in (Signal.WATCH, Signal.NO_TRADE)

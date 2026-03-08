"""tests/test_filters.py — Filter pass/fail logic tests."""

from datetime import date, datetime, timezone

import pytest

from normalization.schema import ContractType, StalenessStatus
from arbitrage.basis import compute_basis
from filters.staleness import filter_staleness
from filters.liquidity import filter_liquidity
from filters.spread import filter_spread
from filters.edge import filter_edge
from filters import run_filter_pipeline
from tests.conftest import make_pair, make_quote


class TestStalenessFilter:
    def test_fresh_passes(self):
        pair = make_pair()
        result = filter_staleness(pair)
        assert result.passed

    def test_stale_passes(self):
        pair = make_pair()
        pair.spot.staleness_status = StalenessStatus.STALE
        result = filter_staleness(pair)
        assert result.passed  # STALE is allowed, only DEAD rejected

    def test_dead_spot_rejected(self):
        pair = make_pair()
        pair.spot.staleness_status = StalenessStatus.DEAD
        result = filter_staleness(pair)
        assert not result.passed
        assert "DEAD" in result.reason

    def test_dead_futures_rejected(self):
        pair = make_pair()
        pair.futures.staleness_status = StalenessStatus.DEAD
        result = filter_staleness(pair)
        assert not result.passed


class TestLiquidityFilter:
    def test_high_volume_passes(self):
        pair = make_pair(volume=2_400_000_000)
        basis = compute_basis(pair)
        result = filter_liquidity(basis, min_volume_usd_24h=1_000_000)
        assert result.passed

    def test_low_volume_rejected(self):
        pair = make_pair(volume=500_000)
        basis = compute_basis(pair)
        result = filter_liquidity(basis, min_volume_usd_24h=1_000_000)
        assert not result.passed
        assert "500,000" in result.reason

    def test_none_volume_rejected(self):
        pair = make_pair()
        basis = compute_basis(pair)
        basis.volume_usd_24h = None
        result = filter_liquidity(basis, min_volume_usd_24h=1_000_000)
        assert not result.passed


class TestSpreadFilter:
    def test_tight_spread_passes(self):
        pair = make_pair(fut_bid=65100, fut_ask=65105)  # ~0.008%
        basis = compute_basis(pair)
        result = filter_spread(basis, max_spread_pct=0.001)
        assert result.passed

    def test_wide_spread_rejected(self):
        pair = make_pair(fut_bid=64000, fut_ask=64200)  # ~0.31%
        basis = compute_basis(pair)
        result = filter_spread(basis, max_spread_pct=0.001)
        assert not result.passed


class TestEdgeFilter:
    def test_positive_edge_passes(self):
        # Use a large premium to ensure annualized basis > 5% with ~200 DTE
        pair = make_pair(
            spot_bid=64000, spot_ask=64005,
            fut_bid=66500, fut_ask=66505,
            expiry=date(2026, 9, 25),
        )
        basis = compute_basis(pair, fee_rate=0.0004, slippage=0.0003)
        result = filter_edge(basis, min_annualized_basis=0.05)
        assert result.passed

    def test_no_positive_edge_rejected(self):
        pair = make_pair(
            spot_bid=64000, spot_ask=64005,
            fut_bid=64006, fut_ask=64010,
        )
        basis = compute_basis(pair, fee_rate=0.01, slippage=0.005)
        result = filter_edge(basis)
        assert not result.passed

    def test_low_dte_rejected(self):
        pair = make_pair(expiry=date(2026, 3, 8))  # today or very soon
        basis = compute_basis(pair)
        result = filter_edge(basis, min_days_to_expiry=2.0)
        assert not result.passed


class TestFilterPipeline:
    def test_good_opportunity_passes_all(self):
        from config.settings import get_settings
        settings = get_settings()
        # Large premium to clear the 5% annualized basis threshold
        pair = make_pair(
            spot_bid=64000, spot_ask=64005,
            fut_bid=66500, fut_ask=66505,
            expiry=date(2026, 9, 25),
        )
        basis = compute_basis(pair, fee_rate=0.0004, slippage=0.0003)
        passed, results = run_filter_pipeline(pair, basis, settings)
        assert passed
        assert all(r.passed for r in results)

    def test_multiple_failures_collected(self):
        from config.settings import get_settings
        settings = get_settings()
        pair = make_pair(
            volume=100_000,
            fut_bid=64000, fut_ask=64200,  # wide spread
            expiry=date(2026, 9, 25),
        )
        pair.spot.staleness_status = StalenessStatus.DEAD
        basis = compute_basis(pair)
        passed, results = run_filter_pipeline(pair, basis, settings)
        assert not passed
        failed = [r for r in results if not r.passed]
        assert len(failed) >= 2  # At least staleness + liquidity

"""tests/test_basis.py — Basis math correctness tests with known values."""

from datetime import date, datetime, timezone

import pytest

from normalization.schema import ContractType, Signal
from arbitrage.basis import compute_basis, _classify_signal
from arbitrage.carry import annualize
from tests.conftest import make_pair


class TestAnnualize:
    def test_basic_annualization(self):
        result = annualize(0.0066, 42.0)
        expected = 0.0066 * 365.0 / 42.0
        assert abs(result - expected) < 1e-10

    def test_none_dte_returns_none(self):
        assert annualize(0.01, None) is None

    def test_zero_dte_returns_none(self):
        assert annualize(0.01, 0.0) is None

    def test_negative_dte_returns_none(self):
        assert annualize(0.01, -5.0) is None


class TestComputeBasis:
    def test_cash_and_carry_known_values(self):
        """Test with known spot=64000/64005, futures=65100/65105, DTE~200."""
        pair = make_pair(
            spot_bid=64000.0, spot_ask=64005.0,
            fut_bid=65100.0, fut_ask=65105.0,
            expiry=date(2026, 9, 25),
        )
        br = compute_basis(pair, fee_rate=0.0004, slippage=0.0003)

        # Mid-based
        assert br.spot_mid == 64002.5
        assert br.futures_mid == 65102.5
        assert abs(br.basis_abs - 1100.0) < 0.01
        assert br.basis_pct > 0

        # Executable
        assert br.executable_basis_cc == 65100.0 - 64005.0  # 1095.0
        assert br.executable_basis_rcc == 64000.0 - 65105.0  # -1105.0

        # Net edge (CC should be positive)
        total_cost = 2 * 0.0004 + 2 * 0.0003  # 0.0014
        expected_gross_cc = 1095.0 / 64005.0
        expected_net_cc = expected_gross_cc - total_cost
        assert abs(br.net_edge_cc_pct - expected_net_cc) < 1e-8

        # Signal
        assert br.signal == Signal.CASH_AND_CARRY

        # Annualized should exist for dated
        assert br.annualized_basis is not None
        assert br.annualized_net_edge_cc is not None

    def test_perpetual_no_annualization(self):
        """Perpetual contracts should not have annualized fields."""
        pair = make_pair(
            contract_type=ContractType.PERPETUAL,
            fut_bid=64050.0, fut_ask=64060.0,
            expiry=None,
        )
        br = compute_basis(pair, fee_rate=0.0004, slippage=0.0003)

        assert br.is_perpetual
        assert br.annualized_basis is None
        assert br.annualized_net_edge_cc is None
        assert br.annualized_net_edge_rcc is None

    def test_backwardation_reverse_cc(self):
        """When futures < spot, should get REVERSE_CC signal."""
        pair = make_pair(
            spot_bid=65100.0, spot_ask=65105.0,
            fut_bid=64000.0, fut_ask=64005.0,
            contract_type=ContractType.PERPETUAL,
            expiry=None,
        )
        br = compute_basis(pair, fee_rate=0.0004, slippage=0.0003)

        assert br.basis_abs < 0
        assert br.signal == Signal.REVERSE_CC

    def test_no_edge_produces_watch_or_no_trade(self):
        """When costs eat all edge, signal should be WATCH or NO_TRADE."""
        pair = make_pair(
            spot_bid=64000.0, spot_ask=64005.0,
            fut_bid=64006.0, fut_ask=64010.0,  # tiny premium
        )
        br = compute_basis(pair, fee_rate=0.01, slippage=0.005)  # high costs

        assert br.signal in (Signal.WATCH, Signal.NO_TRADE)


class TestClassifySignal:
    def test_cash_and_carry(self):
        assert _classify_signal(100, 0.01, -0.02) == Signal.CASH_AND_CARRY

    def test_reverse_cc(self):
        assert _classify_signal(-100, -0.02, 0.01) == Signal.REVERSE_CC

    def test_watch(self):
        assert _classify_signal(50, -0.0005, -0.001) == Signal.WATCH

    def test_no_trade(self):
        assert _classify_signal(0, -0.01, -0.01) == Signal.NO_TRADE

"""tests/test_simulation.py — P&L simulation engine tests."""

from datetime import date, datetime, timezone, timedelta

import pytest

from normalization.schema import ContractType, Signal
from arbitrage.basis import compute_basis
from scoring.ranker import rank_opportunities
from config.settings import get_settings
from simulation.engine import SimulationEngine
from simulation.models import ExitReason
from tests.conftest import make_pair


def _make_qualifying_opp(settings, **pair_kwargs):
    """Create an opportunity that passes all filters (high premium, CC signal)."""
    defaults = dict(
        spot_bid=64000, spot_ask=64005,
        fut_bid=66500, fut_ask=66505,
        expiry=date(2026, 9, 25),
    )
    defaults.update(pair_kwargs)
    pair = make_pair(**defaults)
    basis = compute_basis(pair, fee_rate=0.0004, slippage=0.0003)
    opps = rank_opportunities([pair], [basis], settings)
    assert len(opps) == 1
    assert opps[0].passed_filters
    return opps[0]


def _make_opp_any(settings, **pair_kwargs):
    """Create an opportunity (may not pass filters — for exit price scenarios)."""
    defaults = dict(
        spot_bid=64000, spot_ask=64005,
        fut_bid=66500, fut_ask=66505,
        expiry=date(2026, 9, 25),
    )
    defaults.update(pair_kwargs)
    pair = make_pair(**defaults)
    basis = compute_basis(pair, fee_rate=0.0004, slippage=0.0003)
    opps = rank_opportunities([pair], [basis], settings)
    assert len(opps) == 1
    return opps[0]


class TestSimulationEntry:
    def test_qualifying_opportunity_opens_trade(self):
        settings = get_settings()
        settings.simulation.enabled = True
        settings.simulation.min_score_to_trade = 0  # accept anything
        engine = SimulationEngine(settings)
        opp = _make_qualifying_opp(settings)

        trade = engine.process_opportunity(opp)
        assert trade is not None
        assert trade.exchange == "binance"
        assert trade.asset == "BTC"
        assert trade.is_open
        assert engine.open_position_count == 1

    def test_non_qualifying_signal_rejected(self):
        settings = get_settings()
        settings.simulation.enabled = True
        engine = SimulationEngine(settings)

        # Low premium → WATCH/NO_TRADE signal
        pair = make_pair(
            spot_bid=64000, spot_ask=64005,
            fut_bid=64006, fut_ask=64010,
            expiry=date(2026, 9, 25),
        )
        basis = compute_basis(pair, fee_rate=0.01, slippage=0.005)
        opps = rank_opportunities([pair], [basis], settings)
        opp = opps[0]

        trade = engine.process_opportunity(opp)
        assert trade is None
        assert engine.open_position_count == 0

    def test_max_positions_limit(self):
        settings = get_settings()
        settings.simulation.enabled = True
        settings.simulation.max_open_positions = 2
        settings.simulation.min_score_to_trade = 0
        engine = SimulationEngine(settings)

        # Open 2 positions (different pair_ids)
        opp1 = _make_qualifying_opp(settings, asset="BTC")
        opp2 = _make_qualifying_opp(settings, asset="ETH",
                                     spot_bid=3400, spot_ask=3401,
                                     fut_bid=3550, fut_ask=3551)

        assert engine.process_opportunity(opp1) is not None
        assert engine.process_opportunity(opp2) is not None
        assert engine.open_position_count == 2

        # Third should be rejected
        opp3 = _make_qualifying_opp(settings, exchange="bybit")
        assert engine.process_opportunity(opp3) is None

    def test_duplicate_pair_rejected(self):
        settings = get_settings()
        settings.simulation.enabled = True
        settings.simulation.min_score_to_trade = 0
        engine = SimulationEngine(settings)

        opp = _make_qualifying_opp(settings)
        assert engine.process_opportunity(opp) is not None
        # Same pair_id
        assert engine.process_opportunity(opp) is None
        assert engine.open_position_count == 1

    def test_low_score_rejected(self):
        settings = get_settings()
        settings.simulation.enabled = True
        settings.simulation.min_score_to_trade = 99.0  # very high threshold
        engine = SimulationEngine(settings)

        opp = _make_qualifying_opp(settings)
        # Score likely below 99
        trade = engine.process_opportunity(opp)
        assert trade is None


class TestSimulationExit:
    def test_convergence_exit(self):
        settings = get_settings()
        settings.simulation.enabled = True
        settings.simulation.min_score_to_trade = 0
        settings.simulation.exit_basis_convergence_pct = 0.005
        engine = SimulationEngine(settings)

        # Entry: large basis
        opp_entry = _make_qualifying_opp(settings)
        engine.process_opportunity(opp_entry)
        assert engine.open_position_count == 1

        # Exit: basis converged (futures ~ spot)
        opp_exit = _make_opp_any(
            settings,
            spot_bid=64000, spot_ask=64005,
            fut_bid=64010, fut_ask=64015,  # tiny basis ~0.015%
        )
        # Override the pair_id to match
        opp_exit.pair.pair_id = opp_entry.pair.pair_id

        closed = engine.check_exits([opp_exit])
        assert len(closed) == 1
        assert closed[0].exit_reason == ExitReason.CONVERGENCE
        assert engine.open_position_count == 0

    def test_max_hold_exit(self):
        settings = get_settings()
        settings.simulation.enabled = True
        settings.simulation.min_score_to_trade = 0
        settings.simulation.max_hold_days = 0  # immediate force close
        engine = SimulationEngine(settings)

        opp = _make_qualifying_opp(settings)
        trade = engine.process_opportunity(opp)
        assert trade is not None

        # Backdate entry to trigger max hold
        pair_id = opp.pair.pair_id
        engine._open_positions[pair_id] = trade.model_copy(
            update={"entry_time": datetime(2025, 1, 1, tzinfo=timezone.utc)}
        )

        closed = engine.check_exits([opp])
        assert len(closed) == 1
        assert closed[0].exit_reason == ExitReason.MAX_HOLD


class TestSimulationPnL:
    def test_pnl_calculation(self):
        settings = get_settings()
        settings.simulation.enabled = True
        settings.simulation.min_score_to_trade = 0
        settings.simulation.initial_capital = 100_000
        settings.simulation.position_size_pct = 0.10  # $10,000 position
        settings.simulation.exit_basis_convergence_pct = 0.005
        engine = SimulationEngine(settings)

        # Entry: ~3.9% basis
        opp_entry = _make_qualifying_opp(settings)
        engine.process_opportunity(opp_entry)

        # Exit: basis converged
        opp_exit = _make_opp_any(
            settings,
            fut_bid=64010, fut_ask=64015,
        )
        opp_exit.pair.pair_id = opp_entry.pair.pair_id

        closed = engine.check_exits([opp_exit])
        assert len(closed) == 1

        trade = closed[0]
        # Gross P&L should be positive (basis narrowed)
        assert trade.gross_pnl > 0
        # Fees and slippage should be positive
        assert trade.fees_paid > 0
        assert trade.slippage_cost > 0
        # Net P&L = gross - fees - slippage
        expected_net = trade.gross_pnl - trade.fees_paid - trade.slippage_cost
        assert abs(trade.net_pnl - expected_net) < 0.01

    def test_result_summary(self):
        settings = get_settings()
        settings.simulation.enabled = True
        settings.simulation.min_score_to_trade = 0
        settings.simulation.exit_basis_convergence_pct = 0.005
        engine = SimulationEngine(settings)

        # Entry + Exit
        opp_entry = _make_qualifying_opp(settings)
        engine.process_opportunity(opp_entry)

        opp_exit = _make_opp_any(
            settings, fut_bid=64010, fut_ask=64015,
        )
        opp_exit.pair.pair_id = opp_entry.pair.pair_id
        engine.check_exits([opp_exit])

        result = engine.get_result()
        assert result.total_trades == 1
        assert result.total_fees > 0
        assert result.total_slippage > 0

    def test_dashboard_state_export(self):
        settings = get_settings()
        settings.simulation.enabled = True
        settings.simulation.min_score_to_trade = 0
        engine = SimulationEngine(settings)

        opp = _make_qualifying_opp(settings)
        engine.process_opportunity(opp)

        state = engine.get_state_for_dashboard()
        assert state["enabled"] is True
        assert len(state["open_positions"]) == 1
        assert len(state["equity_curve"]) >= 1

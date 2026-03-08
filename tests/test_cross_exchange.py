"""tests/test_cross_exchange.py — Cross-exchange arbitrage simulation tests."""

from datetime import datetime, timezone, timedelta

import pytest

from config.settings import get_settings
from normalization.schema import ContractType
from simulation.cross_exchange import CrossExchangeEngine, CrossExchangeOpportunity
from simulation.models import ExitReason
from tests.conftest import make_quote


def _make_quotes_with_spread(
    asset="BTC",
    cheap_exchange="binance",
    expensive_exchange="okx",
    cheap_price=68000.0,
    expensive_price=68200.0,
    ts=None,
):
    """Create quotes where one exchange is cheaper than another."""
    if ts is None:
        ts = datetime.now(timezone.utc)

    cheap_quote = make_quote(
        exchange=cheap_exchange,
        asset=asset,
        contract_type=ContractType.SPOT,
        bid=cheap_price - 2,
        ask=cheap_price,
        ts=ts,
    )
    expensive_quote = make_quote(
        exchange=expensive_exchange,
        asset=asset,
        contract_type=ContractType.SPOT,
        bid=expensive_price,
        ask=expensive_price + 2,
        ts=ts,
    )
    return [cheap_quote, expensive_quote]


class TestCrossExchangeOpportunityDetection:
    def test_detects_spread_above_threshold(self):
        settings = get_settings()
        settings.cross_exchange.min_edge_to_trade = 0.0005
        engine = CrossExchangeEngine(settings)

        # ~0.29% spread — well above costs (~15 bps) + min_edge (5 bps)
        quotes = _make_quotes_with_spread(
            cheap_price=68000.0, expensive_price=68200.0,
        )
        opps = engine.scan_quotes(quotes)
        assert len(opps) >= 1
        # Should find buy on binance, sell on okx
        opp = next(o for o in opps if o.buy_exchange == "binance")
        assert opp.sell_exchange == "okx"
        assert opp.spread_pct > 0
        assert opp.net_edge_pct > 0

    def test_no_opportunity_when_spread_below_costs(self):
        settings = get_settings()
        settings.cross_exchange.min_edge_to_trade = 0.01  # 100 bps — very high
        engine = CrossExchangeEngine(settings)

        # ~0.29% spread — below 100 bps threshold
        quotes = _make_quotes_with_spread(
            cheap_price=68000.0, expensive_price=68200.0,
        )
        opps = engine.scan_quotes(quotes)
        assert len(opps) == 0

    def test_no_opportunity_when_prices_equal(self):
        settings = get_settings()
        engine = CrossExchangeEngine(settings)

        quotes = _make_quotes_with_spread(
            cheap_price=68000.0, expensive_price=68000.0,
        )
        opps = engine.scan_quotes(quotes)
        assert len(opps) == 0

    def test_needs_at_least_two_exchanges(self):
        settings = get_settings()
        engine = CrossExchangeEngine(settings)
        ts = datetime.now(timezone.utc)

        # Only one exchange
        quotes = [make_quote(
            exchange="binance", asset="BTC",
            contract_type=ContractType.SPOT,
            bid=68000, ask=68002, ts=ts,
        )]
        opps = engine.scan_quotes(quotes)
        assert len(opps) == 0


class TestCrossExchangeEntry:
    def test_qualifying_opportunity_opens_trade(self):
        settings = get_settings()
        settings.cross_exchange.min_edge_to_trade = 0.0001
        engine = CrossExchangeEngine(settings)

        quotes = _make_quotes_with_spread()
        opps = engine.scan_quotes(quotes)
        assert len(opps) >= 1

        trade = engine.process_opportunity(opps[0])
        assert trade is not None
        assert "binance" in trade.exchange or "okx" in trade.exchange
        assert trade.signal == "CROSS_EXCHANGE"
        assert engine.open_position_count == 1

    def test_max_positions_limit(self):
        settings = get_settings()
        settings.cross_exchange.max_open_positions = 1
        settings.cross_exchange.min_edge_to_trade = 0.0001
        engine = CrossExchangeEngine(settings)

        quotes = _make_quotes_with_spread(asset="BTC")
        opps = engine.scan_quotes(quotes)
        engine.process_opportunity(opps[0])
        assert engine.open_position_count == 1

        # Second should be rejected
        quotes2 = _make_quotes_with_spread(
            asset="ETH", cheap_price=2100, expensive_price=2105,
        )
        opps2 = engine.scan_quotes(quotes2)
        if opps2:
            trade = engine.process_opportunity(opps2[0])
            assert trade is None

    def test_duplicate_pair_rejected(self):
        settings = get_settings()
        settings.cross_exchange.min_edge_to_trade = 0.0001
        engine = CrossExchangeEngine(settings)

        quotes = _make_quotes_with_spread()
        opps = engine.scan_quotes(quotes)
        engine.process_opportunity(opps[0])

        # Same pair_id
        trade = engine.process_opportunity(opps[0])
        assert trade is None
        assert engine.open_position_count == 1


class TestCrossExchangeExit:
    def test_convergence_exit(self):
        settings = get_settings()
        settings.cross_exchange.min_edge_to_trade = 0.0001
        settings.cross_exchange.exit_convergence_threshold = 0.001
        engine = CrossExchangeEngine(settings)

        ts = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)

        # Entry: large spread (~0.29%)
        quotes_entry = _make_quotes_with_spread(
            cheap_price=68000, expensive_price=68200, ts=ts,
        )
        opps_entry = engine.scan_quotes(quotes_entry, as_of=ts)
        assert len(opps_entry) >= 1
        engine.process_opportunity(opps_entry[0])
        assert engine.open_position_count == 1

        # Exit: prices converged → no matching opportunity → triggers convergence
        ts2 = ts + timedelta(minutes=30)
        quotes_exit = _make_quotes_with_spread(
            cheap_price=68100, expensive_price=68100, ts=ts2,
        )
        opps_exit = engine.scan_quotes(quotes_exit, as_of=ts2)
        closed = engine.check_exits(opps_exit, as_of=ts2)
        assert len(closed) == 1
        assert closed[0].exit_reason == ExitReason.CONVERGENCE
        assert engine.open_position_count == 0

    def test_max_hold_exit(self):
        settings = get_settings()
        settings.cross_exchange.min_edge_to_trade = 0.0001
        settings.cross_exchange.max_hold_minutes = 60
        engine = CrossExchangeEngine(settings)

        ts = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
        quotes = _make_quotes_with_spread(ts=ts)
        opps = engine.scan_quotes(quotes, as_of=ts)
        engine.process_opportunity(opps[0])

        # Backdate entry to trigger max hold
        pair_id = list(engine._open_positions.keys())[0]
        trade = engine._open_positions[pair_id]
        engine._open_positions[pair_id] = trade.model_copy(
            update={"entry_time": datetime(2025, 1, 1, tzinfo=timezone.utc)}
        )

        ts2 = ts + timedelta(hours=2)
        closed = engine.check_exits(opps, as_of=ts2)
        assert len(closed) == 1
        assert closed[0].exit_reason == ExitReason.MAX_HOLD


class TestCrossExchangePnL:
    def test_pnl_positive_on_convergence(self):
        settings = get_settings()
        settings.cross_exchange.min_edge_to_trade = 0.0001
        settings.cross_exchange.exit_convergence_threshold = 0.001
        settings.cross_exchange.initial_capital = 10_000
        settings.cross_exchange.position_size_pct = 0.10
        engine = CrossExchangeEngine(settings)

        ts = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)

        # Entry: ~0.29% spread
        quotes_entry = _make_quotes_with_spread(
            cheap_price=68000, expensive_price=68200, ts=ts,
        )
        opps_entry = engine.scan_quotes(quotes_entry, as_of=ts)
        engine.process_opportunity(opps_entry[0])

        # Exit: spread converges
        ts2 = ts + timedelta(minutes=30)
        quotes_exit = _make_quotes_with_spread(
            cheap_price=68100, expensive_price=68100, ts=ts2,
        )
        opps_exit = engine.scan_quotes(quotes_exit, as_of=ts2)
        closed = engine.check_exits(opps_exit, as_of=ts2)
        assert len(closed) == 1

        trade = closed[0]
        assert trade.gross_pnl > 0
        assert trade.fees_paid > 0
        assert trade.slippage_cost > 0

    def test_result_summary(self):
        settings = get_settings()
        settings.cross_exchange.min_edge_to_trade = 0.0001
        settings.cross_exchange.exit_convergence_threshold = 0.001
        settings.cross_exchange.initial_capital = 10_000
        engine = CrossExchangeEngine(settings)

        ts = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
        quotes_entry = _make_quotes_with_spread(
            cheap_price=68000, expensive_price=68200, ts=ts,
        )
        opps_entry = engine.scan_quotes(quotes_entry, as_of=ts)
        engine.process_opportunity(opps_entry[0])

        ts2 = ts + timedelta(minutes=30)
        quotes_exit = _make_quotes_with_spread(
            cheap_price=68100, expensive_price=68100, ts=ts2,
        )
        opps_exit = engine.scan_quotes(quotes_exit, as_of=ts2)
        engine.check_exits(opps_exit, as_of=ts2)

        result = engine.get_result()
        assert result.total_trades == 1
        assert result.total_fees > 0
        assert result.total_slippage > 0

    def test_dashboard_state_export(self):
        settings = get_settings()
        settings.cross_exchange.min_edge_to_trade = 0.0001
        engine = CrossExchangeEngine(settings)

        ts = datetime.now(timezone.utc)
        quotes = _make_quotes_with_spread(ts=ts)
        opps = engine.scan_quotes(quotes, as_of=ts)
        engine.process_opportunity(opps[0])

        state = engine.get_state_for_dashboard()
        assert state["enabled"] is True
        assert len(state["open_positions"]) == 1
        assert len(state["equity_curve"]) >= 1


class TestCrossExchangeDemo:
    def test_demo_runs_without_error(self):
        from simulation.cross_exchange_demo import run_cross_exchange_demo

        settings = get_settings()
        state = run_cross_exchange_demo(settings)
        assert state["enabled"] is True
        assert state["total_trades"] > 0
        assert len(state["equity_curve"]) > 1
        assert state["initial_capital"] == 10_000

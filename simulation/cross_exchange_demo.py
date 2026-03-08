"""
simulation/cross_exchange_demo.py — Generate demo data for cross-exchange arb simulation.

Creates synthetic quotes across 3 exchanges with periodic price dislocations
that mean-revert, producing a realistic set of cross-exchange arbitrage trades.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import List

from config.settings import Settings, get_settings
from normalization.schema import ContractType, InstrumentQuote
from simulation.cross_exchange import CrossExchangeEngine


def _make_quote(
    exchange: str,
    asset: str,
    price: float,
    ts: datetime,
    volume: float = 2_000_000_000,
) -> InstrumentQuote:
    """Build a synthetic SPOT quote."""
    spread = price * 0.00005  # tight spread
    bid = price - spread / 2
    ask = price + spread / 2
    mid = price

    return InstrumentQuote(
        exchange=exchange,
        raw_symbol=f"{asset}USDT",
        internal_symbol=f"{asset}/USDT SPOT",
        asset=asset,
        contract_type=ContractType.SPOT,
        expiry=None,
        bid=bid,
        ask=ask,
        mid=mid,
        last=mid,
        volume_24h=volume,
        exchange_timestamp=ts,
        ingest_timestamp=ts,
    )


def run_cross_exchange_demo(settings: Settings | None = None) -> dict:
    """Run a demo cross-exchange simulation with synthetic dislocations.

    Generates 7 days of data sampled every 30 minutes. Periodically introduces
    price dislocations on one exchange that mean-revert over subsequent intervals.

    Returns:
        Dashboard-ready simulation state dict.
    """
    if settings is None:
        settings = get_settings()

    settings.cross_exchange.enabled = True
    settings.cross_exchange.initial_capital = 10_000
    settings.cross_exchange.position_size_pct = 0.10
    settings.cross_exchange.max_open_positions = 5
    settings.cross_exchange.min_edge_to_trade = 0.0005   # 5 bps
    settings.cross_exchange.exit_convergence_threshold = 0.0002  # 2 bps
    settings.cross_exchange.max_hold_minutes = 120
    settings.cross_exchange.slippage_per_side = 0.0003

    engine = CrossExchangeEngine(settings)

    random.seed(99)  # reproducible

    start = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
    assets = ["BTC", "ETH", "SOL"]
    exchanges = ["binance", "bybit", "okx"]
    base_prices = {"BTC": 68000.0, "ETH": 2100.0, "SOL": 95.0}

    # Track exchange-specific deviations (mean-reverting)
    deviations = {
        (asset, ex): 0.0
        for asset in assets
        for ex in exchanges
    }

    # Simulate 7 days × 48 intervals (every 30 min) = 336 intervals
    num_intervals = 336
    interval_minutes = 30

    for i in range(num_intervals):
        ts = start + timedelta(minutes=i * interval_minutes)
        quotes: List[InstrumentQuote] = []

        for asset in assets:
            base = base_prices[asset]
            # Slow random walk for the "true" price
            base_prices[asset] = base * (1 + random.gauss(0, 0.001))
            true_price = base_prices[asset]

            for ex in exchanges:
                key = (asset, ex)

                # Periodically introduce a dislocation
                if random.random() < 0.04:  # ~4% chance per interval per exchange
                    # Dislocation: 10-30 bps deviation
                    direction = random.choice([-1, 1])
                    magnitude = random.uniform(0.001, 0.003)
                    deviations[key] = direction * magnitude
                else:
                    # Mean-revert: decay toward zero
                    deviations[key] *= random.uniform(0.3, 0.7)

                # Small noise on top
                noise = random.gauss(0, 0.0001)
                price = true_price * (1 + deviations[key] + noise)

                quote = _make_quote(
                    exchange=ex,
                    asset=asset,
                    price=price,
                    ts=ts,
                )
                quotes.append(quote)

        # Scan for opportunities
        opps = engine.scan_quotes(quotes, as_of=ts)

        # Check exits first, then process new entries
        engine.check_exits(opps, as_of=ts)
        for opp in opps:
            engine.process_opportunity(opp)

    # Force close any remaining positions
    final_ts = start + timedelta(minutes=num_intervals * interval_minutes + 60)
    final_quotes: List[InstrumentQuote] = []
    for asset in assets:
        price = base_prices[asset]
        for ex in exchanges:
            final_quotes.append(_make_quote(ex, asset, price, final_ts))

    final_opps = engine.scan_quotes(final_quotes, as_of=final_ts)
    engine.check_exits(final_opps, as_of=final_ts)

    return engine.get_state_for_dashboard()

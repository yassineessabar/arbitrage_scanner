"""
simulation/demo.py — Generate demo simulation data with synthetic trades.

Creates a realistic-looking simulation with 20+ trades over a simulated
time period to demonstrate the P&L simulation dashboard.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import List

from config.settings import Settings, get_settings
from normalization.schema import (
    BasisResult,
    ContractType,
    FilterResult,
    InstrumentQuote,
    Opportunity,
    Signal,
    SpotFuturesPair,
)
from simulation.engine import SimulationEngine


def _make_demo_opportunity(
    exchange: str,
    asset: str,
    spot_price: float,
    futures_premium_pct: float,
    ts: datetime,
    expiry: date,
    volume: float = 2_000_000_000,
    fee_rate: float = 0.0004,
    slippage: float = 0.0003,
) -> Opportunity:
    """Build a synthetic Opportunity for demo purposes."""
    spread = spot_price * 0.00008  # tight spread

    spot_bid = spot_price
    spot_ask = spot_price + spread
    spot_mid = (spot_bid + spot_ask) / 2

    fut_mid = spot_price * (1 + futures_premium_pct)
    fut_bid = fut_mid - spread / 2
    fut_ask = fut_mid + spread / 2

    spot = InstrumentQuote(
        exchange=exchange,
        raw_symbol=f"{asset}USDT",
        internal_symbol=f"{asset}/USDT SPOT",
        asset=asset,
        contract_type=ContractType.SPOT,
        expiry=None,
        bid=spot_bid,
        ask=spot_ask,
        mid=spot_mid,
        last=spot_mid,
        volume_24h=volume,
        exchange_timestamp=ts,
        ingest_timestamp=ts,
    )

    futures = InstrumentQuote(
        exchange=exchange,
        raw_symbol=f"{asset}USDT_FUT",
        internal_symbol=f"{asset}/USDT FUT {expiry}",
        asset=asset,
        contract_type=ContractType.DATED_FUTURE,
        expiry=expiry,
        bid=fut_bid,
        ask=fut_ask,
        mid=fut_mid,
        last=fut_mid,
        volume_24h=volume,
        exchange_timestamp=ts,
        ingest_timestamp=ts,
    )

    pair_id = f"{exchange}_{asset}_{expiry.strftime('%Y%m%d')}"
    pair = SpotFuturesPair(
        exchange=exchange,
        asset=asset,
        spot=spot,
        futures=futures,
        pair_id=pair_id,
        created_at=ts,
    )

    # Compute basis
    basis_abs = fut_mid - spot_mid
    basis_pct = basis_abs / spot_mid
    exec_cc = fut_bid - spot_ask
    exec_rcc = spot_bid - fut_ask
    gross_cc = exec_cc / spot_ask if spot_ask > 0 else 0
    gross_rcc = exec_rcc / spot_bid if spot_bid > 0 else 0
    total_cost = 2 * fee_rate + 2 * slippage
    net_cc = gross_cc - total_cost
    net_rcc = gross_rcc - total_cost

    dte = (expiry - ts.date()).days
    dte = max(dte, 1)
    ann_factor = 365.0 / dte
    ann_basis = basis_pct * ann_factor
    ann_net_cc = net_cc * ann_factor
    ann_net_rcc = net_rcc * ann_factor

    # Only signal CC if basis is meaningfully above convergence threshold
    if net_cc > 0 and basis_pct > 0.008:
        signal = Signal.CASH_AND_CARRY
    elif net_rcc > 0 and basis_pct < -0.008:
        signal = Signal.REVERSE_CC
    else:
        signal = Signal.WATCH

    basis_result = BasisResult(
        exchange=exchange,
        asset=asset,
        spot_symbol=spot.internal_symbol,
        futures_symbol=futures.internal_symbol,
        contract_type=ContractType.DATED_FUTURE,
        expiry=expiry,
        spot_bid=spot_bid,
        spot_ask=spot_ask,
        spot_mid=spot_mid,
        futures_bid=fut_bid,
        futures_ask=fut_ask,
        futures_mid=fut_mid,
        basis_abs=basis_abs,
        basis_pct=basis_pct,
        annualized_basis=ann_basis,
        executable_basis_cc=exec_cc,
        executable_basis_rcc=exec_rcc,
        gross_edge_cc_pct=gross_cc,
        gross_edge_rcc_pct=gross_rcc,
        net_edge_cc_pct=net_cc,
        net_edge_rcc_pct=net_rcc,
        annualized_net_edge_cc=ann_net_cc,
        annualized_net_edge_rcc=ann_net_rcc,
        signal=signal,
        timestamp=ts,
        volume_usd_24h=volume,
        spread_pct=spread / spot_mid,
    )

    passed = signal in (Signal.CASH_AND_CARRY, Signal.REVERSE_CC)
    score = 75.0 + random.uniform(-10, 10) if passed else 40.0

    return Opportunity(
        pair=pair,
        basis_result=basis_result,
        score=score,
        signal=signal,
        passed_filters=passed,
        filter_results=[
            FilterResult(filter_name="staleness", passed=True, reason=""),
            FilterResult(filter_name="liquidity", passed=True, reason="",
                         value=volume, threshold=1_000_000),
            FilterResult(filter_name="spread", passed=True, reason="",
                         value=spread / spot_mid, threshold=0.001),
            FilterResult(filter_name="edge", passed=passed, reason="" if passed else "No edge",
                         value=max(net_cc, net_rcc), threshold=0.0),
        ],
        ranked_at=ts,
    )


def run_demo_simulation(settings: Settings | None = None) -> dict:
    """Run a demo simulation with synthetic data and return dashboard state.

    Generates ~30 opportunities over 60 simulated days with varying basis,
    producing a mix of winning and losing trades.

    Returns:
        Dashboard-ready simulation state dict.
    """
    if settings is None:
        settings = get_settings()

    settings.simulation.enabled = True
    settings.simulation.min_score_to_trade = 60.0
    settings.simulation.initial_capital = 10_000
    settings.simulation.position_size_pct = 0.10
    settings.simulation.max_open_positions = 3
    settings.simulation.exit_basis_convergence_pct = 0.006  # 0.6% convergence
    settings.simulation.max_hold_days = 10  # force close after 10 days

    engine = SimulationEngine(settings)

    random.seed(42)  # reproducible

    start = datetime(2026, 1, 5, 10, 0, 0, tzinfo=timezone.utc)
    expiry = date(2026, 6, 27)

    assets = ["BTC", "ETH", "SOL"]
    exchanges = ["binance", "bybit", "okx"]
    base_prices = {"BTC": 68000, "ETH": 2100, "SOL": 95}

    # Track which exchange each asset uses (consistent per pair)
    asset_exchange = {"BTC": "binance", "ETH": "bybit", "SOL": "okx"}

    # Generate opportunities over 90 days
    for day_offset in range(90):
        ts = start + timedelta(days=day_offset, hours=random.uniform(8, 16))
        batch: List[Opportunity] = []

        for asset in assets:
            exchange = asset_exchange[asset]
            base = base_prices[asset]

            # Price with drift and mean reversion
            drift = random.gauss(0, 0.015)
            price = base * (1 + drift)

            # Basis follows a pattern with some randomness
            cycle = (day_offset % 10) / 10.0
            noise = random.gauss(0, 0.005)  # random noise
            if cycle < 0.3:
                premium = random.uniform(0.012, 0.028) + noise
            elif cycle < 0.5:
                premium = random.uniform(0.010, 0.025) + noise
            elif cycle < 0.8:
                premium = random.uniform(0.002, 0.006) + noise
            else:
                premium = random.uniform(0.010, 0.035) + noise
            premium = max(premium, 0.0005)  # floor at 5 bps

            opp = _make_demo_opportunity(
                exchange=exchange,
                asset=asset,
                spot_price=price,
                futures_premium_pct=premium,
                ts=ts,
                expiry=expiry,
                fee_rate=settings.get_fee_for_exchange(exchange),
                slippage=settings.filters.slippage_assumption,
            )
            batch.append(opp)

        # Process batch: exits first, then entries
        engine.check_exits(batch, as_of=ts)
        for opp in batch:
            engine.process_opportunity(opp)

    # Force close remaining positions at end
    final_ts = start + timedelta(days=91)
    final_batch = []
    for asset in assets:
        exchange = asset_exchange[asset]
        price = base_prices[asset]
        opp = _make_demo_opportunity(
            exchange=exchange,
            asset=asset,
            spot_price=price,
            futures_premium_pct=0.001,
            ts=final_ts,
            expiry=expiry,
        )
        final_batch.append(opp)
    engine.check_exits(final_batch, as_of=final_ts)

    return engine.get_state_for_dashboard()

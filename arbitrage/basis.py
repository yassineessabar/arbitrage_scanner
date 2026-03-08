"""
arbitrage/basis.py — Core basis calculations for the arbitrage engine.

Computes all basis metrics for each SpotFuturesPair:
  - Mid-based: basis_abs, basis_pct, annualized_basis
  - Executable (bid/ask aware): CC and RCC
  - Cost-adjusted: net edge after fees + slippage
  - Signal classification
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog

from normalization.schema import (
    BasisResult,
    ContractType,
    Signal,
    SpotFuturesPair,
)
from arbitrage.carry import annualize

logger = structlog.get_logger(__name__)


def compute_basis(
    pair: SpotFuturesPair,
    fee_rate: float = 0.0005,
    slippage: float = 0.0003,
    min_net_edge: float = 0.0,
) -> BasisResult:
    """Compute all basis metrics for a spot/futures pair.

    Args:
        pair: SpotFuturesPair with spot and futures quotes.
        fee_rate: Taker fee per leg (default 0.05%).
        slippage: Assumed slippage per leg (default 0.03%).
        min_net_edge: Minimum net edge threshold for signal (default 0).

    Returns:
        BasisResult with all computed metrics and trade signal.
    """
    spot = pair.spot
    futures = pair.futures
    now = datetime.now(timezone.utc)

    # ── Mid-Based Metrics ──
    basis_abs = futures.mid - spot.mid
    basis_pct = basis_abs / spot.mid if spot.mid > 0 else 0.0

    # Days to expiry for annualization
    dte: Optional[float] = futures.days_to_expiry
    is_dated = futures.contract_type == ContractType.DATED_FUTURE

    annualized_basis = annualize(basis_pct, dte) if is_dated else None

    # ── Executable Metrics (bid/ask aware) ──
    # Cash & Carry: sell futures at bid, buy spot at ask
    executable_basis_cc = futures.bid - spot.ask
    # Reverse Cash & Carry: sell spot at bid, buy futures at ask
    executable_basis_rcc = spot.bid - futures.ask

    gross_edge_cc_pct = executable_basis_cc / spot.ask if spot.ask > 0 else 0.0
    gross_edge_rcc_pct = executable_basis_rcc / spot.bid if spot.bid > 0 else 0.0

    # ── Net Edge (after costs) ──
    total_cost = (2 * fee_rate) + (2 * slippage)
    net_edge_cc_pct = gross_edge_cc_pct - total_cost
    net_edge_rcc_pct = gross_edge_rcc_pct - total_cost

    # Annualize net edges (dated only)
    annualized_net_edge_cc = annualize(net_edge_cc_pct, dte) if is_dated else None
    annualized_net_edge_rcc = annualize(net_edge_rcc_pct, dte) if is_dated else None

    # ── Signal Classification ──
    signal = _classify_signal(
        basis_abs=basis_abs,
        net_edge_cc=net_edge_cc_pct,
        net_edge_rcc=net_edge_rcc_pct,
        gross_edge_cc=gross_edge_cc_pct,
        gross_edge_rcc=gross_edge_rcc_pct,
        min_net_edge=min_net_edge,
        is_perpetual=futures.contract_type == ContractType.PERPETUAL,
    )

    # ── Spread (futures side, for scoring) ──
    futures_spread_pct = futures.spread_pct

    # ── Combined volume ──
    volume = None
    if spot.volume_24h is not None and futures.volume_24h is not None:
        volume = min(spot.volume_24h, futures.volume_24h)
    elif spot.volume_24h is not None:
        volume = spot.volume_24h
    elif futures.volume_24h is not None:
        volume = futures.volume_24h

    return BasisResult(
        exchange=pair.exchange,
        asset=pair.asset,
        spot_symbol=spot.internal_symbol,
        futures_symbol=futures.internal_symbol,
        contract_type=futures.contract_type,
        expiry=futures.expiry,
        spot_bid=spot.bid,
        spot_ask=spot.ask,
        spot_mid=spot.mid,
        futures_bid=futures.bid,
        futures_ask=futures.ask,
        futures_mid=futures.mid,
        basis_abs=basis_abs,
        basis_pct=basis_pct,
        annualized_basis=annualized_basis,
        executable_basis_cc=executable_basis_cc,
        executable_basis_rcc=executable_basis_rcc,
        gross_edge_cc_pct=gross_edge_cc_pct,
        gross_edge_rcc_pct=gross_edge_rcc_pct,
        net_edge_cc_pct=net_edge_cc_pct,
        net_edge_rcc_pct=net_edge_rcc_pct,
        annualized_net_edge_cc=annualized_net_edge_cc,
        annualized_net_edge_rcc=annualized_net_edge_rcc,
        signal=signal,
        timestamp=now,
        volume_usd_24h=volume,
        spread_pct=futures_spread_pct,
    )


def _classify_signal(
    basis_abs: float,
    net_edge_cc: float,
    net_edge_rcc: float,
    gross_edge_cc: float = 0.0,
    gross_edge_rcc: float = 0.0,
    min_net_edge: float = 0.0,
    is_perpetual: bool = False,
) -> Signal:
    """Classify the trade signal based on basis direction and edge.

    For perpetual futures, uses gross edge (before costs) since perp basis
    is inherently small. For dated futures, uses net edge after costs.

    Args:
        basis_abs: Absolute basis (futures_mid - spot_mid).
        net_edge_cc: Net edge for cash & carry after costs.
        net_edge_rcc: Net edge for reverse cash & carry after costs.
        gross_edge_cc: Gross edge for cash & carry before costs.
        gross_edge_rcc: Gross edge for reverse cash & carry before costs.
        min_net_edge: Minimum threshold for a tradeable signal.
        is_perpetual: Whether this is a perpetual futures contract.

    Returns:
        Signal enum value.
    """
    if is_perpetual:
        # For perps: use gross edge (basis direction is the signal)
        if basis_abs > 0 and gross_edge_cc > 0:
            return Signal.CASH_AND_CARRY
        if basis_abs < 0 and gross_edge_rcc > 0:
            return Signal.REVERSE_CC
    else:
        # For dated futures: require positive net edge after costs
        if basis_abs > 0 and net_edge_cc > min_net_edge:
            return Signal.CASH_AND_CARRY
        if basis_abs < 0 and net_edge_rcc > min_net_edge:
            return Signal.REVERSE_CC

    # Basis exists but edge is marginal
    if abs(basis_abs) > 0 and (net_edge_cc > -0.002 or net_edge_rcc > -0.002):
        return Signal.WATCH

    return Signal.NO_TRADE

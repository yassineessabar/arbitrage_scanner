"""
simulation/cross_exchange.py — Cross-exchange arbitrage simulation engine.

Detects price dislocations for the same asset across different exchanges,
opens simulated trades when the spread exceeds fees + slippage, and closes
them when the spread converges.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from typing import Dict, List, Optional

import structlog
from pydantic import BaseModel, Field

from config.settings import Settings
from normalization.schema import ContractType, InstrumentQuote
from simulation.models import (
    EquitySnapshot,
    ExitReason,
    SimulatedTrade,
    SimulationResult,
)

logger = structlog.get_logger(__name__)


class CrossExchangeOpportunity(BaseModel):
    """A detected cross-exchange price dislocation."""

    asset: str = Field(..., description="Base asset (BTC, ETH, etc.)")
    contract_type: ContractType = Field(..., description="SPOT or PERPETUAL")
    buy_exchange: str = Field(..., description="Exchange to buy on (cheaper)")
    sell_exchange: str = Field(..., description="Exchange to sell on (more expensive)")
    buy_ask: float = Field(..., gt=0, description="Ask price on buy exchange")
    sell_bid: float = Field(..., gt=0, description="Bid price on sell exchange")
    spread_pct: float = Field(..., description="Gross spread: (sell_bid - buy_ask) / buy_ask")
    net_edge_pct: float = Field(..., description="Net edge after all costs")
    total_cost_pct: float = Field(..., description="Total round-trip cost as pct")
    buy_volume_24h: float = Field(default=0, ge=0)
    sell_volume_24h: float = Field(default=0, ge=0)
    timestamp: datetime
    pair_id: str = Field(..., description="e.g. BTC_SPOT_binance_okx")


class CrossExchangeEngine:
    """Cross-exchange arbitrage simulator.

    Scans quotes across exchanges for the same asset, detects spreads
    that exceed costs, and simulates opening/closing trades.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cfg = settings.cross_exchange
        self._capital = self._cfg.initial_capital
        self._equity = self._cfg.initial_capital
        self._open_positions: Dict[str, SimulatedTrade] = {}
        self._closed_trades: List[SimulatedTrade] = []
        self._equity_curve: List[EquitySnapshot] = [
            EquitySnapshot(
                timestamp=datetime.now(timezone.utc),
                equity=self._equity,
            )
        ]
        self._latest_rejected: List[CrossExchangeOpportunity] = []

    @property
    def open_position_count(self) -> int:
        return len(self._open_positions)

    @property
    def open_positions(self) -> List[SimulatedTrade]:
        return list(self._open_positions.values())

    def scan_quotes(
        self,
        quotes: List[InstrumentQuote],
        as_of: Optional[datetime] = None,
    ) -> List[CrossExchangeOpportunity]:
        """Find cross-exchange arbitrage opportunities from a list of quotes.

        Groups quotes by (asset, contract_type), then for each pair of exchanges
        computes the spread and returns opportunities where net_edge > threshold.
        """
        qualified, _ = self._scan_all(quotes, as_of)
        return qualified

    def scan_all_spreads(
        self,
        quotes: List[InstrumentQuote],
        as_of: Optional[datetime] = None,
    ) -> tuple[List[CrossExchangeOpportunity], List[CrossExchangeOpportunity]]:
        """Scan all cross-exchange spreads, returning (qualified, rejected).

        Returns:
            Tuple of (qualified opportunities, rejected opportunities).
            Rejected = positive spread but below cost threshold.
        """
        return self._scan_all(quotes, as_of)

    def _scan_all(
        self,
        quotes: List[InstrumentQuote],
        as_of: Optional[datetime] = None,
    ) -> tuple[List[CrossExchangeOpportunity], List[CrossExchangeOpportunity]]:
        ts = as_of or datetime.now(timezone.utc)

        groups: Dict[tuple, List[InstrumentQuote]] = defaultdict(list)
        for q in quotes:
            if q.contract_type == ContractType.SPOT:
                groups[(q.asset, q.contract_type)].append(q)

        qualified: List[CrossExchangeOpportunity] = []
        rejected: List[CrossExchangeOpportunity] = []

        for (asset, ctype), exchange_quotes in groups.items():
            if len(exchange_quotes) < 2:
                continue

            for q_a, q_b in combinations(exchange_quotes, 2):
                for buy_q, sell_q in [(q_a, q_b), (q_b, q_a)]:
                    opp = self._evaluate_pair(buy_q, sell_q, asset, ctype, ts,
                                              include_rejected=True)
                    if opp is not None:
                        if opp.net_edge_pct >= self._cfg.min_edge_to_trade:
                            qualified.append(opp)
                        else:
                            rejected.append(opp)

        # Sort rejected by net_edge descending (closest to qualifying first)
        rejected.sort(key=lambda o: o.net_edge_pct, reverse=True)

        return qualified, rejected

    def _evaluate_pair(
        self,
        buy_quote: InstrumentQuote,
        sell_quote: InstrumentQuote,
        asset: str,
        ctype: ContractType,
        ts: datetime,
        include_rejected: bool = False,
    ) -> Optional[CrossExchangeOpportunity]:
        """Evaluate buying on one exchange and selling on another."""
        buy_ask = buy_quote.ask
        sell_bid = sell_quote.bid

        if sell_bid <= buy_ask:
            return None  # No positive spread

        spread_pct = (sell_bid - buy_ask) / buy_ask

        fee_buy = self._settings.get_fee_for_exchange(buy_quote.exchange)
        fee_sell = self._settings.get_fee_for_exchange(sell_quote.exchange)
        total_cost = fee_buy + fee_sell + 2 * self._cfg.slippage_per_side

        net_edge = spread_pct - total_cost

        if not include_rejected and net_edge < self._cfg.min_edge_to_trade:
            return None

        pair_id = f"{asset}_{ctype.value}_{buy_quote.exchange}_{sell_quote.exchange}"

        return CrossExchangeOpportunity(
            asset=asset,
            contract_type=ctype,
            buy_exchange=buy_quote.exchange,
            sell_exchange=sell_quote.exchange,
            buy_ask=buy_ask,
            sell_bid=sell_bid,
            spread_pct=spread_pct,
            net_edge_pct=net_edge,
            total_cost_pct=total_cost,
            buy_volume_24h=buy_quote.volume_24h or 0,
            sell_volume_24h=sell_quote.volume_24h or 0,
            timestamp=ts,
            pair_id=pair_id,
        )

    def process_opportunity(
        self, opp: CrossExchangeOpportunity
    ) -> Optional[SimulatedTrade]:
        """Open a simulated trade if the opportunity qualifies.

        Entry criteria:
          1. net_edge_pct >= min_edge_to_trade
          2. open positions < max_open_positions
          3. no existing position for same pair_id
        """
        if opp.net_edge_pct < self._cfg.min_edge_to_trade:
            return None

        if self.open_position_count >= self._cfg.max_open_positions:
            return None

        if opp.pair_id in self._open_positions:
            return None

        position_size = self._equity * self._cfg.position_size_pct

        # Entry costs (one leg on each exchange)
        fee_buy = self._settings.get_fee_for_exchange(opp.buy_exchange)
        fee_sell = self._settings.get_fee_for_exchange(opp.sell_exchange)
        entry_fees = (fee_buy + fee_sell) * position_size
        entry_slippage = 2 * self._cfg.slippage_per_side * position_size

        trade = SimulatedTrade(
            trade_id=str(uuid.uuid4())[:8],
            exchange=f"{opp.buy_exchange}/{opp.sell_exchange}",
            asset=opp.asset,
            signal="CROSS_EXCHANGE",
            pair_id=opp.pair_id,
            entry_time=opp.timestamp,
            entry_spot=opp.buy_ask,       # buy price
            entry_futures=opp.sell_bid,    # sell price
            entry_basis_pct=opp.spread_pct,
            position_size_usd=position_size,
            fees_paid=entry_fees,
            slippage_cost=entry_slippage,
            score_at_entry=opp.net_edge_pct * 10000,  # edge in bps as "score"
        )

        self._open_positions[opp.pair_id] = trade

        logger.info(
            "cross_exchange_trade_opened",
            trade_id=trade.trade_id,
            asset=opp.asset,
            buy_exchange=opp.buy_exchange,
            sell_exchange=opp.sell_exchange,
            spread_pct=f"{opp.spread_pct:.4%}",
            net_edge=f"{opp.net_edge_pct:.4%}",
            position_size=f"${position_size:,.0f}",
        )

        return trade

    def check_exits(
        self,
        current_opps: List[CrossExchangeOpportunity],
        as_of: Optional[datetime] = None,
    ) -> List[SimulatedTrade]:
        """Check all open positions for exit conditions.

        Exit conditions:
          1. CONVERGENCE: current spread < exit_convergence_threshold
          2. MAX_HOLD: held > max_hold_minutes
        """
        now = as_of or datetime.now(timezone.utc)
        closed: List[SimulatedTrade] = []

        # Build lookup: pair_id → current opportunity
        opp_map: Dict[str, CrossExchangeOpportunity] = {}
        for opp in current_opps:
            opp_map[opp.pair_id] = opp

        pairs_to_close: List[str] = []

        for pair_id, trade in self._open_positions.items():
            exit_reason: Optional[ExitReason] = None
            exit_spread_pct: Optional[float] = None
            exit_buy_price: Optional[float] = None
            exit_sell_price: Optional[float] = None

            current_opp = opp_map.get(pair_id)

            if current_opp is not None:
                # Current spread for the same direction
                exit_spread_pct = current_opp.spread_pct
                exit_buy_price = current_opp.buy_ask
                exit_sell_price = current_opp.sell_bid

                # Check convergence (spread narrowed enough to take profit)
                if exit_spread_pct < self._cfg.exit_convergence_threshold:
                    exit_reason = ExitReason.CONVERGENCE
            else:
                # No matching opportunity means spread has disappeared / reversed
                # Treat as convergence with zero spread
                exit_spread_pct = 0.0
                # Use entry prices as approximation (conservative — no P&L from price)
                exit_buy_price = trade.entry_spot
                exit_sell_price = trade.entry_futures
                exit_reason = ExitReason.CONVERGENCE

            # Check max hold
            hold_seconds = (now - trade.entry_time).total_seconds()
            hold_minutes = hold_seconds / 60.0
            if hold_minutes > self._cfg.max_hold_minutes:
                exit_reason = ExitReason.MAX_HOLD
                if exit_buy_price is None:
                    exit_buy_price = trade.entry_spot
                    exit_sell_price = trade.entry_futures
                    exit_spread_pct = trade.entry_basis_pct

            if exit_reason is not None and exit_buy_price is not None:
                closed_trade = self._close_trade(
                    trade, exit_buy_price, exit_sell_price,
                    exit_spread_pct, exit_reason, now,
                )
                closed.append(closed_trade)
                pairs_to_close.append(pair_id)

        for pair_id in pairs_to_close:
            del self._open_positions[pair_id]

        if closed:
            self._equity_curve.append(
                EquitySnapshot(timestamp=now, equity=self._equity)
            )

        return closed

    def _close_trade(
        self,
        trade: SimulatedTrade,
        exit_buy_price: float,
        exit_sell_price: float,
        exit_spread_pct: float,
        reason: ExitReason,
        now: datetime,
    ) -> SimulatedTrade:
        """Close a trade, compute P&L, and update equity."""
        # Parse exchanges from "buy_exchange/sell_exchange"
        exchanges = trade.exchange.split("/")
        fee_buy = self._settings.get_fee_for_exchange(exchanges[0])
        fee_sell = self._settings.get_fee_for_exchange(exchanges[1])
        pos_size = trade.position_size_usd

        # Exit costs
        exit_fees = (fee_buy + fee_sell) * pos_size
        exit_slippage = 2 * self._cfg.slippage_per_side * pos_size

        # Gross P&L: profit from spread convergence
        # Entry: bought at buy_ask, sold at sell_bid → spread = entry_basis_pct
        # Exit: need to reverse — sell what we bought, buy what we sold
        # Profit = (entry_spread - exit_spread) × position_size
        basis_change = trade.entry_basis_pct - exit_spread_pct
        gross_pnl = basis_change * pos_size

        # Total costs
        total_fees = trade.fees_paid + exit_fees
        total_slippage = trade.slippage_cost + exit_slippage
        net_pnl = gross_pnl - total_fees - total_slippage

        self._equity += net_pnl

        closed = trade.model_copy(
            update={
                "exit_time": now,
                "exit_spot": exit_buy_price,
                "exit_futures": exit_sell_price,
                "exit_basis_pct": exit_spread_pct,
                "gross_pnl": gross_pnl,
                "fees_paid": total_fees,
                "slippage_cost": total_slippage,
                "net_pnl": net_pnl,
                "exit_reason": reason,
            }
        )

        self._closed_trades.append(closed)

        logger.info(
            "cross_exchange_trade_closed",
            trade_id=closed.trade_id,
            reason=reason.value,
            gross_pnl=f"${gross_pnl:,.2f}",
            net_pnl=f"${net_pnl:,.2f}",
            equity=f"${self._equity:,.2f}",
        )

        return closed

    def get_result(self) -> SimulationResult:
        """Compute and return aggregate simulation results."""
        closed = self._closed_trades

        total_net_pnl = sum(t.net_pnl for t in closed)
        total_fees = sum(t.fees_paid for t in closed)
        total_slippage = sum(t.slippage_cost for t in closed)

        winning = [t for t in closed if t.net_pnl > 0]
        losing = [t for t in closed if t.net_pnl <= 0]

        n_closed = len(closed)
        win_rate = len(winning) / n_closed if n_closed > 0 else 0.0
        avg_hold = sum(t.hold_days for t in closed) / n_closed if n_closed > 0 else 0.0

        max_dd = self._compute_max_drawdown()
        sharpe = self._compute_sharpe()

        gross_wins = sum(t.net_pnl for t in winning)
        gross_losses = abs(sum(t.net_pnl for t in losing))
        pf = gross_wins / gross_losses if gross_losses > 0 else (
            float("inf") if gross_wins > 0 else 0.0
        )

        return SimulationResult(
            trades=self._closed_trades + list(self._open_positions.values()),
            equity_curve=self._equity_curve,
            initial_capital=self._cfg.initial_capital,
            total_net_pnl=total_net_pnl,
            total_fees=total_fees,
            total_slippage=total_slippage,
            total_trades=n_closed,
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=win_rate,
            avg_hold_days=avg_hold,
            max_drawdown_pct=max_dd,
            sharpe_ratio=sharpe,
            profit_factor=pf,
        )

    def _compute_max_drawdown(self) -> float:
        if len(self._equity_curve) < 2:
            return 0.0
        peak = self._equity_curve[0].equity
        max_dd = 0.0
        for snap in self._equity_curve:
            if snap.equity > peak:
                peak = snap.equity
            dd = (peak - snap.equity) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
        return max_dd

    def _compute_sharpe(self) -> float:
        if len(self._equity_curve) < 3:
            return 0.0
        returns = []
        for i in range(1, len(self._equity_curve)):
            prev = self._equity_curve[i - 1].equity
            curr = self._equity_curve[i].equity
            if prev > 0:
                returns.append((curr - prev) / prev)
        if not returns or len(returns) < 2:
            return 0.0
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(variance) if variance > 0 else 0.0
        if std_r == 0:
            return 0.0
        return (mean_r / std_r) * math.sqrt(252)

    def update_rejected(self, rejected: List[CrossExchangeOpportunity]) -> None:
        """Store latest rejected (sub-threshold) opportunities for display."""
        self._latest_rejected = rejected

    def get_state_for_dashboard(self) -> dict:
        """Export current simulation state for dashboard rendering."""
        result = self.get_result()
        return {
            "enabled": True,
            "equity": self._equity,
            "initial_capital": self._cfg.initial_capital,
            "total_net_pnl": result.total_net_pnl,
            "total_return_pct": result.total_return_pct,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": result.win_rate,
            "avg_hold_days": result.avg_hold_days,
            "max_drawdown_pct": result.max_drawdown_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "profit_factor": result.profit_factor,
            "total_fees": result.total_fees,
            "total_slippage": result.total_slippage,
            "open_positions": [
                t.model_dump(mode="json") for t in self.open_positions
            ],
            "closed_trades": [
                t.model_dump(mode="json") for t in self._closed_trades[-50:]
            ],
            "equity_curve": [
                {"timestamp": s.timestamp.isoformat(), "equity": s.equity}
                for s in self._equity_curve
            ],
            "rejected_spreads": [
                {
                    "asset": r.asset,
                    "buy_exchange": r.buy_exchange,
                    "sell_exchange": r.sell_exchange,
                    "buy_ask": r.buy_ask,
                    "sell_bid": r.sell_bid,
                    "spread_pct": r.spread_pct,
                    "total_cost_pct": r.total_cost_pct,
                    "net_edge_pct": r.net_edge_pct,
                    "timestamp": r.timestamp.isoformat(),
                }
                for r in self._latest_rejected[:20]
            ],
        }

"""
simulation/engine.py — Core P&L simulation engine.

Processes arbitrage opportunities, opens simulated trades on qualifying signals,
tracks open positions, checks exit conditions, and computes aggregate statistics.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

import structlog

from config.settings import Settings
from normalization.schema import Opportunity, Signal
from simulation.models import (
    EquitySnapshot,
    ExitReason,
    SimulatedTrade,
    SimulationResult,
)

logger = structlog.get_logger(__name__)


class SimulationEngine:
    """Position-level P&L simulator for arbitrage opportunities.

    Tracks open positions, applies entry/exit logic with realistic costs,
    and maintains an equity curve.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sim_cfg = settings.simulation
        self._capital = self._sim_cfg.initial_capital
        self._equity = self._sim_cfg.initial_capital
        self._open_positions: Dict[str, SimulatedTrade] = {}  # pair_id → trade
        self._closed_trades: List[SimulatedTrade] = []
        self._equity_curve: List[EquitySnapshot] = [
            EquitySnapshot(
                timestamp=datetime.now(timezone.utc),
                equity=self._equity,
            )
        ]

    @property
    def open_position_count(self) -> int:
        return len(self._open_positions)

    @property
    def open_positions(self) -> List[SimulatedTrade]:
        return list(self._open_positions.values())

    def process_opportunity(self, opp: Opportunity) -> Optional[SimulatedTrade]:
        """Evaluate an opportunity and open a simulated trade if it qualifies.

        Entry criteria:
          1. passed_filters is True
          2. signal is CASH_AND_CARRY or REVERSE_CC
          3. score >= min_score_to_trade
          4. open positions < max_open_positions
          5. no existing position for same pair_id

        Returns:
            The opened SimulatedTrade, or None if criteria not met.
        """
        # Check signal
        if opp.signal not in (Signal.CASH_AND_CARRY, Signal.REVERSE_CC):
            return None

        # Check filters
        if not opp.passed_filters:
            return None

        # Check score
        if opp.score < self._sim_cfg.min_score_to_trade:
            return None

        # Check position limits
        if self.open_position_count >= self._sim_cfg.max_open_positions:
            return None

        # Check duplicate
        pair_id = opp.pair.pair_id
        if pair_id in self._open_positions:
            return None

        # Calculate position size
        position_size = self._equity * self._sim_cfg.position_size_pct

        # Get costs
        fee_rate = self._settings.get_fee_for_exchange(opp.pair.exchange)
        slippage = self._settings.filters.slippage_assumption

        # Entry prices (executable — using bid/ask)
        br = opp.basis_result
        if opp.signal == Signal.CASH_AND_CARRY:
            entry_spot = br.spot_ask      # buy spot at ask
            entry_futures = br.futures_bid  # sell futures at bid
        else:  # REVERSE_CC
            entry_spot = br.spot_bid       # sell spot at bid
            entry_futures = br.futures_ask  # buy futures at ask

        entry_basis_pct = (entry_futures - entry_spot) / entry_spot

        # Entry costs (2 legs: spot + futures)
        entry_fees = 2 * fee_rate * position_size
        entry_slippage = 2 * slippage * position_size

        trade = SimulatedTrade(
            trade_id=str(uuid.uuid4())[:8],
            exchange=opp.pair.exchange,
            asset=opp.pair.asset,
            signal=opp.signal.value,
            pair_id=pair_id,
            entry_time=opp.ranked_at,
            entry_spot=entry_spot,
            entry_futures=entry_futures,
            entry_basis_pct=entry_basis_pct,
            position_size_usd=position_size,
            fees_paid=entry_fees,
            slippage_cost=entry_slippage,
            score_at_entry=opp.score,
        )

        self._open_positions[pair_id] = trade

        logger.info(
            "sim_trade_opened",
            trade_id=trade.trade_id,
            exchange=trade.exchange,
            asset=trade.asset,
            signal=trade.signal,
            entry_basis_pct=f"{entry_basis_pct:.4%}",
            position_size=f"${position_size:,.0f}",
        )

        return trade

    def check_exits(
        self,
        current_opportunities: List[Opportunity],
        as_of: Optional[datetime] = None,
    ) -> List[SimulatedTrade]:
        """Check all open positions for exit conditions.

        Exit conditions:
          1. CONVERGENCE: current |basis_pct| < exit_basis_convergence_pct
          2. EXPIRY: days_to_expiry <= 1
          3. MAX_HOLD: hold days > max_hold_days

        Args:
            current_opportunities: Latest scanned opportunities (for current prices).
            as_of: Timestamp to use for hold time calculation (defaults to now).

        Returns:
            List of trades that were closed this cycle.
        """
        now = as_of or datetime.now(timezone.utc)
        closed: List[SimulatedTrade] = []

        # Build lookup: pair_id → current opportunity
        opp_map: Dict[str, Opportunity] = {}
        for opp in current_opportunities:
            opp_map[opp.pair.pair_id] = opp

        pairs_to_close: List[str] = []

        for pair_id, trade in self._open_positions.items():
            exit_reason: Optional[ExitReason] = None
            exit_spot: Optional[float] = None
            exit_futures: Optional[float] = None
            exit_basis_pct: Optional[float] = None

            # Get current prices from matching opportunity
            current_opp = opp_map.get(pair_id)

            if current_opp is not None:
                br = current_opp.basis_result
                exit_basis_pct = br.basis_pct

                # Set exit prices based on original signal direction
                if trade.signal == Signal.CASH_AND_CARRY.value:
                    exit_spot = br.spot_bid      # sell spot at bid
                    exit_futures = br.futures_ask  # buy back futures at ask
                else:
                    exit_spot = br.spot_ask       # buy back spot at ask
                    exit_futures = br.futures_bid  # sell back futures at bid

                # Check convergence
                if abs(exit_basis_pct) < self._sim_cfg.exit_basis_convergence_pct:
                    exit_reason = ExitReason.CONVERGENCE

                # Check expiry
                dte = br.days_to_expiry
                if dte is not None and dte <= 1:
                    exit_reason = ExitReason.EXPIRY

            # Check max hold (regardless of whether we have current prices)
            hold_seconds = (now - trade.entry_time).total_seconds()
            hold_days = hold_seconds / 86400.0
            if hold_days > self._sim_cfg.max_hold_days:
                exit_reason = ExitReason.MAX_HOLD
                # If no current prices, use entry prices (worst case: no P&L)
                if exit_spot is None:
                    exit_spot = trade.entry_spot
                    exit_futures = trade.entry_futures
                    exit_basis_pct = trade.entry_basis_pct

            if exit_reason is not None and exit_spot is not None:
                closed_trade = self._close_trade(
                    trade, exit_spot, exit_futures, exit_basis_pct, exit_reason, now
                )
                closed.append(closed_trade)
                pairs_to_close.append(pair_id)

        # Remove closed positions
        for pair_id in pairs_to_close:
            del self._open_positions[pair_id]

        # Update equity curve
        if closed:
            self._equity_curve.append(
                EquitySnapshot(timestamp=now, equity=self._equity)
            )

        return closed

    def _close_trade(
        self,
        trade: SimulatedTrade,
        exit_spot: float,
        exit_futures: float,
        exit_basis_pct: float,
        reason: ExitReason,
        now: datetime,
    ) -> SimulatedTrade:
        """Close a trade, compute P&L, and update equity."""
        fee_rate = self._settings.get_fee_for_exchange(trade.exchange)
        slippage = self._settings.filters.slippage_assumption
        pos_size = trade.position_size_usd

        # Exit costs
        exit_fees = 2 * fee_rate * pos_size
        exit_slippage = 2 * slippage * pos_size

        # Gross P&L from basis convergence
        # CC: profit = (entry_basis - exit_basis) * position_size / entry_spot
        # RCC: profit = (exit_basis - entry_basis) * position_size / entry_spot
        basis_change = trade.entry_basis_pct - exit_basis_pct
        if trade.signal == Signal.REVERSE_CC.value:
            basis_change = -basis_change

        gross_pnl = basis_change * pos_size

        # Total costs
        total_fees = trade.fees_paid + exit_fees
        total_slippage = trade.slippage_cost + exit_slippage
        net_pnl = gross_pnl - total_fees - total_slippage

        # Update equity
        self._equity += net_pnl

        # Create closed trade record
        closed = trade.model_copy(
            update={
                "exit_time": now,
                "exit_spot": exit_spot,
                "exit_futures": exit_futures,
                "exit_basis_pct": exit_basis_pct,
                "gross_pnl": gross_pnl,
                "fees_paid": total_fees,
                "slippage_cost": total_slippage,
                "net_pnl": net_pnl,
                "exit_reason": reason,
            }
        )

        self._closed_trades.append(closed)

        logger.info(
            "sim_trade_closed",
            trade_id=closed.trade_id,
            reason=reason.value,
            gross_pnl=f"${gross_pnl:,.2f}",
            net_pnl=f"${net_pnl:,.2f}",
            equity=f"${self._equity:,.2f}",
        )

        return closed

    def get_result(self) -> SimulationResult:
        """Compute and return aggregate simulation results."""
        all_trades = self._closed_trades + list(self._open_positions.values())
        closed = self._closed_trades

        total_net_pnl = sum(t.net_pnl for t in closed)
        total_fees = sum(t.fees_paid for t in closed)
        total_slippage = sum(t.slippage_cost for t in closed)

        winning = [t for t in closed if t.net_pnl > 0]
        losing = [t for t in closed if t.net_pnl <= 0]

        n_closed = len(closed)
        win_rate = len(winning) / n_closed if n_closed > 0 else 0.0
        avg_hold = sum(t.hold_days for t in closed) / n_closed if n_closed > 0 else 0.0

        # Max drawdown from equity curve
        max_dd = self._compute_max_drawdown()

        # Sharpe ratio (annualized, assuming daily returns)
        sharpe = self._compute_sharpe()

        # Profit factor
        gross_wins = sum(t.net_pnl for t in winning)
        gross_losses = abs(sum(t.net_pnl for t in losing))
        pf = gross_wins / gross_losses if gross_losses > 0 else float("inf") if gross_wins > 0 else 0.0

        return SimulationResult(
            trades=all_trades,
            equity_curve=self._equity_curve,
            initial_capital=self._sim_cfg.initial_capital,
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
        """Compute max drawdown from equity curve as a percentage."""
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
        """Compute annualized Sharpe ratio from equity curve."""
        if len(self._equity_curve) < 3:
            return 0.0

        returns = []
        for i in range(1, len(self._equity_curve)):
            prev = self._equity_curve[i - 1].equity
            curr = self._equity_curve[i].equity
            if prev > 0:
                returns.append((curr - prev) / prev)

        if not returns:
            return 0.0

        mean_r = sum(returns) / len(returns)
        if len(returns) < 2:
            return 0.0

        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(variance) if variance > 0 else 0.0

        if std_r == 0:
            return 0.0

        # Annualize assuming each equity snapshot is ~1 scan cycle
        return (mean_r / std_r) * math.sqrt(252)

    def get_state_for_dashboard(self) -> dict:
        """Export current simulation state for dashboard rendering."""
        result = self.get_result()
        return {
            "enabled": True,
            "equity": self._equity,
            "initial_capital": self._sim_cfg.initial_capital,
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
                t.model_dump(mode="json") for t in self._closed_trades[-50:]  # last 50
            ],
            "equity_curve": [
                {"timestamp": s.timestamp.isoformat(), "equity": s.equity}
                for s in self._equity_curve
            ],
        }

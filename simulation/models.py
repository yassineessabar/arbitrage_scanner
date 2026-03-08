"""
simulation/models.py — Data models for the P&L simulation module.

Models:
    - ExitReason       : Enum for why a trade was closed
    - SimulatedTrade   : A single simulated arbitrage trade
    - EquitySnapshot   : Point-in-time equity value
    - SimulationResult : Aggregate results of a simulation run
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, computed_field


class ExitReason(str, Enum):
    """Reason a simulated trade was closed."""

    CONVERGENCE = "CONVERGENCE"  # Basis converged below threshold
    EXPIRY = "EXPIRY"            # Futures contract expired
    MAX_HOLD = "MAX_HOLD"        # Held too long, force close
    STILL_OPEN = "STILL_OPEN"    # Position not yet closed


class SimulatedTrade(BaseModel):
    """A single simulated arbitrage trade with full P&L breakdown."""

    trade_id: str = Field(..., description="Unique trade identifier")
    exchange: str = Field(..., description="Exchange identifier")
    asset: str = Field(..., description="Base asset (BTC, ETH, etc.)")
    signal: str = Field(..., description="Trade signal: LONG SPOT / SHORT FUT or reverse")
    pair_id: str = Field(..., description="Source pair identifier")

    # Timing
    entry_time: datetime = Field(..., description="When the position was opened")
    exit_time: Optional[datetime] = Field(default=None, description="When the position was closed")

    # Entry prices (executable)
    entry_spot: float = Field(..., gt=0, description="Spot entry price")
    entry_futures: float = Field(..., gt=0, description="Futures entry price")
    entry_basis_pct: float = Field(..., description="Basis at entry as pct of spot")

    # Exit prices
    exit_spot: Optional[float] = Field(default=None, description="Spot exit price")
    exit_futures: Optional[float] = Field(default=None, description="Futures exit price")
    exit_basis_pct: Optional[float] = Field(default=None, description="Basis at exit as pct")

    # Sizing
    position_size_usd: float = Field(..., gt=0, description="Notional position size in USD")

    # P&L breakdown
    gross_pnl: float = Field(default=0.0, description="Gross P&L before costs")
    fees_paid: float = Field(default=0.0, ge=0, description="Total fees paid (entry + exit)")
    slippage_cost: float = Field(default=0.0, ge=0, description="Total slippage cost")
    net_pnl: float = Field(default=0.0, description="Net P&L after all costs")

    # Metadata
    exit_reason: ExitReason = Field(default=ExitReason.STILL_OPEN)
    score_at_entry: float = Field(default=0.0, description="Opportunity score at entry")

    @computed_field
    @property
    def net_pnl_pct(self) -> float:
        """Net P&L as percentage of position size."""
        if self.position_size_usd > 0:
            return self.net_pnl / self.position_size_usd
        return 0.0

    @computed_field
    @property
    def hold_days(self) -> float:
        """Days the position was/is held."""
        if self.exit_time is None:
            return 0.0
        delta = self.exit_time - self.entry_time
        return delta.total_seconds() / 86400.0

    @property
    def is_open(self) -> bool:
        return self.exit_reason == ExitReason.STILL_OPEN


class EquitySnapshot(BaseModel):
    """Point-in-time equity value for the equity curve."""

    timestamp: datetime
    equity: float


class SimulationResult(BaseModel):
    """Aggregate results from a simulation run."""

    trades: List[SimulatedTrade] = Field(default_factory=list)
    equity_curve: List[EquitySnapshot] = Field(default_factory=list)
    initial_capital: float = Field(default=100_000)

    # Summary stats (computed after simulation)
    total_net_pnl: float = Field(default=0.0)
    total_fees: float = Field(default=0.0)
    total_slippage: float = Field(default=0.0)
    total_trades: int = Field(default=0)
    winning_trades: int = Field(default=0)
    losing_trades: int = Field(default=0)
    win_rate: float = Field(default=0.0)
    avg_hold_days: float = Field(default=0.0)
    max_drawdown_pct: float = Field(default=0.0)
    sharpe_ratio: float = Field(default=0.0)
    profit_factor: float = Field(default=0.0)

    @property
    def final_equity(self) -> float:
        return self.initial_capital + self.total_net_pnl

    @property
    def total_return_pct(self) -> float:
        if self.initial_capital > 0:
            return self.total_net_pnl / self.initial_capital
        return 0.0

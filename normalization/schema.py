"""
normalization/schema.py — Core Data Models for the Institutional Crypto Arbitrage Scanner.

This module defines all Pydantic v2 data models used across the entire system.
Every other module imports from here. No other module may define data schemas.

Models:
    - ContractType      : Enum for instrument types (SPOT, DATED_FUTURE, PERPETUAL)
    - StalenessStatus   : Enum for quote freshness classification
    - Signal            : Enum for trade signal classification
    - InstrumentQuote   : Normalized market quote from any exchange
    - SpotFuturesPair   : Matched spot + futures instrument pair
    - BasisResult       : Full basis computation output
    - FilterResult      : Per-filter pass/fail result
    - Opportunity       : Scored and ranked arbitrage opportunity
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ═══════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════


class ContractType(str, Enum):
    """Type of financial instrument contract."""

    SPOT = "SPOT"
    DATED_FUTURE = "DATED_FUTURE"
    PERPETUAL = "PERPETUAL"


class StalenessStatus(str, Enum):
    """Classification of quote freshness.

    FRESH  : Age 0–5s   → use normally
    STALE  : Age 5–30s  → use with warning flag
    DEAD   : Age >30s   → exclude from opportunities
    """

    FRESH = "FRESH"
    STALE = "STALE"
    DEAD = "DEAD"


class Signal(str, Enum):
    """Trade signal classification for an arbitrage opportunity.

    CASH_AND_CARRY : futures > spot, positive net edge → buy spot / sell futures
    REVERSE_CC     : spot > futures, positive net edge → sell spot / buy futures
    WATCH          : basis exists but below threshold or edge marginal
    NO_TRADE       : filtered out or no viable opportunity
    """

    CASH_AND_CARRY = "LONG SPOT / SHORT FUT"
    REVERSE_CC = "SHORT SPOT / LONG FUT"
    WATCH = "WATCH"
    NO_TRADE = "NO TRADE"


# ═══════════════════════════════════════════════════════════
# INSTRUMENT QUOTE
# ═══════════════════════════════════════════════════════════


class InstrumentQuote(BaseModel):
    """Normalized market quote from any exchange.

    After normalization, no downstream module knows or cares which
    exchange the data came from. All pricing, volume, and metadata
    fields follow a single internal schema.

    Computed Properties:
        spread_pct      : Bid/ask spread as a percentage of mid price.
        days_to_expiry  : Calendar days until contract expiry (dated futures only).
    """

    # ── Identity ──
    exchange: str = Field(
        ..., description="Exchange identifier: 'binance', 'bybit', 'okx'"
    )
    raw_symbol: str = Field(
        ..., description="Exchange-native symbol (e.g. 'BTCUSDT_241227')"
    )
    internal_symbol: str = Field(
        ..., description="Internal normalized symbol (e.g. 'BTC/USDT FUT 2024-12-27')"
    )
    asset: str = Field(
        ..., description="Base asset symbol: 'BTC', 'ETH', 'SOL', 'BNB'"
    )
    quote_currency: str = Field(default="USDT", description="Quote currency")
    contract_type: ContractType = Field(
        ..., description="Instrument type: SPOT, DATED_FUTURE, or PERPETUAL"
    )
    expiry: Optional[date] = Field(
        default=None, description="Contract expiry date (None for SPOT and PERPETUAL)"
    )

    # ── Pricing ──
    bid: float = Field(..., gt=0, description="Best bid price")
    ask: float = Field(..., gt=0, description="Best ask price")
    mid: float = Field(..., gt=0, description="Mid price: (bid + ask) / 2")
    last: float = Field(..., gt=0, description="Last traded price")

    # ── Market Info ──
    volume_24h: Optional[float] = Field(
        default=None, ge=0, description="24h volume in quote currency (USD)"
    )
    open_interest: Optional[float] = Field(
        default=None, ge=0, description="Open interest in base asset"
    )
    bid_size: Optional[float] = Field(
        default=None, ge=0, description="Best bid size in base asset"
    )
    ask_size: Optional[float] = Field(
        default=None, ge=0, description="Best ask size in base asset"
    )

    # ── Metadata ──
    exchange_timestamp: datetime = Field(
        ..., description="Exchange-reported timestamp"
    )
    ingest_timestamp: datetime = Field(
        ..., description="Timestamp when the system received this quote"
    )
    staleness_status: StalenessStatus = Field(
        default=StalenessStatus.FRESH,
        description="Quote freshness classification",
    )

    # ── Validators ──

    @field_validator("exchange")
    @classmethod
    def validate_exchange(cls, v: str) -> str:
        """Ensure exchange identifier is lowercase and recognized."""
        v = v.lower().strip()
        allowed = {"binance", "bybit", "okx"}
        if v not in allowed:
            raise ValueError(f"Exchange must be one of {allowed}, got '{v}'")
        return v

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, v: str) -> str:
        """Ensure asset symbol is uppercase."""
        return v.upper().strip()

    @field_validator("quote_currency")
    @classmethod
    def validate_quote_currency(cls, v: str) -> str:
        """Ensure quote currency is uppercase."""
        return v.upper().strip()

    @model_validator(mode="after")
    def validate_bid_ask_consistency(self) -> "InstrumentQuote":
        """Ensure bid <= ask."""
        if self.bid > self.ask:
            raise ValueError(
                f"Bid ({self.bid}) must be <= ask ({self.ask})"
            )
        return self

    @model_validator(mode="after")
    def validate_expiry_matches_contract_type(self) -> "InstrumentQuote":
        """Ensure expiry is set only for dated futures."""
        if self.contract_type == ContractType.DATED_FUTURE and self.expiry is None:
            raise ValueError("DATED_FUTURE contracts must have an expiry date")
        if self.contract_type in (ContractType.SPOT, ContractType.PERPETUAL) and self.expiry is not None:
            raise ValueError(
                f"{self.contract_type.value} contracts must not have an expiry date"
            )
        return self

    # ── Computed Properties ──

    @property
    def spread_pct(self) -> float:
        """Bid/ask spread as a percentage of mid price."""
        if self.mid > 0:
            return (self.ask - self.bid) / self.mid
        return float("inf")

    @property
    def days_to_expiry(self) -> Optional[float]:
        """Calendar days until contract expiry. None for SPOT and PERPETUAL."""
        if self.expiry is None:
            return None
        delta = self.expiry - date.today()
        return max(delta.days, 0.001)


# ═══════════════════════════════════════════════════════════
# SPOT / FUTURES PAIR
# ═══════════════════════════════════════════════════════════


class SpotFuturesPair(BaseModel):
    """A matched pair of spot and futures instruments for the same asset on the same exchange.

    Used by the aggregator to feed the basis engine. Each pair represents
    one potential arbitrage opportunity to evaluate.
    """

    exchange: str = Field(..., description="Exchange identifier")
    asset: str = Field(..., description="Base asset (e.g. 'BTC')")
    spot: InstrumentQuote = Field(..., description="Spot leg of the pair")
    futures: InstrumentQuote = Field(..., description="Futures leg of the pair")
    pair_id: str = Field(
        ...,
        description="Unique pair identifier (e.g. 'binance_BTC_20241227')",
    )
    created_at: datetime = Field(
        ..., description="Timestamp when this pair was assembled"
    )

    @model_validator(mode="after")
    def validate_pair_consistency(self) -> "SpotFuturesPair":
        """Ensure spot and futures belong to the same exchange and asset."""
        if self.spot.exchange != self.futures.exchange:
            raise ValueError(
                f"Spot exchange ({self.spot.exchange}) must match "
                f"futures exchange ({self.futures.exchange})"
            )
        if self.spot.asset != self.futures.asset:
            raise ValueError(
                f"Spot asset ({self.spot.asset}) must match "
                f"futures asset ({self.futures.asset})"
            )
        if self.spot.contract_type != ContractType.SPOT:
            raise ValueError("Spot leg must have contract_type SPOT")
        if self.futures.contract_type not in (
            ContractType.DATED_FUTURE,
            ContractType.PERPETUAL,
        ):
            raise ValueError(
                "Futures leg must have contract_type DATED_FUTURE or PERPETUAL"
            )
        return self


# ═══════════════════════════════════════════════════════════
# BASIS RESULT
# ═══════════════════════════════════════════════════════════


class BasisResult(BaseModel):
    """Full basis computation output for a spot/futures pair.

    Contains mid-based metrics, executable (bid/ask aware) metrics,
    cost-adjusted net edge, annualized carry, and the resulting trade signal.

    Computed Properties:
        days_to_expiry  : Calendar days until futures expiry.
        is_perpetual    : Whether this is a perpetual futures basis.
    """

    # ── Identity ──
    exchange: str = Field(..., description="Exchange identifier")
    asset: str = Field(..., description="Base asset symbol")
    spot_symbol: str = Field(..., description="Internal spot symbol")
    futures_symbol: str = Field(..., description="Internal futures symbol")
    contract_type: ContractType = Field(
        ..., description="DATED_FUTURE or PERPETUAL"
    )
    expiry: Optional[date] = Field(
        default=None, description="Futures expiry date (None for PERPETUAL)"
    )

    # ── Spot Pricing ──
    spot_bid: float = Field(..., gt=0, description="Spot best bid")
    spot_ask: float = Field(..., gt=0, description="Spot best ask")
    spot_mid: float = Field(..., gt=0, description="Spot mid price")

    # ── Futures Pricing ──
    futures_bid: float = Field(..., gt=0, description="Futures best bid")
    futures_ask: float = Field(..., gt=0, description="Futures best ask")
    futures_mid: float = Field(..., gt=0, description="Futures mid price")

    # ── Mid-Based Metrics ──
    basis_abs: float = Field(
        ..., description="Absolute basis: futures_mid - spot_mid (USD)"
    )
    basis_pct: float = Field(
        ..., description="Percentage basis: basis_abs / spot_mid"
    )
    annualized_basis: Optional[float] = Field(
        default=None,
        description="Annualized basis: basis_pct * 365 / DTE (dated only)",
    )

    # ── Executable Metrics (bid/ask aware) ──
    executable_basis_cc: float = Field(
        ...,
        description="Cash & Carry executable basis: futures_bid - spot_ask",
    )
    executable_basis_rcc: float = Field(
        ...,
        description="Reverse C&C executable basis: spot_bid - futures_ask",
    )
    gross_edge_cc_pct: float = Field(
        ..., description="Gross edge C&C: executable_basis_cc / spot_ask"
    )
    gross_edge_rcc_pct: float = Field(
        ..., description="Gross edge RCC: executable_basis_rcc / spot_bid"
    )

    # ── Net Edge (after fees + slippage) ──
    net_edge_cc_pct: float = Field(
        ..., description="Net edge C&C after costs"
    )
    net_edge_rcc_pct: float = Field(
        ..., description="Net edge RCC after costs"
    )
    annualized_net_edge_cc: Optional[float] = Field(
        default=None, description="Annualized net edge C&C (dated only)"
    )
    annualized_net_edge_rcc: Optional[float] = Field(
        default=None, description="Annualized net edge RCC (dated only)"
    )

    # ── Signal & Metadata ──
    signal: Signal = Field(..., description="Trade signal classification")
    timestamp: datetime = Field(
        ..., description="Timestamp of this computation"
    )

    # ── Market Context (for scoring) ──
    volume_usd_24h: Optional[float] = Field(
        default=None, ge=0, description="Combined 24h volume (USD)"
    )
    spread_pct: Optional[float] = Field(
        default=None, ge=0, description="Futures bid/ask spread percentage"
    )

    # ── Computed Properties ──

    @property
    def days_to_expiry(self) -> Optional[float]:
        """Calendar days until futures contract expiry."""
        if self.expiry is None:
            return None
        delta = self.expiry - date.today()
        return max(delta.days, 0.001)

    @property
    def is_perpetual(self) -> bool:
        """Whether this is a perpetual futures basis."""
        return self.contract_type == ContractType.PERPETUAL

    # ── Validators ──

    @model_validator(mode="after")
    def validate_annualization(self) -> "BasisResult":
        """Ensure annualized fields are set only for dated futures."""
        if self.contract_type == ContractType.DATED_FUTURE:
            if self.annualized_basis is None:
                raise ValueError(
                    "DATED_FUTURE must have annualized_basis computed"
                )
        if self.contract_type == ContractType.PERPETUAL:
            if self.annualized_basis is not None:
                raise ValueError(
                    "PERPETUAL contracts must not have annualized_basis"
                )
            if self.annualized_net_edge_cc is not None:
                raise ValueError(
                    "PERPETUAL contracts must not have annualized_net_edge_cc"
                )
            if self.annualized_net_edge_rcc is not None:
                raise ValueError(
                    "PERPETUAL contracts must not have annualized_net_edge_rcc"
                )
        return self

    @model_validator(mode="after")
    def validate_expiry_matches_type(self) -> "BasisResult":
        """Ensure expiry is set for dated futures and absent for perpetuals."""
        if self.contract_type == ContractType.DATED_FUTURE and self.expiry is None:
            raise ValueError("DATED_FUTURE must have an expiry date")
        if self.contract_type == ContractType.PERPETUAL and self.expiry is not None:
            raise ValueError("PERPETUAL must not have an expiry date")
        return self


# ═══════════════════════════════════════════════════════════
# FILTER RESULT
# ═══════════════════════════════════════════════════════════


class FilterResult(BaseModel):
    """Result of a single filter applied to an opportunity.

    Each filter in the pipeline returns one FilterResult indicating
    whether the opportunity passed and, if not, the rejection reason.
    """

    filter_name: str = Field(
        ..., description="Name of the filter (e.g. 'liquidity', 'spread')"
    )
    passed: bool = Field(
        ..., description="Whether the opportunity passed this filter"
    )
    reason: str = Field(
        default="",
        description="Human-readable reason for rejection (empty if passed)",
    )
    value: Optional[float] = Field(
        default=None,
        description="The actual measured value that was tested",
    )
    threshold: Optional[float] = Field(
        default=None,
        description="The threshold the value was compared against",
    )


# ═══════════════════════════════════════════════════════════
# OPPORTUNITY
# ═══════════════════════════════════════════════════════════


class Opportunity(BaseModel):
    """A scored and ranked arbitrage opportunity.

    Combines the matched pair, basis computation, filter results,
    composite score, and trade signal into a single output object
    consumed by the dashboard and storage layers.
    """

    pair: SpotFuturesPair = Field(
        ..., description="The spot/futures pair for this opportunity"
    )
    basis_result: BasisResult = Field(
        ..., description="Full basis computation output"
    )
    score: float = Field(
        ..., ge=0, le=100, description="Composite opportunity score (0–100)"
    )
    signal: Signal = Field(
        ..., description="Trade signal classification"
    )
    passed_filters: bool = Field(
        ..., description="Whether the opportunity passed all filters"
    )
    filter_results: List[FilterResult] = Field(
        default_factory=list,
        description="Individual filter results",
    )
    ranked_at: datetime = Field(
        ..., description="Timestamp when scoring/ranking was performed"
    )

    @property
    def filter_reasons(self) -> List[str]:
        """List of rejection reasons from failed filters."""
        return [
            fr.reason for fr in self.filter_results if not fr.passed and fr.reason
        ]

    @property
    def rejection_summary(self) -> str:
        """Comma-separated summary of all rejection reasons."""
        reasons = self.filter_reasons
        if not reasons:
            return "PASSED"
        return "; ".join(reasons)

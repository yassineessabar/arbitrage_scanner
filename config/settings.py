"""
config/settings.py — Pydantic Settings model for the Arbitrage Scanner.

Loads configuration from:
  1. config/default.yaml  (base defaults)
  2. .env file            (environment overrides)
  3. Runtime env vars     (ARBS_ prefix overrides)

Usage:
    from config.settings import get_settings
    settings = get_settings()
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


# ═══════════════════════════════════════════════════════════
# SUB-MODELS (plain BaseModel — not settings, just structure)
# ═══════════════════════════════════════════════════════════


class SystemConfig(BaseModel):
    """Top-level system settings."""

    scan_interval_seconds: int = Field(default=5, ge=1)
    log_level: str = Field(default="INFO")
    storage_path: str = Field(default="./data/arbitrage.db")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v = v.upper().strip()
        if v not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return v


class ExchangeConfig(BaseModel):
    """Per-exchange configuration."""

    enabled: bool = Field(default=True)
    fee_taker: float = Field(default=0.0005, ge=0)
    reliability_score: int = Field(default=90, ge=0, le=100)


class AssetConfig(BaseModel):
    """Per-asset configuration."""

    symbol: str = Field(..., description="Internal symbol e.g. 'BTC/USDT'")
    min_volume_usd_24h: float = Field(default=1_000_000, ge=0)


class FilterConfig(BaseModel):
    """Opportunity filter thresholds."""

    min_annualized_basis: float = Field(default=0.05, ge=0)
    max_spread_pct: float = Field(default=0.001, ge=0)
    max_staleness_seconds: float = Field(default=5.0, ge=0)
    slippage_assumption: float = Field(default=0.0003, ge=0)
    min_days_to_expiry: float = Field(default=1.0, ge=0)


class ScoringWeights(BaseModel):
    """Scoring component weights (must sum to ~1.0)."""

    edge: float = Field(default=0.35)
    liquidity: float = Field(default=0.25)
    spread: float = Field(default=0.20)
    freshness: float = Field(default=0.10)
    exchange: float = Field(default=0.10)


class ScoringConfig(BaseModel):
    """Scoring engine configuration."""

    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    max_edge_for_normalization: float = Field(default=0.30)
    max_staleness_for_normalization: float = Field(default=5.0)


class StorageConfig(BaseModel):
    """Historical storage settings."""

    write_interval_seconds: int = Field(default=60, ge=1)
    basis_change_threshold_bps: float = Field(default=5.0, ge=0)
    export_parquet: bool = Field(default=True)
    export_interval_days: int = Field(default=7, ge=1)


class DashboardConfig(BaseModel):
    """Dashboard display settings."""

    refresh_interval_seconds: int = Field(default=3, ge=1)
    top_opportunities_count: int = Field(default=3, ge=1)
    min_score_to_display: float = Field(default=0, ge=0, le=100)


class SimulationConfig(BaseModel):
    """P&L simulation settings."""

    enabled: bool = Field(default=False)
    initial_capital: float = Field(default=10_000, gt=0)
    position_size_pct: float = Field(default=0.10, gt=0, le=1.0)
    max_open_positions: int = Field(default=5, ge=1)
    min_score_to_trade: float = Field(default=60.0, ge=0, le=100)
    exit_basis_convergence_pct: float = Field(default=0.002, ge=0)
    max_hold_days: int = Field(default=90, ge=1)


class CrossExchangeConfig(BaseModel):
    """Cross-exchange arbitrage simulation settings."""

    enabled: bool = Field(default=True)
    initial_capital: float = Field(default=10_000, gt=0)
    position_size_pct: float = Field(default=0.10, gt=0, le=1.0)
    max_open_positions: int = Field(default=5, ge=1)
    min_edge_to_trade: float = Field(default=0.0005, ge=0,
                                      description="Minimum net edge (5 bps) after fees+slippage")
    exit_convergence_threshold: float = Field(default=0.0002, ge=0,
                                               description="Close when spread narrows below 2 bps")
    max_hold_minutes: int = Field(default=120, ge=1,
                                   description="Force close after N minutes")
    slippage_per_side: float = Field(default=0.0003, ge=0,
                                      description="Slippage assumption per leg (3 bps)")


# ═══════════════════════════════════════════════════════════
# MAIN SETTINGS
# ═══════════════════════════════════════════════════════════


class Settings(BaseSettings):
    """Root settings for the Arbitrage Scanner.

    Resolution order:
      1. config/default.yaml   → base values
      2. .env file             → environment overrides
      3. ARBS_* env vars       → runtime overrides
    """

    system: SystemConfig = Field(default_factory=SystemConfig)
    exchanges: Dict[str, ExchangeConfig] = Field(default_factory=dict)
    assets: List[AssetConfig] = Field(default_factory=list)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    cross_exchange: CrossExchangeConfig = Field(default_factory=CrossExchangeConfig)

    model_config = {
        "env_prefix": "ARBS_",
        "env_nested_delimiter": "__",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def get_enabled_exchanges(self) -> Dict[str, ExchangeConfig]:
        """Return only enabled exchanges."""
        return {k: v for k, v in self.exchanges.items() if v.enabled}

    def get_fee_for_exchange(self, exchange: str) -> float:
        """Return the taker fee for a given exchange."""
        exc = self.exchanges.get(exchange.lower())
        if exc is None:
            return 0.0005  # conservative default
        return exc.fee_taker

    def get_reliability_score(self, exchange: str) -> float:
        """Return the reliability score (0–1) for a given exchange."""
        exc = self.exchanges.get(exchange.lower())
        if exc is None:
            return 0.80
        return exc.reliability_score / 100.0

    def get_min_volume_for_asset(self, symbol: str) -> float:
        """Return minimum 24h volume for an asset symbol."""
        for asset in self.assets:
            if asset.symbol == symbol:
                return asset.min_volume_usd_24h
        return 1_000_000  # default fallback


def _load_yaml_config(yaml_path: Optional[str] = None) -> dict:
    """Load and return config from a YAML file."""
    if yaml_path is None:
        # Look relative to this file's directory
        yaml_path = str(Path(__file__).parent / "default.yaml")

    if not os.path.exists(yaml_path):
        return {}

    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f) or {}
    return data


def get_settings(yaml_path: Optional[str] = None) -> Settings:
    """Load settings from YAML, .env, and environment variables.

    Args:
        yaml_path: Optional path to YAML config. Defaults to config/default.yaml.

    Returns:
        Fully resolved Settings instance.
    """
    yaml_data = _load_yaml_config(yaml_path)
    return Settings(**yaml_data)

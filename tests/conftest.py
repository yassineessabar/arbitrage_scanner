"""
tests/conftest.py — Shared fixtures and mock data for the test suite.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timezone

import pytest

from config.settings import Settings, get_settings
from normalization.schema import (
    BasisResult,
    ContractType,
    InstrumentQuote,
    Signal,
    SpotFuturesPair,
    StalenessStatus,
)


@pytest.fixture
def utc_now() -> datetime:
    """Current UTC time fixture."""
    return datetime.now(timezone.utc)


@pytest.fixture
def future_expiry() -> date:
    """A future expiry date for testing."""
    return date(2026, 9, 25)


@pytest.fixture
def settings() -> Settings:
    """Application settings from default.yaml."""
    return get_settings()


@pytest.fixture
def temp_db_path(tmp_path):
    """Temporary database path for storage tests."""
    return str(tmp_path / "test_arb.db")


@pytest.fixture
def temp_settings(temp_db_path) -> Settings:
    """Settings with temporary database path."""
    s = get_settings()
    s.system.storage_path = temp_db_path
    return s


def make_quote(
    exchange: str = "binance",
    asset: str = "BTC",
    contract_type: ContractType = ContractType.SPOT,
    bid: float = 64000.0,
    ask: float = 64010.0,
    expiry: date | None = None,
    volume: float = 2_400_000_000.0,
    ts: datetime | None = None,
) -> InstrumentQuote:
    """Factory for creating test InstrumentQuote objects."""
    if ts is None:
        ts = datetime.now(timezone.utc)

    if contract_type == ContractType.SPOT:
        suffix = "SPOT"
    elif contract_type == ContractType.PERPETUAL:
        suffix = "PERP"
    else:
        suffix = f"FUT {expiry}"

    return InstrumentQuote(
        exchange=exchange,
        raw_symbol="TEST",
        internal_symbol=f"{asset}/USDT {suffix}",
        asset=asset,
        contract_type=contract_type,
        expiry=expiry,
        bid=bid,
        ask=ask,
        mid=(bid + ask) / 2.0,
        last=(bid + ask) / 2.0,
        volume_24h=volume,
        exchange_timestamp=ts,
        ingest_timestamp=ts,
    )


def make_pair(
    exchange: str = "binance",
    asset: str = "BTC",
    spot_bid: float = 64000.0,
    spot_ask: float = 64005.0,
    fut_bid: float = 65100.0,
    fut_ask: float = 65105.0,
    expiry: date | None = None,
    contract_type: ContractType = ContractType.DATED_FUTURE,
    volume: float = 2_400_000_000.0,
    ts: datetime | None = None,
) -> SpotFuturesPair:
    """Factory for creating test SpotFuturesPair objects."""
    if ts is None:
        ts = datetime.now(timezone.utc)
    if expiry is None and contract_type == ContractType.DATED_FUTURE:
        expiry = date(2026, 9, 25)

    spot = make_quote(exchange, asset, ContractType.SPOT, spot_bid, spot_ask, volume=volume, ts=ts)
    futures = make_quote(exchange, asset, contract_type, fut_bid, fut_ask, expiry=expiry, volume=volume, ts=ts)

    suffix = "PERP" if contract_type == ContractType.PERPETUAL else expiry.strftime("%Y%m%d")
    pair_id = f"{exchange}_{asset}_{suffix}"

    return SpotFuturesPair(
        exchange=exchange,
        asset=asset,
        spot=spot,
        futures=futures,
        pair_id=pair_id,
        created_at=ts,
    )

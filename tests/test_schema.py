"""tests/test_schema.py — Schema validation edge cases."""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from normalization.schema import (
    BasisResult,
    ContractType,
    FilterResult,
    InstrumentQuote,
    Opportunity,
    Signal,
    SpotFuturesPair,
    StalenessStatus,
)
from tests.conftest import make_quote, make_pair


class TestEnums:
    def test_contract_type_values(self):
        assert ContractType.SPOT.value == "SPOT"
        assert ContractType.DATED_FUTURE.value == "DATED_FUTURE"
        assert ContractType.PERPETUAL.value == "PERPETUAL"

    def test_staleness_values(self):
        assert StalenessStatus.FRESH.value == "FRESH"
        assert StalenessStatus.STALE.value == "STALE"
        assert StalenessStatus.DEAD.value == "DEAD"

    def test_signal_values(self):
        assert Signal.CASH_AND_CARRY.value == "LONG SPOT / SHORT FUT"
        assert Signal.REVERSE_CC.value == "SHORT SPOT / LONG FUT"
        assert Signal.WATCH.value == "WATCH"
        assert Signal.NO_TRADE.value == "NO TRADE"


class TestInstrumentQuote:
    def test_spot_quote_creation(self):
        q = make_quote()
        assert q.exchange == "binance"
        assert q.asset == "BTC"
        assert q.contract_type == ContractType.SPOT
        assert q.expiry is None
        assert q.days_to_expiry is None

    def test_dated_future_quote(self):
        exp = date(2026, 9, 25)
        q = make_quote(contract_type=ContractType.DATED_FUTURE, expiry=exp)
        assert q.expiry == exp
        assert q.days_to_expiry is not None
        assert q.days_to_expiry > 0

    def test_spread_pct_computed(self):
        q = make_quote(bid=100.0, ask=100.1)
        expected = (100.1 - 100.0) / 100.05
        assert abs(q.spread_pct - expected) < 1e-10

    def test_bid_greater_than_ask_rejected(self):
        with pytest.raises(ValidationError):
            make_quote(bid=65000.0, ask=64000.0)

    def test_dated_future_without_expiry_rejected(self):
        with pytest.raises(ValidationError):
            make_quote(contract_type=ContractType.DATED_FUTURE, expiry=None)

    def test_spot_with_expiry_rejected(self):
        with pytest.raises(ValidationError):
            make_quote(contract_type=ContractType.SPOT, expiry=date(2026, 1, 1))

    def test_exchange_lowercased(self):
        q = make_quote(exchange="BINANCE")
        assert q.exchange == "binance"

    def test_asset_uppercased(self):
        q = make_quote(asset="btc")
        assert q.asset == "BTC"

    def test_invalid_exchange_rejected(self):
        with pytest.raises(ValidationError):
            make_quote(exchange="kraken")


class TestSpotFuturesPair:
    def test_pair_creation(self):
        pair = make_pair()
        assert pair.exchange == "binance"
        assert pair.asset == "BTC"
        assert pair.spot.contract_type == ContractType.SPOT
        assert pair.futures.contract_type == ContractType.DATED_FUTURE

    def test_mismatched_exchange_rejected(self):
        now = datetime.now(timezone.utc)
        spot = make_quote(exchange="binance")
        fut = make_quote(exchange="okx", contract_type=ContractType.PERPETUAL)
        with pytest.raises(ValidationError):
            SpotFuturesPair(
                exchange="binance", asset="BTC", spot=spot, futures=fut,
                pair_id="test", created_at=now,
            )

    def test_mismatched_asset_rejected(self):
        now = datetime.now(timezone.utc)
        spot = make_quote(asset="BTC")
        fut = make_quote(asset="ETH", contract_type=ContractType.PERPETUAL)
        with pytest.raises(ValidationError):
            SpotFuturesPair(
                exchange="binance", asset="BTC", spot=spot, futures=fut,
                pair_id="test", created_at=now,
            )


class TestFilterResult:
    def test_passed_filter(self):
        fr = FilterResult(filter_name="test", passed=True)
        assert fr.passed
        assert fr.reason == ""

    def test_failed_filter(self):
        fr = FilterResult(
            filter_name="liquidity", passed=False,
            reason="Volume too low", value=500000, threshold=1000000,
        )
        assert not fr.passed
        assert "Volume too low" in fr.reason

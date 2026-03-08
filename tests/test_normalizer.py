"""tests/test_normalizer.py — Normalization from mock raw payloads."""

from datetime import date

import pytest

from normalization.normalizer import normalize_quote
from normalization.symbol_map import resolve_symbol
from normalization.schema import ContractType


class TestSymbolMap:
    def test_binance_spot(self):
        r = resolve_symbol("binance", "BTCUSDT", "spot")
        assert r is not None
        assert r == ("BTC/USDT SPOT", "BTC", ContractType.SPOT, None)

    def test_binance_perp(self):
        r = resolve_symbol("binance", "ETHUSDT", "futures")
        assert r is not None
        assert r[2] == ContractType.PERPETUAL

    def test_binance_dated(self):
        r = resolve_symbol("binance", "BTCUSDT_250627", "")
        assert r is not None
        assert r[2] == ContractType.DATED_FUTURE
        assert r[3] == date(2025, 6, 27)

    def test_bybit_spot(self):
        r = resolve_symbol("bybit", "SOLUSDT", "spot")
        assert r is not None
        assert r[2] == ContractType.SPOT

    def test_bybit_dated(self):
        r = resolve_symbol("bybit", "BTC-27JUN25", "linear")
        assert r is not None
        assert r[2] == ContractType.DATED_FUTURE
        assert r[3] == date(2025, 6, 27)

    def test_okx_spot(self):
        r = resolve_symbol("okx", "BTC-USDT", "")
        assert r is not None
        assert r[2] == ContractType.SPOT

    def test_okx_swap(self):
        r = resolve_symbol("okx", "ETH-USDT-SWAP", "")
        assert r is not None
        assert r[2] == ContractType.PERPETUAL

    def test_okx_dated(self):
        r = resolve_symbol("okx", "BTC-USDT-250627", "")
        assert r is not None
        assert r[2] == ContractType.DATED_FUTURE

    def test_unsupported_asset_returns_none(self):
        assert resolve_symbol("binance", "DOGEUSDT", "spot") is None

    def test_unsupported_exchange_returns_none(self):
        assert resolve_symbol("kraken", "BTCUSDT", "spot") is None


class TestNormalizeBinance:
    def test_book_ticker(self):
        payload = {
            "_feed_type": "spot",
            "s": "BTCUSDT",
            "b": "64000.0",
            "a": "64010.0",
            "B": "1.5",
            "A": "2.0",
            "E": 1710000000000,
        }
        q = normalize_quote("binance", payload)
        assert q is not None
        assert q.exchange == "binance"
        assert q.asset == "BTC"
        assert q.contract_type == ContractType.SPOT
        assert q.bid == 64000.0
        assert q.ask == 64010.0

    def test_futures_ticker(self):
        payload = {
            "_feed_type": "futures",
            "s": "ETHUSDT",
            "b": "3420.0",
            "a": "3421.0",
            "E": 1710000000000,
        }
        q = normalize_quote("binance", payload)
        assert q is not None
        assert q.contract_type == ContractType.PERPETUAL

    def test_invalid_payload_returns_none(self):
        assert normalize_quote("binance", {"bad": "data"}) is None

    def test_zero_price_returns_none(self):
        payload = {"_feed_type": "spot", "s": "BTCUSDT", "b": "0", "a": "0"}
        assert normalize_quote("binance", payload) is None


class TestNormalizeBybit:
    def test_spot_ticker(self):
        payload = {
            "_feed_type": "spot",
            "topic": "tickers.BTCUSDT",
            "data": {
                "symbol": "BTCUSDT",
                "bid1Price": "64000",
                "ask1Price": "64010",
                "lastPrice": "64005",
                "turnover24h": "2400000000",
            },
            "ts": "1710000000000",
        }
        q = normalize_quote("bybit", payload)
        assert q is not None
        assert q.exchange == "bybit"
        assert q.contract_type == ContractType.SPOT


class TestNormalizeOKX:
    def test_swap_ticker(self):
        payload = {
            "_exchange": "okx",
            "arg": {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
            "data": [{
                "instId": "BTC-USDT-SWAP",
                "bidPx": "64300",
                "askPx": "64320",
                "last": "64310",
                "volCcy24h": "2000000000",
                "ts": "1710000000000",
            }],
        }
        q = normalize_quote("okx", payload)
        assert q is not None
        assert q.contract_type == ContractType.PERPETUAL
        assert q.bid == 64300.0

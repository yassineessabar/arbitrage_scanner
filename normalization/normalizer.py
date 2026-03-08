"""
normalization/normalizer.py — Per-exchange normalization logic.

Converts raw exchange WebSocket payloads into InstrumentQuote objects.
Handles missing fields gracefully, attaches ingest_timestamp, and
validates with Pydantic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog

from normalization.schema import InstrumentQuote
from normalization.symbol_map import resolve_symbol

logger = structlog.get_logger(__name__)


def normalize_quote(
    exchange_id: str,
    raw_payload: dict,
) -> Optional[InstrumentQuote]:
    """Normalize a raw exchange payload into an InstrumentQuote.

    Args:
        exchange_id: Exchange identifier ('binance', 'bybit', 'okx').
        raw_payload: Raw JSON payload from the WebSocket feed.

    Returns:
        InstrumentQuote if normalization succeeds, None otherwise.
    """
    try:
        exchange_id = exchange_id.lower()
        if exchange_id == "binance":
            return _normalize_binance(raw_payload)
        elif exchange_id == "bybit":
            return _normalize_bybit(raw_payload)
        elif exchange_id == "okx":
            return _normalize_okx(raw_payload)
        else:
            logger.warning("unknown_exchange", exchange=exchange_id)
            return None
    except Exception as e:
        logger.debug(
            "normalization_error",
            exchange=exchange_id,
            error=str(e),
        )
        return None


# ═══════════════════════════════════════════════════════════
# BINANCE
# ═══════════════════════════════════════════════════════════


def _normalize_binance(payload: dict) -> Optional[InstrumentQuote]:
    """Normalize a Binance bookTicker or 24hrTicker payload."""
    feed_type = payload.get("_feed_type", "spot")

    # bookTicker format: {s, b, B, a, A}
    raw_symbol = payload.get("s")
    if raw_symbol is None:
        return None

    resolved = resolve_symbol("binance", raw_symbol, feed_type)
    if resolved is None:
        return None

    internal_symbol, asset, contract_type, expiry = resolved

    # Extract prices — bookTicker has b (bid), a (ask)
    bid = _safe_float(payload.get("b"))
    ask = _safe_float(payload.get("a"))
    last = _safe_float(payload.get("c")) or _safe_float(payload.get("b"))

    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None

    mid = (bid + ask) / 2.0
    if last is None or last <= 0:
        last = mid

    # Volume from ticker: v (base volume), q (quote volume)
    volume_24h = _safe_float(payload.get("q"))
    bid_size = _safe_float(payload.get("B"))
    ask_size = _safe_float(payload.get("A"))

    # Exchange timestamp
    event_time = payload.get("E")
    exchange_ts = _ms_to_datetime(event_time) if event_time else datetime.now(timezone.utc)

    return InstrumentQuote(
        exchange="binance",
        raw_symbol=raw_symbol,
        internal_symbol=internal_symbol,
        asset=asset,
        contract_type=contract_type,
        expiry=expiry,
        bid=bid,
        ask=ask,
        mid=mid,
        last=last,
        volume_24h=volume_24h,
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp=exchange_ts,
        ingest_timestamp=datetime.now(timezone.utc),
    )


# ═══════════════════════════════════════════════════════════
# BYBIT
# ═══════════════════════════════════════════════════════════


def _normalize_bybit(payload: dict) -> Optional[InstrumentQuote]:
    """Normalize a Bybit V5 tickers payload."""
    feed_type = payload.get("_feed_type", "spot")

    ticker_data = payload.get("data")
    if not ticker_data:
        return None

    raw_symbol = ticker_data.get("symbol")
    if raw_symbol is None:
        return None

    resolved = resolve_symbol("bybit", raw_symbol, feed_type)
    if resolved is None:
        return None

    internal_symbol, asset, contract_type, expiry = resolved

    bid = _safe_float(ticker_data.get("bid1Price"))
    ask = _safe_float(ticker_data.get("ask1Price"))
    last = _safe_float(ticker_data.get("lastPrice"))

    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None

    mid = (bid + ask) / 2.0
    if last is None or last <= 0:
        last = mid

    volume_24h = _safe_float(ticker_data.get("turnover24h"))
    bid_size = _safe_float(ticker_data.get("bid1Size"))
    ask_size = _safe_float(ticker_data.get("ask1Size"))
    open_interest = _safe_float(ticker_data.get("openInterest"))

    ts_ms = payload.get("ts")
    exchange_ts = _ms_to_datetime(ts_ms) if ts_ms else datetime.now(timezone.utc)

    return InstrumentQuote(
        exchange="bybit",
        raw_symbol=raw_symbol,
        internal_symbol=internal_symbol,
        asset=asset,
        contract_type=contract_type,
        expiry=expiry,
        bid=bid,
        ask=ask,
        mid=mid,
        last=last,
        volume_24h=volume_24h,
        open_interest=open_interest,
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp=exchange_ts,
        ingest_timestamp=datetime.now(timezone.utc),
    )


# ═══════════════════════════════════════════════════════════
# OKX
# ═══════════════════════════════════════════════════════════


def _normalize_okx(payload: dict) -> Optional[InstrumentQuote]:
    """Normalize an OKX V5 tickers payload."""
    data_list = payload.get("data")
    if not data_list or not isinstance(data_list, list):
        return None

    ticker = data_list[0]
    raw_symbol = ticker.get("instId")
    if raw_symbol is None:
        return None

    resolved = resolve_symbol("okx", raw_symbol)
    if resolved is None:
        return None

    internal_symbol, asset, contract_type, expiry = resolved

    bid = _safe_float(ticker.get("bidPx"))
    ask = _safe_float(ticker.get("askPx"))
    last = _safe_float(ticker.get("last"))

    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None

    mid = (bid + ask) / 2.0
    if last is None or last <= 0:
        last = mid

    # OKX provides volCcy24h (quote volume) for spot, vol24h for futures
    volume_24h = _safe_float(ticker.get("volCcy24h")) or _safe_float(
        ticker.get("vol24h")
    )
    bid_size = _safe_float(ticker.get("bidSz"))
    ask_size = _safe_float(ticker.get("askSz"))
    open_interest = _safe_float(ticker.get("oi"))

    ts_ms = ticker.get("ts")
    exchange_ts = _ms_to_datetime(ts_ms) if ts_ms else datetime.now(timezone.utc)

    return InstrumentQuote(
        exchange="okx",
        raw_symbol=raw_symbol,
        internal_symbol=internal_symbol,
        asset=asset,
        contract_type=contract_type,
        expiry=expiry,
        bid=bid,
        ask=ask,
        mid=mid,
        last=last,
        volume_24h=volume_24h,
        open_interest=open_interest,
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp=exchange_ts,
        ingest_timestamp=datetime.now(timezone.utc),
    )


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════


def _safe_float(value: object) -> Optional[float]:
    """Safely convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        f = float(value)
        return f if f >= 0 else None
    except (ValueError, TypeError):
        return None


def _ms_to_datetime(ms: object) -> datetime:
    """Convert millisecond timestamp to timezone-aware datetime."""
    try:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return datetime.now(timezone.utc)

"""
normalization/symbol_map.py — Cross-exchange symbol mapping.

Maps exchange-native symbols to internal normalized symbols and vice versa.
Covers BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT across
Binance, Bybit, OKX for spot, perpetual, and dated futures.

Internal symbol format:
  - Spot:       "BTC/USDT SPOT"
  - Perpetual:  "BTC/USDT PERP"
  - Dated:      "BTC/USDT FUT 2025-06-27"
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional, Tuple

from normalization.schema import ContractType

# ═══════════════════════════════════════════════════════════
# BASE ASSETS
# ═══════════════════════════════════════════════════════════

SUPPORTED_ASSETS = ("BTC", "ETH", "SOL", "BNB")
QUOTE_CURRENCY = "USDT"


# ═══════════════════════════════════════════════════════════
# SYMBOL RESOLUTION
# ═══════════════════════════════════════════════════════════


def resolve_symbol(
    exchange: str,
    raw_symbol: str,
    feed_type: str = "",
) -> Optional[Tuple[str, str, ContractType, Optional[date]]]:
    """Resolve an exchange-native symbol to internal representation.

    Args:
        exchange: Exchange identifier ('binance', 'bybit', 'okx').
        raw_symbol: Exchange-native symbol string.
        feed_type: Feed type hint ('spot', 'futures', 'linear', '').

    Returns:
        Tuple of (internal_symbol, asset, contract_type, expiry) or None if
        the symbol cannot be mapped.
    """
    exchange = exchange.lower()
    if exchange == "binance":
        return _resolve_binance(raw_symbol, feed_type)
    elif exchange == "bybit":
        return _resolve_bybit(raw_symbol, feed_type)
    elif exchange == "okx":
        return _resolve_okx(raw_symbol, feed_type)
    return None


# ═══════════════════════════════════════════════════════════
# BINANCE
# ═══════════════════════════════════════════════════════════
#
# Spot:     BTCUSDT
# Perp:     BTCUSDT (on fstream, same symbol as spot but futures context)
# Dated:    BTCUSDT_250627


def _resolve_binance(
    raw_symbol: str, feed_type: str
) -> Optional[Tuple[str, str, ContractType, Optional[date]]]:
    """Resolve Binance symbol."""
    raw_upper = raw_symbol.upper()

    # Dated future: BTCUSDT_250627
    dated_match = re.match(r"^([A-Z]+)(USDT)_(\d{6})$", raw_upper)
    if dated_match:
        asset = dated_match.group(1)
        if asset not in SUPPORTED_ASSETS:
            return None
        expiry = _parse_date_yymmdd(dated_match.group(3))
        if expiry is None:
            return None
        internal = f"{asset}/{QUOTE_CURRENCY} FUT {expiry.isoformat()}"
        return (internal, asset, ContractType.DATED_FUTURE, expiry)

    # Spot or perp: BTCUSDT
    base_match = re.match(r"^([A-Z]+)(USDT)$", raw_upper)
    if base_match:
        asset = base_match.group(1)
        if asset not in SUPPORTED_ASSETS:
            return None
        if feed_type == "futures":
            internal = f"{asset}/{QUOTE_CURRENCY} PERP"
            return (internal, asset, ContractType.PERPETUAL, None)
        else:
            internal = f"{asset}/{QUOTE_CURRENCY} SPOT"
            return (internal, asset, ContractType.SPOT, None)

    return None


# ═══════════════════════════════════════════════════════════
# BYBIT
# ═══════════════════════════════════════════════════════════
#
# Spot:     BTCUSDT (on spot feed)
# Perp:     BTCUSDT (on linear feed)
# Dated:    BTC-27JUN25


def _resolve_bybit(
    raw_symbol: str, feed_type: str
) -> Optional[Tuple[str, str, ContractType, Optional[date]]]:
    """Resolve Bybit symbol."""
    raw_upper = raw_symbol.upper()

    # Dated future: BTC-27JUN25
    dated_match = re.match(r"^([A-Z]+)-(\d{2})([A-Z]{3})(\d{2})$", raw_upper)
    if dated_match:
        asset = dated_match.group(1)
        if asset not in SUPPORTED_ASSETS:
            return None
        expiry = _parse_date_ddmmmyy(
            dated_match.group(2), dated_match.group(3), dated_match.group(4)
        )
        if expiry is None:
            return None
        internal = f"{asset}/{QUOTE_CURRENCY} FUT {expiry.isoformat()}"
        return (internal, asset, ContractType.DATED_FUTURE, expiry)

    # Spot or perp: BTCUSDT
    base_match = re.match(r"^([A-Z]+)(USDT)$", raw_upper)
    if base_match:
        asset = base_match.group(1)
        if asset not in SUPPORTED_ASSETS:
            return None
        if feed_type == "linear":
            internal = f"{asset}/{QUOTE_CURRENCY} PERP"
            return (internal, asset, ContractType.PERPETUAL, None)
        else:
            internal = f"{asset}/{QUOTE_CURRENCY} SPOT"
            return (internal, asset, ContractType.SPOT, None)

    return None


# ═══════════════════════════════════════════════════════════
# OKX
# ═══════════════════════════════════════════════════════════
#
# Spot:     BTC-USDT
# Perp:     BTC-USDT-SWAP
# Dated:    BTC-USDT-250627


def _resolve_okx(
    raw_symbol: str, feed_type: str = ""
) -> Optional[Tuple[str, str, ContractType, Optional[date]]]:
    """Resolve OKX symbol."""
    raw_upper = raw_symbol.upper()

    # Perpetual swap: BTC-USDT-SWAP
    if raw_upper.endswith("-SWAP"):
        parts = raw_upper.replace("-SWAP", "").split("-")
        if len(parts) != 2:
            return None
        asset = parts[0]
        if asset not in SUPPORTED_ASSETS:
            return None
        internal = f"{asset}/{QUOTE_CURRENCY} PERP"
        return (internal, asset, ContractType.PERPETUAL, None)

    # Dated future: BTC-USDT-250627
    dated_match = re.match(r"^([A-Z]+)-USDT-(\d{6})$", raw_upper)
    if dated_match:
        asset = dated_match.group(1)
        if asset not in SUPPORTED_ASSETS:
            return None
        expiry = _parse_date_yymmdd(dated_match.group(2))
        if expiry is None:
            return None
        internal = f"{asset}/{QUOTE_CURRENCY} FUT {expiry.isoformat()}"
        return (internal, asset, ContractType.DATED_FUTURE, expiry)

    # Spot: BTC-USDT
    spot_match = re.match(r"^([A-Z]+)-USDT$", raw_upper)
    if spot_match:
        asset = spot_match.group(1)
        if asset not in SUPPORTED_ASSETS:
            return None
        internal = f"{asset}/{QUOTE_CURRENCY} SPOT"
        return (internal, asset, ContractType.SPOT, None)

    return None


# ═══════════════════════════════════════════════════════════
# DATE PARSING HELPERS
# ═══════════════════════════════════════════════════════════

MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _parse_date_yymmdd(s: str) -> Optional[date]:
    """Parse YYMMDD format (e.g. '250627' -> 2025-06-27)."""
    try:
        return datetime.strptime(s, "%y%m%d").date()
    except ValueError:
        return None


def _parse_date_ddmmmyy(day: str, month: str, year: str) -> Optional[date]:
    """Parse DD-MMM-YY format (e.g. '27', 'JUN', '25' -> 2025-06-27)."""
    mon = MONTH_MAP.get(month.upper())
    if mon is None:
        return None
    try:
        return date(2000 + int(year), mon, int(day))
    except ValueError:
        return None

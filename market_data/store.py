"""
market_data/store.py — Thread-safe in-memory market data store.

Maintains a live snapshot of all current quotes, keyed by
(exchange, internal_symbol). Supports upsert, get, and get_all operations.
All operations are asyncio-safe via an asyncio.Lock.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import structlog

from normalization.schema import InstrumentQuote

logger = structlog.get_logger(__name__)

# Store key type: (exchange, internal_symbol)
StoreKey = Tuple[str, str]


class MarketDataStore:
    """In-memory store for the latest InstrumentQuote per instrument.

    Thread-safe via asyncio.Lock. Supports upsert, lookup, and
    full snapshot retrieval.
    """

    def __init__(self) -> None:
        self._data: Dict[StoreKey, InstrumentQuote] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, quote: InstrumentQuote) -> None:
        """Insert or update a quote in the store.

        Args:
            quote: Normalized InstrumentQuote to store.
        """
        key: StoreKey = (quote.exchange, quote.internal_symbol)
        async with self._lock:
            self._data[key] = quote

    async def get(
        self, exchange: str, internal_symbol: str
    ) -> Optional[InstrumentQuote]:
        """Retrieve the latest quote for a specific instrument.

        Args:
            exchange: Exchange identifier.
            internal_symbol: Internal normalized symbol.

        Returns:
            The latest InstrumentQuote, or None if not found.
        """
        key: StoreKey = (exchange, internal_symbol)
        async with self._lock:
            return self._data.get(key)

    async def get_all(self) -> List[InstrumentQuote]:
        """Retrieve all quotes currently in the store.

        Returns:
            List of all InstrumentQuote objects.
        """
        async with self._lock:
            return list(self._data.values())

    async def get_by_exchange(self, exchange: str) -> List[InstrumentQuote]:
        """Retrieve all quotes for a given exchange.

        Args:
            exchange: Exchange identifier.

        Returns:
            List of InstrumentQuote objects for the exchange.
        """
        async with self._lock:
            return [q for q in self._data.values() if q.exchange == exchange]

    async def get_by_asset(self, asset: str) -> List[InstrumentQuote]:
        """Retrieve all quotes for a given asset across all exchanges.

        Args:
            asset: Base asset symbol (e.g. 'BTC').

        Returns:
            List of InstrumentQuote objects for the asset.
        """
        async with self._lock:
            return [q for q in self._data.values() if q.asset == asset]

    async def size(self) -> int:
        """Return the number of quotes in the store."""
        async with self._lock:
            return len(self._data)

    async def clear(self) -> None:
        """Remove all quotes from the store."""
        async with self._lock:
            self._data.clear()

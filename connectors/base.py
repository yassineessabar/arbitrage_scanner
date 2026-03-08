"""
connectors/base.py — Abstract base class for all exchange connectors.

Defines the interface every connector must implement. No connector
may import from another connector. All connectors import from this base.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class ExponentialBackoff:
    """Exponential backoff helper for reconnect logic.

    Starts at `base` seconds, doubles each attempt, caps at `maximum`.
    Resets on successful connection.
    """

    def __init__(self, base: float = 1.0, maximum: float = 60.0) -> None:
        self._base = base
        self._maximum = maximum
        self._current = base

    def next(self) -> float:
        """Return the next backoff interval and advance."""
        wait = self._current
        self._current = min(self._current * 2, self._maximum)
        return wait

    def reset(self) -> None:
        """Reset backoff to initial value."""
        self._current = self._base


# Type alias for the quote callback
QuoteCallback = Callable[[str, dict], Coroutine[Any, Any, None]]
# Signature: callback(exchange_id: str, raw_payload: dict) -> None


class BaseConnector(ABC):
    """Abstract base class for exchange WebSocket connectors.

    Each connector:
      - Connects to exchange WebSocket feeds (spot + futures)
      - Subscribes to ticker/book channels for configured symbols
      - Emits raw payloads via an async callback
      - Implements exponential backoff reconnect
      - Tracks connection state and last message time
      - Isolates errors — never crashes the system
    """

    def __init__(self, exchange_id: str) -> None:
        self.exchange_id: str = exchange_id
        self._callback: Optional[QuoteCallback] = None
        self._connected: bool = False
        self._last_message_time: Optional[datetime] = None
        self._backoff = ExponentialBackoff(base=1.0, maximum=60.0)
        self._running: bool = False

    # ── Abstract Interface ──

    @abstractmethod
    async def connect(self) -> None:
        """Establish WebSocket connections to the exchange."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close all WebSocket connections."""
        ...

    @abstractmethod
    async def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to market data channels for given symbols.

        Args:
            symbols: List of internal symbols (e.g. ['BTC/USDT', 'ETH/USDT']).
        """
        ...

    @abstractmethod
    async def _listen(self) -> None:
        """Main listen loop — receive and dispatch messages."""
        ...

    # ── Public Interface ──

    def set_callback(self, callback: QuoteCallback) -> None:
        """Register the quote callback that receives raw payloads.

        Args:
            callback: Async function(exchange_id, raw_payload) -> None.
        """
        self._callback = callback

    @property
    def is_connected(self) -> bool:
        """Whether the connector currently has an active connection."""
        return self._connected

    @property
    def last_message_time(self) -> Optional[datetime]:
        """Timestamp of the last received message."""
        return self._last_message_time

    async def emit(self, raw_payload: dict) -> None:
        """Emit a raw payload to the registered callback.

        Args:
            raw_payload: Exchange-specific message payload.
        """
        self._last_message_time = datetime.now(timezone.utc)
        if self._callback is not None:
            try:
                await self._callback(self.exchange_id, raw_payload)
            except Exception as e:
                logger.error(
                    "callback_error",
                    exchange=self.exchange_id,
                    error=str(e),
                )

    async def run(self) -> None:
        """Run the connector with automatic reconnection.

        This is the main entry point — call this as an asyncio task.
        It handles connect, subscribe, listen, and reconnect on failure.
        """
        self._running = True
        while self._running:
            try:
                await self.connect()
                self._backoff.reset()
                logger.info("connector_connected", exchange=self.exchange_id)
                await self._listen()
            except asyncio.CancelledError:
                logger.info("connector_cancelled", exchange=self.exchange_id)
                self._running = False
                break
            except Exception as e:
                wait = self._backoff.next()
                logger.warning(
                    "connector_disconnected",
                    exchange=self.exchange_id,
                    error=str(e),
                    reconnect_in=wait,
                )
                self._connected = False
                await asyncio.sleep(wait)
            finally:
                try:
                    await self.disconnect()
                except Exception:
                    pass

    async def stop(self) -> None:
        """Signal the connector to stop its run loop."""
        self._running = False
        await self.disconnect()

"""
connectors/binance.py — Binance WebSocket connector for spot + futures.

Connects to:
  - Spot:    wss://stream.binance.com:9443/ws
  - Futures: wss://fstream.binance.com/ws

Subscribes to bookTicker streams for real-time bid/ask data
and 24hr ticker for volume information.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

from connectors.base import BaseConnector

logger = structlog.get_logger(__name__)

SPOT_WS_URL = "wss://stream.binance.com:9443/ws"
FUTURES_WS_URL = "wss://fstream.binance.com/ws"
PING_INTERVAL = 30


class BinanceConnector(BaseConnector):
    """Binance WebSocket connector for spot and futures market data.

    Subscribes to bookTicker (best bid/ask) and ticker_24hr (volume)
    streams for both spot and futures instruments.
    """

    def __init__(self) -> None:
        super().__init__(exchange_id="binance")
        self._spot_ws: Optional[Any] = None
        self._futures_ws: Optional[Any] = None
        self._symbols: List[str] = []
        self._spot_id: int = 1
        self._futures_id: int = 1

    async def connect(self) -> None:
        """Establish WebSocket connections to Binance spot and futures."""
        self._spot_ws = await websockets.connect(
            SPOT_WS_URL,
            ping_interval=PING_INTERVAL,
            ping_timeout=10,
            close_timeout=5,
        )
        self._futures_ws = await websockets.connect(
            FUTURES_WS_URL,
            ping_interval=PING_INTERVAL,
            ping_timeout=10,
            close_timeout=5,
        )
        self._connected = True
        logger.info("binance_connected", spot=True, futures=True)

    async def disconnect(self) -> None:
        """Close all Binance WebSocket connections."""
        self._connected = False
        for ws, label in [(self._spot_ws, "spot"), (self._futures_ws, "futures")]:
            if ws is not None:
                try:
                    await ws.close()
                except Exception as e:
                    logger.debug("binance_close_error", feed=label, error=str(e))
        self._spot_ws = None
        self._futures_ws = None

    async def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to bookTicker and 24hrTicker for given symbols.

        Args:
            symbols: Internal symbols like ['BTC/USDT', 'ETH/USDT'].
                     Converted to Binance format (e.g. 'btcusdt').
        """
        self._symbols = symbols

        # Build Binance stream names
        spot_streams: List[str] = []
        futures_streams: List[str] = []

        for sym in symbols:
            # Convert BTC/USDT → btcusdt
            base = sym.replace("/", "").lower()
            spot_streams.append(f"{base}@bookTicker")
            spot_streams.append(f"{base}@ticker")
            futures_streams.append(f"{base}@bookTicker")
            futures_streams.append(f"{base}@ticker")

        # Subscribe to spot streams
        if self._spot_ws and spot_streams:
            msg = {
                "method": "SUBSCRIBE",
                "params": spot_streams,
                "id": self._spot_id,
            }
            await self._spot_ws.send(json.dumps(msg))
            self._spot_id += 1
            logger.info("binance_subscribed", feed="spot", streams=len(spot_streams))

        # Subscribe to futures streams
        if self._futures_ws and futures_streams:
            msg = {
                "method": "SUBSCRIBE",
                "params": futures_streams,
                "id": self._futures_id,
            }
            await self._futures_ws.send(json.dumps(msg))
            self._futures_id += 1
            logger.info("binance_subscribed", feed="futures", streams=len(futures_streams))

    async def _listen(self) -> None:
        """Listen on both spot and futures WebSockets concurrently."""
        await self.subscribe(self._symbols)

        async def _listen_ws(ws: Any, feed_type: str) -> None:
            """Listen loop for a single WebSocket."""
            try:
                async for message in ws:
                    try:
                        data = json.loads(message)
                        # Skip subscription confirmations
                        if "result" in data and data.get("id"):
                            continue
                        data["_feed_type"] = feed_type
                        data["_exchange"] = "binance"
                        await self.emit(data)
                    except json.JSONDecodeError:
                        logger.warning("binance_invalid_json", feed=feed_type)
            except ConnectionClosed as e:
                logger.warning("binance_ws_closed", feed=feed_type, code=e.code)
                raise

        await asyncio.gather(
            _listen_ws(self._spot_ws, "spot"),
            _listen_ws(self._futures_ws, "futures"),
        )

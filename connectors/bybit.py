"""
connectors/bybit.py — Bybit V5 WebSocket connector for spot + futures.

Connects to:
  - Public: wss://stream.bybit.com/v5/public/spot
  - Public: wss://stream.bybit.com/v5/public/linear

Subscribes to tickers stream for real-time bid/ask and volume data.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, List, Optional

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

from connectors.base import BaseConnector

logger = structlog.get_logger(__name__)

SPOT_WS_URL = "wss://stream.bybit.com/v5/public/spot"
LINEAR_WS_URL = "wss://stream.bybit.com/v5/public/linear"
PING_INTERVAL = 20


class BybitConnector(BaseConnector):
    """Bybit V5 WebSocket connector for spot and linear futures.

    Subscribes to tickers topic for best bid/ask and 24h volume
    across spot and linear (USDT perpetual + dated futures) instruments.
    """

    def __init__(self) -> None:
        super().__init__(exchange_id="bybit")
        self._spot_ws: Optional[Any] = None
        self._linear_ws: Optional[Any] = None
        self._symbols: List[str] = []

    async def connect(self) -> None:
        """Establish WebSocket connections to Bybit spot and linear."""
        self._spot_ws = await websockets.connect(
            SPOT_WS_URL,
            ping_interval=PING_INTERVAL,
            ping_timeout=10,
            close_timeout=5,
        )
        self._linear_ws = await websockets.connect(
            LINEAR_WS_URL,
            ping_interval=PING_INTERVAL,
            ping_timeout=10,
            close_timeout=5,
        )
        self._connected = True
        logger.info("bybit_connected", spot=True, linear=True)

    async def disconnect(self) -> None:
        """Close all Bybit WebSocket connections."""
        self._connected = False
        for ws, label in [(self._spot_ws, "spot"), (self._linear_ws, "linear")]:
            if ws is not None:
                try:
                    await ws.close()
                except Exception as e:
                    logger.debug("bybit_close_error", feed=label, error=str(e))
        self._spot_ws = None
        self._linear_ws = None

    async def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to tickers for given symbols.

        Args:
            symbols: Internal symbols like ['BTC/USDT', 'ETH/USDT'].
                     Converted to Bybit format (e.g. 'BTCUSDT').
        """
        self._symbols = symbols

        spot_topics: List[str] = []
        linear_topics: List[str] = []

        for sym in symbols:
            base = sym.replace("/", "")
            spot_topics.append(f"tickers.{base}")
            linear_topics.append(f"tickers.{base}")

        # Subscribe spot
        if self._spot_ws and spot_topics:
            msg = {"op": "subscribe", "args": spot_topics}
            await self._spot_ws.send(json.dumps(msg))
            logger.info("bybit_subscribed", feed="spot", topics=len(spot_topics))

        # Subscribe linear
        if self._linear_ws and linear_topics:
            msg = {"op": "subscribe", "args": linear_topics}
            await self._linear_ws.send(json.dumps(msg))
            logger.info("bybit_subscribed", feed="linear", topics=len(linear_topics))

    async def _listen(self) -> None:
        """Listen on both spot and linear WebSockets concurrently."""
        await self.subscribe(self._symbols)

        async def _listen_ws(ws: Any, feed_type: str) -> None:
            """Listen loop for a single WebSocket."""
            try:
                async for message in ws:
                    try:
                        data = json.loads(message)
                        # Skip subscription confirmations and pong
                        if data.get("op") in ("subscribe", "pong"):
                            if not data.get("success", True):
                                logger.warning(
                                    "bybit_subscribe_failed",
                                    feed=feed_type,
                                    msg=data.get("ret_msg"),
                                )
                            continue

                        # Only process ticker data
                        topic = data.get("topic", "")
                        if "tickers" not in topic:
                            continue

                        data["_feed_type"] = feed_type
                        data["_exchange"] = "bybit"
                        await self.emit(data)
                    except json.JSONDecodeError:
                        logger.warning("bybit_invalid_json", feed=feed_type)
            except ConnectionClosed as e:
                logger.warning("bybit_ws_closed", feed=feed_type, code=e.code)
                raise

        # Send periodic pings (Bybit requires app-level ping)
        async def _heartbeat(ws: Any, feed_type: str) -> None:
            """Send periodic ping messages."""
            while self._connected:
                try:
                    await ws.send(json.dumps({"op": "ping"}))
                    await asyncio.sleep(PING_INTERVAL)
                except Exception:
                    break

        await asyncio.gather(
            _listen_ws(self._spot_ws, "spot"),
            _listen_ws(self._linear_ws, "linear"),
            _heartbeat(self._spot_ws, "spot"),
            _heartbeat(self._linear_ws, "linear"),
        )

"""
connectors/okx.py — OKX V5 WebSocket connector for spot + futures.

Connects to:
  - Public: wss://ws.okx.com:8443/ws/v5/public

OKX uses a single endpoint with instType to differentiate
SPOT, FUTURES, and SWAP instruments.
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

WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
PING_INTERVAL = 25


class OKXConnector(BaseConnector):
    """OKX V5 WebSocket connector for spot, futures, and swap instruments.

    OKX uses a single public WebSocket endpoint. Instrument types are
    differentiated by instType in subscription arguments.
    """

    def __init__(self) -> None:
        super().__init__(exchange_id="okx")
        self._ws: Optional[Any] = None
        self._symbols: List[str] = []

    async def connect(self) -> None:
        """Establish WebSocket connection to OKX public endpoint."""
        self._ws = await websockets.connect(
            WS_URL,
            ping_interval=PING_INTERVAL,
            ping_timeout=10,
            close_timeout=5,
        )
        self._connected = True
        logger.info("okx_connected")

    async def disconnect(self) -> None:
        """Close OKX WebSocket connection."""
        self._connected = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception as e:
                logger.debug("okx_close_error", error=str(e))
        self._ws = None

    async def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to tickers for spot, futures, and swap instruments.

        Args:
            symbols: Internal symbols like ['BTC/USDT', 'ETH/USDT'].
                     Converted to OKX format (e.g. 'BTC-USDT').
        """
        self._symbols = symbols

        args: List[dict] = []

        for sym in symbols:
            # Convert BTC/USDT → BTC-USDT
            parts = sym.split("/")
            if len(parts) != 2:
                continue
            okx_sym = f"{parts[0]}-{parts[1]}"

            # Spot tickers
            args.append({"channel": "tickers", "instId": okx_sym})
            # Swap (perpetual) tickers
            args.append({"channel": "tickers", "instId": f"{okx_sym}-SWAP"})

        if self._ws and args:
            msg = {"op": "subscribe", "args": args}
            await self._ws.send(json.dumps(msg))
            logger.info("okx_subscribed", channels=len(args))

    async def _subscribe_futures(self) -> None:
        """Subscribe to dated futures instruments via instType filter.

        OKX dated futures have dynamic instIds (e.g. BTC-USDT-250627).
        We subscribe to the FUTURES instType tickers channel.
        """
        if self._ws is None:
            return

        args: List[dict] = []
        for sym in self._symbols:
            parts = sym.split("/")
            if len(parts) != 2:
                continue
            okx_sym = f"{parts[0]}-{parts[1]}"
            args.append({
                "channel": "tickers",
                "instType": "FUTURES",
                "instFamily": okx_sym,
            })

        if args:
            msg = {"op": "subscribe", "args": args}
            await self._ws.send(json.dumps(msg))
            logger.info("okx_subscribed_futures", channels=len(args))

    async def _listen(self) -> None:
        """Listen on the OKX WebSocket."""
        await self.subscribe(self._symbols)
        await self._subscribe_futures()

        async def _listen_loop() -> None:
            """Main message processing loop."""
            if self._ws is None:
                return
            try:
                async for message in self._ws:
                    # OKX sends "pong" as plain text
                    if message == "pong":
                        continue
                    try:
                        data = json.loads(message)
                        # Handle subscription events
                        event = data.get("event")
                        if event == "subscribe":
                            logger.debug("okx_sub_confirmed", arg=data.get("arg"))
                            continue
                        if event == "error":
                            logger.warning(
                                "okx_error",
                                code=data.get("code"),
                                msg=data.get("msg"),
                            )
                            continue

                        # Process ticker data
                        if "data" in data and "arg" in data:
                            data["_exchange"] = "okx"
                            await self.emit(data)
                    except json.JSONDecodeError:
                        logger.warning("okx_invalid_json")
            except ConnectionClosed as e:
                logger.warning("okx_ws_closed", code=e.code)
                raise

        async def _heartbeat() -> None:
            """Send periodic ping messages (OKX expects plain 'ping')."""
            while self._connected and self._ws is not None:
                try:
                    await self._ws.send("ping")
                    await asyncio.sleep(PING_INTERVAL)
                except Exception:
                    break

        await asyncio.gather(_listen_loop(), _heartbeat())

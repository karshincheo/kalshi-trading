"""
Kalshi WebSocket client for real-time market data.

Kalshi WS endpoint: wss://trading-api.kalshi.com/trade-api/ws/v2
Demo WS endpoint: wss://demo-trading-api.kalshi.co/trade-api/ws/v2

Subscription channels:
  - ticker: real-time price updates (bid/ask/last)
  - orderbook_delta: incremental L2 orderbook updates
  - trade: fills (authenticated only)

This client maintains an in-memory market cache and calls
registered callbacks when prices update.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed

log = logging.getLogger(__name__)

# WS endpoints
LIVE_WS_URL = "wss://trading-api.kalshi.com/trade-api/ws/v2"
DEMO_WS_URL = "wss://demo-trading-api.kalshi.co/trade-api/ws/v2"


class KalshiWebSocketClient:
    """
    Connects to Kalshi WebSocket feed and pushes market updates
    to registered callback functions.
    """

    def __init__(
        self,
        demo: bool = True,
        on_ticker_update: Optional[Callable] = None,
        on_orderbook_update: Optional[Callable] = None,
    ) -> None:
        self._url = DEMO_WS_URL if demo else LIVE_WS_URL
        self._on_ticker = on_ticker_update
        self._on_orderbook = on_orderbook_update
        self._subscribed_tickers: set[str] = set()
        self._running = False
        self._ws = None
        self._seq = 0

    async def connect(self) -> None:
        self._running = True
        while self._running:
            try:
                async with websockets.connect(
                    self._url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    log.info("Kalshi WS connected to %s", self._url)
                    # Re-subscribe after reconnect
                    if self._subscribed_tickers:
                        await self._subscribe(list(self._subscribed_tickers))
                    await self._listen(ws)
            except ConnectionClosed as e:
                log.warning("WS connection closed: %s. Reconnecting in 5s...", e)
                await asyncio.sleep(5)
            except Exception as e:
                log.error("WS error: %s. Reconnecting in 10s...", e)
                await asyncio.sleep(10)

    async def _listen(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
                await self._handle_message(msg)
            except Exception as e:
                log.debug("WS parse error: %s", e)

    async def _handle_message(self, msg: dict) -> None:
        msg_type = msg.get("type")
        if msg_type == "ticker":
            if self._on_ticker:
                await self._on_ticker(msg)
        elif msg_type in ("orderbook_snapshot", "orderbook_delta"):
            if self._on_orderbook:
                await self._on_orderbook(msg)

    async def subscribe(self, tickers: list[str]) -> None:
        self._subscribed_tickers.update(tickers)
        if self._ws:
            await self._subscribe(tickers)

    async def _subscribe(self, tickers: list[str]) -> None:
        self._seq += 1
        msg = {
            "id": self._seq,
            "cmd": "subscribe",
            "params": {
                "channels": ["ticker"],
                "market_tickers": tickers,
            },
        }
        if self._ws:
            await self._ws.send(json.dumps(msg))

    async def disconnect(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()

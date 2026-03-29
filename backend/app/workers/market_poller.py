"""
Market Poller — Periodically fetches market data from Kalshi API.

In paper mode: fetches public market data (no auth needed) to keep
the paper broker's market cache current. This enables realistic
paper trading simulation.

In demo/live mode: also fetches private data (positions, balance).
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.broker.kalshi_client import KalshiClient

if TYPE_CHECKING:
    from app.broker.base import IBroker

log = logging.getLogger(__name__)

# Public Kalshi client for market data (no auth)
_public_client = KalshiClient(
    base_url="https://trading-api.kalshi.com/trade-api/v2"
)


class MarketPoller:
    """
    Fetches live market data from Kalshi and updates the broker's cache.
    """

    def __init__(self, broker: "IBroker", poll_interval: int = 30) -> None:
        self._broker = broker
        self._poll_interval = poll_interval
        self._running = False

    async def start(self) -> None:
        self._running = True
        log.info("Market poller started (interval=%ds)", self._poll_interval)
        while self._running:
            try:
                await self._poll()
            except Exception as e:
                log.error("Market poller error: %s", e)
            await asyncio.sleep(self._poll_interval)

    async def _poll(self) -> None:
        """Fetch markets and update broker cache."""
        markets = await _public_client.get_markets(status="active", limit=200)
        log.debug("Polled %d markets from Kalshi", len(markets))

        # Update paper broker's market cache
        if hasattr(self._broker, 'update_market'):
            for market in markets:
                self._broker.update_market(market)

    def stop(self) -> None:
        self._running = False

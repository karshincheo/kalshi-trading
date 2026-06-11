"""
Kalshi temperature market data collector.

Polls the public Kalshi API for temperature markets, captures snapshots
(prices, orderbooks, settlements), and stores them as Parquet files.

Designed to run continuously or as a one-shot backfill.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

from app.autoresearch.config import AutoresearchSettings
from app.autoresearch.market_filter import (
    is_temperature_market,
    parse_temperature_market,
)
from app.schemas.market import MarketOut

logger = logging.getLogger(__name__)

KALSHI_PUBLIC_BASE = "https://trading-api.kalshi.com/trade-api/v2"


class TemperatureMarketCollector:
    """Collects and persists Kalshi temperature market data."""

    def __init__(self, config: AutoresearchSettings) -> None:
        self.config = config
        self.cache_dir = Path(config.kalshi_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(
            base_url=config.kalshi_api_base,
            timeout=15.0,
        )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def collect_once(self) -> int:
        """
        Run a single collection cycle.

        Returns number of temperature market snapshots captured.
        """
        markets = self._fetch_temperature_markets()
        if not markets:
            logger.info("No temperature markets found.")
            return 0

        now = datetime.now(timezone.utc)
        snapshots = []

        for market in markets:
            parsed = parse_temperature_market(market)
            if not parsed:
                continue

            orderbook = self._fetch_orderbook(market.ticker)
            time.sleep(0.15)  # pace orderbook calls under the public rate limit

            snapshots.append({
                "timestamp": now.isoformat(),
                "ticker": market.ticker,
                "event_ticker": market.event_ticker,
                "title": market.title,
                "city": parsed["city"],
                "target_date": parsed["target_date"].isoformat(),
                "strike_temp_f": parsed["strike_temp_f"],
                "is_high": parsed["is_high"],
                "status": market.status,
                "yes_bid": market.yes_bid,
                "yes_ask": market.yes_ask,
                "yes_mid": market.yes_mid,
                "last_price": market.last_price,
                "volume_24h": market.volume_24h,
                "open_interest": market.open_interest,
                "close_time": market.close_time.isoformat() if market.close_time else None,
                "result": market.result,
                "bids_json": json.dumps(orderbook["bids"]) if orderbook else None,
                "asks_json": json.dumps(orderbook["asks"]) if orderbook else None,
            })

        if not snapshots:
            return 0

        df = pd.DataFrame(snapshots)
        self._append_snapshots(df, now)
        logger.info("Collected %d temperature market snapshots.", len(snapshots))
        return len(snapshots)

    def collect_settlements(self) -> int:
        """Check for recently settled temperature markets and record outcomes."""
        markets = self._fetch_temperature_markets(status="settled")
        if not markets:
            return 0

        settlements = []
        for market in markets:
            parsed = parse_temperature_market(market)
            if not parsed or market.result is None:
                continue
            settlements.append({
                "ticker": market.ticker,
                "city": parsed["city"],
                "target_date": parsed["target_date"].isoformat(),
                "strike_temp_f": parsed["strike_temp_f"],
                "is_high": parsed["is_high"],
                "result": market.result,  # "yes" or "no"
                "settled_at": datetime.now(timezone.utc).isoformat(),
            })

        if not settlements:
            return 0

        df = pd.DataFrame(settlements)
        path = self.cache_dir / "settlements.parquet"
        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df]).drop_duplicates(subset=["ticker"])
        df.to_parquet(path, index=False)
        logger.info("Recorded %d settlements.", len(settlements))
        return len(settlements)

    def run_continuous(self, interval_seconds: Optional[int] = None) -> None:
        """Run collector in a loop. Blocking call."""
        interval = interval_seconds or self.config.collector_interval_seconds
        logger.info("Starting continuous collection every %ds...", interval)
        try:
            while True:
                try:
                    self.collect_once()
                    self.collect_settlements()
                except Exception:
                    logger.exception("Collection cycle failed.")
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Collector stopped.")
        finally:
            self.close()

    def load_all_snapshots(self) -> pd.DataFrame:
        """Load all collected snapshots into a single DataFrame."""
        parquet_files = sorted(self.cache_dir.glob("snapshots_*.parquet"))
        if not parquet_files:
            return pd.DataFrame()
        dfs = [pd.read_parquet(f) for f in parquet_files]
        return pd.concat(dfs, ignore_index=True)

    def load_settlements(self) -> pd.DataFrame:
        """Load all settlement records."""
        path = self.cache_dir / "settlements.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_temperature_series(self) -> list[str]:
        """List temperature series tickers from the Climate and Weather category."""
        try:
            resp = self._client.get("/series", params={"category": "Climate and Weather"})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Kalshi series API error: %s", e)
            return []
        tickers = [s.get("ticker", "") for s in resp.json().get("series", [])]
        return [t for t in tickers if "HIGH" in t or "LOW" in t or "TEMP" in t]

    def _fetch_temperature_markets(self, status: str = "open") -> list[MarketOut]:
        """Fetch temperature markets per series — far fewer requests than
        paginating the whole market list, which both rate-limits and can bury
        temperature markets past the page cap."""
        all_markets = []
        for series in self._fetch_temperature_series():
            try:
                resp = self._client.get(
                    "/markets",
                    params={"limit": 200, "status": status, "series_ticker": series},
                )
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("Kalshi API error for series %s: %s", series, e)
                continue
            for m in resp.json().get("markets", []):
                market = _parse_market_dict(m)
                if is_temperature_market(market):
                    all_markets.append(market)
            time.sleep(0.25)  # stay friendly with the public rate limit

        logger.info("Found %d temperature markets (status=%s).", len(all_markets), status)
        return all_markets

    def _fetch_orderbook(self, ticker: str) -> Optional[dict]:
        """Fetch L2 orderbook for a single ticker."""
        try:
            resp = self._client.get(f"/markets/{ticker}/orderbook")
            resp.raise_for_status()
            data = resp.json()
            ob = data.get("orderbook", data)
            return {
                "bids": [[lvl.get("price", 0), lvl.get("quantity", 0)] for lvl in (ob.get("yes", []) or [])],
                "asks": [[lvl.get("price", 0), lvl.get("quantity", 0)] for lvl in (ob.get("no", []) or [])],
            }
        except httpx.HTTPError:
            return None

    def _append_snapshots(self, df: pd.DataFrame, ts: datetime) -> None:
        """Append snapshot DataFrame to a date-partitioned Parquet file."""
        date_str = ts.strftime("%Y-%m-%d")
        path = self.cache_dir / f"snapshots_{date_str}.parquet"
        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df], ignore_index=True)
        df.to_parquet(path, index=False)


def _parse_market_dict(m: dict) -> MarketOut:
    """Parse a raw Kalshi API market dict into MarketOut. Mirrors KalshiClient._parse_market."""
    yes_bid = m.get("yes_bid") or m.get("yes_bid_price")
    yes_ask = m.get("yes_ask") or m.get("yes_ask_price")
    if yes_bid is not None:
        yes_bid = yes_bid / 100
    if yes_ask is not None:
        yes_ask = yes_ask / 100
    close_time = m.get("close_time") or m.get("expiration_time")
    return MarketOut(
        ticker=m.get("ticker", ""),
        event_ticker=m.get("event_ticker", ""),
        title=m.get("title", ""),
        subtitle=m.get("subtitle"),
        category=m.get("category"),
        status=m.get("status", "active"),
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        yes_mid=((yes_bid or 0) + (yes_ask or 1)) / 2 if yes_bid and yes_ask else None,
        last_price=(m.get("last_price") or 0) / 100 if m.get("last_price") else None,
        volume_24h=m.get("volume_24h") or m.get("volume"),
        open_interest=m.get("open_interest"),
        close_time=datetime.fromisoformat(close_time.replace("Z", "+00:00")) if close_time else None,
        result=m.get("result"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

"""
Nowcasting Strategy — Real-time macro signal trading.

Core idea from the research report:
  Economic data (CPI, jobs, Fed rate) is released on a schedule.
  Before the official release, Kalshi markets price in consensus.
  Real-time disaggregated data (BLS microdata, fed funds futures,
  state unemployment filings) can improve the forecast BEFORE
  the market updates.

  Edge: If our nowcast differs from market price by > threshold,
  trade in the direction of our nowcast.

Data sources:
  - BLS API: real-time economic releases (CPI, PPI, jobs)
  - FRED API: Fed Funds rate, PCE, GDP estimates
  - State-level data: weekly initial claims (leading indicator for monthly)

Approach:
  1. Identify Kalshi markets related to upcoming economic releases
  2. Pull real-time data for relevant indicators
  3. Run simple nowcast model (Kalman filter or weighted average)
  4. If nowcast probability ≠ market price by > min_edge: signal

In paper/demo mode without BLS API key:
  Strategy uses a simulated nowcast based on market price deviation
  from recent historical average (mean-reversion signal).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from app.core.strategies.base import AbstractStrategy, Signal
from app.schemas.market import MarketOut


# Keywords that identify economic indicator markets
ECON_KEYWORDS = {
    "cpi": ["cpi", "inflation", "consumer price"],
    "jobs": ["jobs", "employment", "unemployment", "nonfarm", "payroll"],
    "fed": ["federal reserve", "fed rate", "fomc", "interest rate", "fed funds"],
    "gdp": ["gdp", "gross domestic"],
    "pce": ["pce", "personal consumption"],
}


class NowcastingStrategy(AbstractStrategy):
    name = "nowcasting"
    display_name = "Nowcasting (Macro Real-Time Signals)"
    description = (
        "Trades economic indicator markets using real-time BLS/FRED data. "
        "Generates signals when the nowcast model disagrees with Kalshi prices "
        "before official data releases."
    )

    DEFAULT_PARAMS: dict[str, Any] = {
        "min_edge_bps": 300,             # Minimum nowcast edge to trade
        "max_days_before_release": 3,    # Only trade near release date
        "categories": ["economics"],     # Kalshi categories to scan
        "mean_reversion_window": 14,     # Days for mean-reversion baseline
        "mean_reversion_alpha": 0.3,     # Weight on mean-reversion signal
        "confidence_base": 0.55,
        "use_bls_api": False,            # Set True when BLS API key is configured
    }

    def __init__(self, params: Optional[dict[str, Any]] = None) -> None:
        super().__init__(params)
        self._price_history: dict[str, list[float]] = {}
        self._nowcast_cache: dict[str, float] = {}

    def fit(self, historical_markets: list[MarketOut]) -> None:
        """Build price history for mean-reversion baseline."""
        from collections import defaultdict
        history: dict[str, list[float]] = defaultdict(list)
        for m in historical_markets:
            if m.yes_mid:
                history[m.ticker].append(m.yes_mid)
        self._price_history = dict(history)

    def reset(self) -> None:
        self._nowcast_cache = {}

    def generate_signals(
        self,
        markets: list[MarketOut],
        portfolio_equity: float,
    ) -> list[Signal]:
        signals = []
        target_categories = set(self.params.get("categories", ["economics"]))
        now = datetime.now(timezone.utc)

        for market in markets:
            if market.status != "active":
                continue
            if market.category not in target_categories:
                continue

            yes_mid = market.yes_mid
            if yes_mid is None:
                continue

            # Check if market is related to an upcoming release
            title_lower = market.title.lower()
            release_type = None
            for rtype, keywords in ECON_KEYWORDS.items():
                if any(kw in title_lower for kw in keywords):
                    release_type = rtype
                    break

            if release_type is None:
                continue

            # Check proximity to close time
            if market.close_time:
                days_to_close = (market.close_time - now).total_seconds() / 86400
                if days_to_close > self.params["max_days_before_release"]:
                    continue
                if days_to_close < 0:
                    continue

            # Generate nowcast estimate
            nowcast = self._compute_nowcast(market.ticker, yes_mid, release_type)

            if nowcast is None:
                continue

            edge = nowcast - yes_mid
            edge_bps = abs(edge) * 10_000

            if edge_bps < self.params["min_edge_bps"]:
                continue

            confidence = min(
                0.85,
                self.params["confidence_base"] + edge_bps * 0.00005
            )

            direction = "buy_yes" if edge > 0 else "buy_no"
            market_price = yes_mid if edge > 0 else (1.0 - yes_mid)

            signals.append(Signal(
                ticker=market.ticker,
                direction=direction,
                fair_value=nowcast,
                market_price=market_price,
                edge=abs(edge),
                confidence=confidence,
                strategy_name=self.name,
                metadata={
                    "release_type": release_type,
                    "nowcast": nowcast,
                    "market_price": yes_mid,
                    "edge_bps": edge_bps,
                    "source": "mean_reversion" if not self.params["use_bls_api"] else "bls_api",
                },
            ))

        return signals

    def _compute_nowcast(
        self,
        ticker: str,
        current_price: float,
        release_type: str,
    ) -> Optional[float]:
        """
        Compute nowcast probability estimate.

        Without BLS/FRED API: uses mean-reversion to historical average.
        With API: uses weighted combination of API data + Kalman filter.
        """
        history = self._price_history.get(ticker, [])
        window = self.params["mean_reversion_window"]

        if not self.params["use_bls_api"]:
            # Mean-reversion baseline
            if len(history) < 5:
                return None

            recent = history[-window:] if len(history) >= window else history
            mean_price = sum(recent) / len(recent)

            # Nowcast: blend current price with historical mean
            alpha = self.params["mean_reversion_alpha"]
            nowcast = alpha * mean_price + (1 - alpha) * current_price

            return nowcast

        # When BLS API is configured, this would call bls_client and fred_client
        # For now: placeholder that returns current price (no signal)
        return None

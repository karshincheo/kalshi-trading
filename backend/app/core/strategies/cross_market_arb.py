"""
Cross-Market Arbitrage: Kalshi vs Polymarket.

When the same event is traded on both Kalshi and Polymarket,
price divergences create risk-free (or near risk-free) arbitrage.

Example:
  Kalshi: "Will X happen?" YES at 0.60
  Polymarket: "Will X happen?" YES at 0.65

  Buy YES on Kalshi at 0.60, sell YES on Polymarket at 0.65.
  If X happens: Kalshi pays $1, Polymarket costs $1 → flat.
  If X doesn't: Kalshi loses $0.60, Polymarket gains $0.65 → +$0.05.

  But: prices converge before resolution, so we can close both legs
  at any time if we capture the spread.

Practical considerations:
  - Polymarket uses USDC on Polygon (crypto settlement)
  - Kalshi uses USD (cash settlement)
  - Cross-chain settlement risk and timing risk
  - In practice: we only signal arbitrage, not auto-execute both legs

Strategy: identify Kalshi markets with matching Polymarket markets,
compute spread, signal if spread > threshold.

In this implementation, we match markets by:
1. Title similarity (fuzzy string matching)
2. Close time proximity (within 7 days)
3. Price spread > min_spread_bps
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.core.strategies.base import AbstractStrategy, Signal
from app.schemas.market import MarketOut


class CrossMarketArbStrategy(AbstractStrategy):
    name = "cross_market_arb"
    display_name = "Cross-Market Arbitrage (Kalshi vs Polymarket)"
    description = (
        "Identifies price discrepancies between identical events on Kalshi and Polymarket. "
        "Signals when the spread exceeds transaction costs and is large enough to capture."
    )

    DEFAULT_PARAMS: dict[str, Any] = {
        "min_spread_bps": 300,      # Minimum spread to signal (covers fees + slippage)
        "max_close_time_diff_days": 7,  # Max days between close times to match
        "min_similarity_score": 0.7,   # Minimum title similarity (0-1)
        "confidence_per_bps": 0.002,
        "confidence_base": 0.75,
    }

    def __init__(self, params: Optional[dict[str, Any]] = None) -> None:
        super().__init__(params)
        self._polymarket_prices: dict[str, dict] = {}  # Loaded by data sync service

    def update_polymarket_prices(self, prices: dict[str, dict]) -> None:
        """Called by data_sync_service with latest Polymarket prices."""
        self._polymarket_prices = prices

    def generate_signals(
        self,
        markets: list[MarketOut],
        portfolio_equity: float,
    ) -> list[Signal]:
        signals = []

        if not self._polymarket_prices:
            return signals

        for market in markets:
            if market.status != "active":
                continue

            yes_mid = market.yes_mid
            if yes_mid is None:
                continue

            # Try to find a matching Polymarket market
            poly_match = self._find_polymarket_match(market)
            if poly_match is None:
                continue

            poly_price = poly_match.get("price", None)
            if poly_price is None:
                continue

            spread = poly_price - yes_mid  # positive: Polymarket higher → buy on Kalshi
            spread_bps = abs(spread) * 10_000

            if spread_bps < self.params["min_spread_bps"]:
                continue

            confidence = min(
                0.90,
                self.params["confidence_base"] + spread_bps * self.params["confidence_per_bps"],
            )

            if spread > 0:
                # Kalshi underpriced vs Polymarket → buy YES on Kalshi
                direction = "buy_yes"
                market_price = yes_mid
                fair_value = poly_price  # Polymarket is our reference
            else:
                # Kalshi overpriced vs Polymarket → sell YES on Kalshi
                direction = "sell_yes"
                market_price = yes_mid
                fair_value = poly_price

            signals.append(Signal(
                ticker=market.ticker,
                direction=direction,
                fair_value=fair_value,
                market_price=market_price,
                edge=abs(spread),
                confidence=confidence,
                strategy_name=self.name,
                metadata={
                    "kalshi_price": yes_mid,
                    "polymarket_price": poly_price,
                    "spread_bps": spread_bps,
                    "polymarket_slug": poly_match.get("slug"),
                    "arb_type": "buy_kalshi" if spread > 0 else "sell_kalshi",
                },
            ))

        return signals

    def _find_polymarket_match(self, market: MarketOut) -> Optional[dict]:
        """Find matching Polymarket market by title similarity."""
        best_score = 0.0
        best_match = None

        for poly_id, poly_data in self._polymarket_prices.items():
            score = self._title_similarity(
                market.title,
                poly_data.get("question", ""),
            )
            if score > best_score and score >= self.params["min_similarity_score"]:
                # Check close time proximity
                if market.close_time and poly_data.get("end_date"):
                    try:
                        poly_end = datetime.fromisoformat(
                            poly_data["end_date"].replace("Z", "+00:00")
                        )
                        diff_days = abs((market.close_time - poly_end).days)
                        if diff_days <= self.params["max_close_time_diff_days"]:
                            best_score = score
                            best_match = poly_data
                    except Exception:
                        pass
                else:
                    best_score = score
                    best_match = poly_data

        return best_match

    @staticmethod
    def _title_similarity(s1: str, s2: str) -> float:
        """Simple word overlap similarity."""
        if not s1 or not s2:
            return 0.0
        words1 = set(s1.lower().split())
        words2 = set(s2.lower().split())
        # Remove common stop words
        stop = {"will", "be", "the", "a", "an", "in", "on", "of", "to", "is", "or"}
        words1 -= stop
        words2 -= stop
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

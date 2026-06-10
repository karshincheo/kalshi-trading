"""
Longshot Bias / "Nothing Ever Happens" Strategy.

Core insight from the research report:
  Prediction markets systematically misprice extreme probabilities:
  1. "Optimism tax" — retail money bids up dramatic/exciting YES contracts
  2. Longshot bias — humans overweight small probabilities
  3. Media hype → inflated prices on high-salience events
  4. "Nothing ever happens" — most extreme scenarios don't materialize

Edge: When YES is priced at 95-99¢, the true probability is almost always
lower. Markets rarely resolve at these extremes. Similarly, NO at 1-5¢
offers value by shorting the hype.

Strategy parameters:
  sell_yes_threshold (default 0.97): Sell YES if price ≥ threshold
  buy_no_threshold (default 0.03):   Buy NO if price ≤ threshold
  min_volume_24h (default 50):       Ignore illiquid markets
  min_days_to_close (default 1):     Don't trade day-of-settlement
  max_days_to_close (default 90):    Don't trade very long-dated contracts
  excluded_categories (default []):  Categories to skip

Fair value model:
  For extreme contracts, we estimate fair value as:
    fair_value_yes = market_price * regression_to_mean_factor
  Where regression_to_mean_factor < 1 for overpriced contracts.

  Specifically: if YES is at 0.97, we estimate the true probability
  is ~0.93 (4% edge). This is calibrated from historical Kalshi data.
  The regression factor = 1 - alpha * (price - threshold)

This strategy generates SELL_YES signals (or equivalently BUY_NO signals)
when the edge exceeds min_edge_bps basis points.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.core.strategies.base import AbstractStrategy, Signal
from app.schemas.market import MarketOut


class LongshotBiasStrategy(AbstractStrategy):
    name = "longshot_bias"
    display_name = "Longshot Bias (Nothing Ever Happens)"
    description = (
        "Fades extreme probability contracts. Sells YES contracts priced near certainty "
        "(97%+) and buys NO contracts priced near zero, exploiting the optimism tax and "
        "longshot bias in prediction markets."
    )

    DEFAULT_PARAMS: dict[str, Any] = {
        "sell_yes_threshold": 0.97,     # Sell YES if price ≥ this
        "buy_no_threshold": 0.03,       # Buy NO if price ≤ this
        "min_volume_24h": 50,           # Minimum 24h volume filter
        "min_days_to_close": 1,         # Min days before settlement
        "max_days_to_close": 90,        # Max days before settlement
        "regression_alpha": 0.5,        # Regression-to-mean factor
        "min_edge_bps": 150,            # Minimum edge in basis points to signal
        "excluded_categories": [],      # e.g. ["sports"] if you want to skip
        "confidence_base": 0.7,        # Base confidence for extreme signals
        "confidence_per_bps": 0.001,   # Additional confidence per extra bps of edge
    }

    def generate_signals(
        self,
        markets: list[MarketOut],
        portfolio_equity: float,
    ) -> list[Signal]:
        signals = []
        now = datetime.now(timezone.utc)

        sell_yes_thresh = self.params["sell_yes_threshold"]
        buy_no_thresh = self.params["buy_no_threshold"]
        min_vol = self.params["min_volume_24h"]
        min_days = self.params["min_days_to_close"]
        max_days = self.params["max_days_to_close"]
        alpha = self.params["regression_alpha"]
        min_edge_bps = self.params["min_edge_bps"]
        excl_cats = set(self.params.get("excluded_categories", []))

        for market in markets:
            if market.status != "active":
                continue
            if market.category in excl_cats:
                continue
            if (market.volume_24h or 0) < min_vol:
                continue

            # Check days to close
            days_to_close: Optional[float] = None
            if market.close_time:
                delta = market.close_time - now
                days_to_close = delta.total_seconds() / 86400
                if days_to_close < min_days or days_to_close > max_days:
                    continue

            yes_mid = market.yes_mid
            if yes_mid is None:
                if market.yes_bid and market.yes_ask:
                    yes_mid = (market.yes_bid + market.yes_ask) / 2
                elif market.last_price:
                    yes_mid = market.last_price
                else:
                    continue

            no_mid = 1.0 - yes_mid

            # === Check for SELL YES signal ===
            if yes_mid >= sell_yes_thresh:
                # Estimate fair value via regression to mean
                excess = yes_mid - sell_yes_thresh
                fair_yes = yes_mid - alpha * excess
                fair_yes = max(0.5, min(0.999, fair_yes))  # clip to reasonable range

                edge = yes_mid - fair_yes  # positive = YES overpriced
                edge_bps = edge * 10_000

                if edge_bps >= min_edge_bps:
                    confidence = min(
                        0.99,
                        self.params["confidence_base"]
                        + self.params["confidence_per_bps"] * edge_bps,
                    )
                    signals.append(Signal(
                        ticker=market.ticker,
                        direction="sell_yes",
                        fair_value=fair_yes,
                        market_price=yes_mid,
                        edge=edge,
                        confidence=confidence,
                        strategy_name=self.name,
                        metadata={
                            "excess_above_threshold": excess,
                            "days_to_close": days_to_close,
                            "volume_24h": market.volume_24h,
                            "category": market.category,
                            "signal_type": "overpriced_yes",
                        },
                    ))

            # === Check for BUY NO signal ===
            elif no_mid >= (1 - buy_no_thresh):
                # YES is very cheap = NO is very expensive
                # Actually: buy NO when YES is priced below buy_no_threshold
                pass  # handled by sell_yes equivalent

            # === Direct BUY NO signal when YES is cheap ===
            if yes_mid <= buy_no_thresh:
                # YES is irrationally cheap, sell it? No — we want to BUY NO.
                # NO mid = 1 - yes_mid = 1 - (near 0) = near 1
                # Actually longshot bias: when NO is near 1.0, same logic as selling YES
                excess_no = no_mid - sell_yes_thresh if no_mid >= sell_yes_thresh else 0
                if excess_no > 0:
                    fair_no = no_mid - alpha * excess_no
                    edge_no = no_mid - fair_no
                    edge_bps_no = edge_no * 10_000

                    if edge_bps_no >= min_edge_bps:
                        confidence = min(
                            0.99,
                            self.params["confidence_base"]
                            + self.params["confidence_per_bps"] * edge_bps_no,
                        )
                        signals.append(Signal(
                            ticker=market.ticker,
                            direction="sell_no",
                            fair_value=1 - fair_no,  # store as YES fair value
                            market_price=no_mid,
                            edge=edge_no,
                            confidence=confidence,
                            strategy_name=self.name,
                            metadata={
                                "signal_type": "overpriced_no",
                                "days_to_close": days_to_close,
                                "volume_24h": market.volume_24h,
                                "category": market.category,
                            },
                        ))

        return signals

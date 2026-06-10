"""
LIP (Liquidity Incentive Program) Optimizer.

Kalshi's LIP rewards market makers for providing liquidity.
Market makers earn rebates when limit orders are filled.

The LIP reward structure (simplified):
  - Reward per fill = base_rebate × time_at_best_bid_ask
  - Higher rewards for tighter spreads
  - Higher rewards for more liquid markets

This strategy optimizes limit order placement to maximize
LIP rewards while maintaining acceptable risk.

Key optimizations:
  1. Price at best bid/ask (tightest spread = most LIP points)
  2. Focus on high-volume markets (more fills = more rewards)
  3. Size orders conservatively (reduce inventory risk from fills)
  4. Refresh quotes frequently (time-weighted scoring)

This is essentially market making with LIP economics layered on top.
The main difference: we size to the LIP reward opportunity rather
than purely to the spread capture.

Note: Actual LIP rates require Kalshi account and are subject to change.
Parameters here are approximations based on publicly available info.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.strategies.base import AbstractStrategy, Signal
from app.schemas.market import MarketOut


class LIPOptimizerStrategy(AbstractStrategy):
    name = "lip_optimizer"
    display_name = "LIP Optimizer (Liquidity Incentive Program)"
    description = (
        "Optimizes limit order placement to maximize Kalshi Liquidity Incentive "
        "Program rewards while providing two-sided markets."
    )

    DEFAULT_PARAMS: dict[str, Any] = {
        "target_spread_bps": 100,    # Target spread to quote (tighter = more LIP)
        "min_volume_24h": 500,       # Only target high-volume markets
        "max_position_per_market": 5,  # Conservative sizing (LIP reward, not alpha)
        "quote_inside_bbo": True,    # Quote inside the current best bid/ask
        "inside_offset_bps": 10,     # How much inside BBO to quote
        "min_days_to_close": 2,      # Don't quote near resolution
        "max_days_to_close": 14,     # Focus on near-term liquid markets
    }

    def generate_signals(
        self,
        markets: list[MarketOut],
        portfolio_equity: float,
    ) -> list[Signal]:
        signals = []
        now = datetime.now(timezone.utc)

        for market in markets:
            if market.status != "active":
                continue
            if (market.volume_24h or 0) < self.params["min_volume_24h"]:
                continue

            yes_bid = market.yes_bid
            yes_ask = market.yes_ask
            if yes_bid is None or yes_ask is None:
                continue

            current_spread_bps = (yes_ask - yes_bid) * 10_000
            if current_spread_bps <= 0:
                continue

            if market.close_time:
                days_to_close = (market.close_time - now).total_seconds() / 86400
                if days_to_close < self.params["min_days_to_close"]:
                    continue
                if days_to_close > self.params["max_days_to_close"]:
                    continue

            yes_mid = (yes_bid + yes_ask) / 2
            target_half_spread = self.params["target_spread_bps"] / 20_000

            if self.params["quote_inside_bbo"]:
                inside_offset = self.params["inside_offset_bps"] / 10_000
                our_bid = min(yes_bid + inside_offset, yes_mid - target_half_spread)
                our_ask = max(yes_ask - inside_offset, yes_mid + target_half_spread)
            else:
                our_bid = yes_mid - target_half_spread
                our_ask = yes_mid + target_half_spread

            our_bid = max(0.01, min(0.99, our_bid))
            our_ask = max(0.01, min(0.99, our_ask))

            if our_bid >= our_ask:
                continue

            # Signal bid side
            signals.append(Signal(
                ticker=market.ticker,
                direction="buy_yes",
                fair_value=yes_mid,
                market_price=our_bid,
                edge=(yes_ask - our_bid) / 2,
                confidence=0.5,  # LIP is about earning rebates, not alpha
                strategy_name=self.name,
                metadata={
                    "order_type": "limit",
                    "limit_price": round(our_bid, 4),
                    "lip_target": True,
                    "current_spread_bps": current_spread_bps,
                    "volume_24h": market.volume_24h,
                },
            ))

            # Signal ask side
            signals.append(Signal(
                ticker=market.ticker,
                direction="sell_yes",
                fair_value=yes_mid,
                market_price=our_ask,
                edge=(our_ask - yes_bid) / 2,
                confidence=0.5,
                strategy_name=self.name,
                metadata={
                    "order_type": "limit",
                    "limit_price": round(our_ask, 4),
                    "lip_target": True,
                    "current_spread_bps": current_spread_bps,
                    "volume_24h": market.volume_24h,
                },
            ))

        return signals

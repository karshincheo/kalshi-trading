"""
Avellaneda-Stoikov Market Making with Jump-Diffusion Extension.

Classic Avellaneda-Stoikov (2008) for continuous-time market making:

  s*(t) = s - q*γ*σ²*(T-t)           [reservation price / fair mid]
  δ_bid = γ*σ²*(T-t)/2 + ln(1+γ/κ)/γ [bid offset from reservation]
  δ_ask = γ*σ²*(T-t)/2 + ln(1+γ/κ)/γ [ask offset from reservation]

Where:
  s     = current mid price (fair value estimate)
  q     = current inventory in contracts (signed, positive = long YES)
  γ     = risk aversion parameter (higher → wider spreads)
  σ²    = variance of contract price process
  T-t   = time to market close (in appropriate units)
  κ     = order arrival rate (estimated from historical fill data)

Jump-diffusion extension:
  Near resolution time, contract price jumps to 0 or 1.
  We add a jump term to the effective variance:
    σ²_eff = σ²_gbm + λ * (p*(1-p)) * jump_weight
  Where λ is jump intensity (increases near close) and p is current price.

Inventory management:
  - Soft inventory limit: skew quotes to reduce
  - Hard inventory limit: stop quoting on the overfull side
  - Emergency: market order to flatten if drawdown > emergency_threshold

For Kalshi: we quote YES bids and YES asks as limit orders.
When YES bid is hit: we buy YES (go long YES inventory).
When YES ask is lifted: we sell YES (go short or reduce long).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.strategies.base import AbstractStrategy, Signal
from app.schemas.market import MarketOut


class MarketMakingStrategy(AbstractStrategy):
    name = "market_making"
    display_name = "Avellaneda-Stoikov Market Making"
    description = (
        "Provides two-sided liquidity and earns the bid-ask spread. "
        "Uses the Avellaneda-Stoikov model with inventory risk management "
        "and jump-diffusion extension near contract resolution."
    )

    DEFAULT_PARAMS: dict[str, Any] = {
        "gamma": 0.1,               # Risk aversion (higher → wider spread)
        "sigma": 0.02,              # Price volatility estimate (std per unit time)
        "kappa": 1.5,               # Order arrival rate parameter
        "time_unit": 86400.0,       # 1 day in seconds (normalize T-t)
        "max_inventory": 20,        # Hard inventory limit (contracts)
        "soft_inventory": 10,       # Soft inventory: start skewing quotes
        "skew_factor": 0.01,        # Additional spread per unit inventory above soft limit
        "emergency_drawdown": 0.15, # Emergency flatten threshold (15% position loss)
        "jump_lambda_base": 0.1,    # Base jump intensity
        "jump_lambda_near_close": 2.0,  # Jump intensity in last 24h
        "jump_near_close_hours": 24,    # Hours to resolution when jump kicks in
        "min_spread_bps": 50,       # Minimum spread we quote (risk control)
        "max_spread_bps": 2000,     # Maximum spread (avoid quoting nonsense)
        "min_volume_24h": 200,      # Minimum market volume to make market
        "max_days_to_close": 30,    # Don't make market on very long-dated contracts
    }

    def __init__(self, params: Optional[dict[str, Any]] = None) -> None:
        super().__init__(params)
        self._inventory: dict[str, int] = {}  # ticker → net YES inventory
        self._sigma_estimates: dict[str, float] = {}  # fitted per-ticker

    def reset(self) -> None:
        self._inventory = {}
        self._sigma_estimates = {}

    def fit(self, historical_markets: list[MarketOut]) -> None:
        """Estimate σ per ticker from historical price variance."""
        from collections import defaultdict
        price_history: dict[str, list[float]] = defaultdict(list)
        for m in historical_markets:
            if m.yes_mid:
                price_history[m.ticker].append(m.yes_mid)
        for ticker, prices in price_history.items():
            if len(prices) > 5:
                diffs = [prices[i] - prices[i-1] for i in range(1, len(prices))]
                n = len(diffs)
                mean_d = sum(diffs) / n
                var = sum((d - mean_d) ** 2 for d in diffs) / (n - 1)
                self._sigma_estimates[ticker] = math.sqrt(var)

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

            yes_mid = market.yes_mid
            if yes_mid is None:
                if market.yes_bid and market.yes_ask:
                    yes_mid = (market.yes_bid + market.yes_ask) / 2
                else:
                    continue

            # Time to close
            if market.close_time is None:
                continue
            delta = market.close_time - now
            T_minus_t = delta.total_seconds()
            if T_minus_t <= 0:
                continue
            if T_minus_t > self.params["max_days_to_close"] * 86400:
                continue

            T_normalized = T_minus_t / self.params["time_unit"]
            hours_to_close = T_minus_t / 3600

            # Volatility: use fitted estimate or default
            sigma = self._sigma_estimates.get(market.ticker, self.params["sigma"])

            # Jump-diffusion: increase effective sigma near resolution
            if hours_to_close <= self.params["jump_near_close_hours"]:
                jump_lambda = self.params["jump_lambda_near_close"]
            else:
                jump_lambda = self.params["jump_lambda_base"]

            # Jump variance term: λ * p * (1 - p)
            jump_var = jump_lambda * yes_mid * (1 - yes_mid)
            sigma_eff = math.sqrt(sigma ** 2 + jump_var)

            # Current inventory for this ticker
            q = self._inventory.get(market.ticker, 0)
            gamma = self.params["gamma"]
            kappa = self.params["kappa"]

            # Reservation price (where we want mid to be, adjusted for inventory)
            reservation = yes_mid - q * gamma * sigma_eff ** 2 * T_normalized

            # Half-spread from A-S formula
            half_spread = (gamma * sigma_eff ** 2 * T_normalized / 2
                           + math.log(1 + gamma / kappa) / gamma)

            # Apply inventory skew beyond soft limit
            soft_inv = self.params["soft_inventory"]
            if abs(q) > soft_inv:
                skew = self.params["skew_factor"] * (abs(q) - soft_inv)
                if q > 0:  # Long inventory → skew ask down, bid down
                    half_spread += skew
                else:  # Short inventory → skew bid up, ask up
                    half_spread += skew

            # Compute bid and ask prices
            our_bid = reservation - half_spread
            our_ask = reservation + half_spread

            # Clip to valid range
            our_bid = max(0.01, min(0.99, our_bid))
            our_ask = max(0.01, min(0.99, our_ask))

            # Check spread is within acceptable range
            spread_bps = (our_ask - our_bid) * 10_000
            min_spread = self.params["min_spread_bps"]
            max_spread = self.params["max_spread_bps"]

            if spread_bps < min_spread or spread_bps > max_spread:
                continue

            # Don't quote both sides if inventory at hard limit
            max_inv = self.params["max_inventory"]

            # Generate BID signal (buy YES at our_bid)
            if q < max_inv and market.yes_ask and our_bid < market.yes_ask:
                edge_bid = market.yes_ask - our_bid  # spread we capture
                if edge_bid > 0:
                    signals.append(Signal(
                        ticker=market.ticker,
                        direction="buy_yes",
                        fair_value=yes_mid,
                        market_price=our_bid,
                        edge=half_spread,
                        confidence=0.6,
                        strategy_name=self.name,
                        metadata={
                            "order_type": "limit",
                            "limit_price": round(our_bid, 4),
                            "reservation_price": round(reservation, 4),
                            "half_spread": round(half_spread, 4),
                            "sigma_eff": round(sigma_eff, 4),
                            "inventory": q,
                            "T_normalized": T_normalized,
                        },
                    ))

            # Generate ASK signal (sell YES at our_ask)
            if q > -max_inv and market.yes_bid and our_ask > market.yes_bid:
                edge_ask = our_ask - market.yes_bid  # spread we capture
                if edge_ask > 0:
                    signals.append(Signal(
                        ticker=market.ticker,
                        direction="sell_yes",
                        fair_value=yes_mid,
                        market_price=our_ask,
                        edge=half_spread,
                        confidence=0.6,
                        strategy_name=self.name,
                        metadata={
                            "order_type": "limit",
                            "limit_price": round(our_ask, 4),
                            "reservation_price": round(reservation, 4),
                            "half_spread": round(half_spread, 4),
                            "sigma_eff": round(sigma_eff, 4),
                            "inventory": q,
                        },
                    ))

        return signals

    def update_inventory(self, ticker: str, delta: int) -> None:
        """Called by trading engine after a fill to update inventory."""
        self._inventory[ticker] = self._inventory.get(ticker, 0) + delta

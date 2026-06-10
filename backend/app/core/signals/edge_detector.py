"""
Edge Detector — Central scoring engine for market opportunities.

Combines signals from all enabled strategies into a unified
opportunity score for the scanner view.

The edge score (0-100) is computed as:
  base_score = edge_bps * confidence
  volume_bonus = log(volume_24h + 1) / log(max_volume + 1) * 10
  time_bonus = max(0, 10 - days_to_close) if days_to_close < 10 else 0
  edge_score = min(100, base_score / 100 + volume_bonus + time_bonus)
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from app.core.strategies.base import Signal
from app.schemas.market import MarketOut
from app.schemas.strategy import OpportunityOut


def compute_edge_score(signal: Signal, market: MarketOut) -> float:
    """
    Compute a 0-100 composite edge score for display in the scanner.

    Higher scores = better trading opportunity.
    """
    edge_bps = abs(signal.edge) * 10_000
    base_score = edge_bps * signal.confidence / 100

    # Volume bonus (more liquid = easier to execute)
    vol = market.volume_24h or 0
    volume_bonus = math.log(vol + 1) / math.log(10_000 + 1) * 15 if vol > 0 else 0

    # Time bonus: more urgent = higher score (near resolution)
    time_bonus = 0.0
    if market.close_time:
        now = datetime.now(timezone.utc)
        days = (market.close_time - now).total_seconds() / 86400
        if 1 <= days <= 7:
            time_bonus = (7 - days) / 7 * 10

    return min(100.0, base_score + volume_bonus + time_bonus)


def signals_to_opportunities(
    signals: list[Signal],
    markets: dict[str, MarketOut],
    kelly_fractions: dict[str, float],
    bankroll: float,
) -> list[OpportunityOut]:
    """
    Convert strategy signals into scanner OpportunityOut objects.
    """
    opportunities = []
    seen_tickers: set[str] = set()

    # Sort by edge * confidence descending
    sorted_signals = sorted(signals, key=lambda s: abs(s.edge) * s.confidence, reverse=True)

    for signal in sorted_signals:
        if signal.ticker in seen_tickers:
            continue
        market = markets.get(signal.ticker)
        if market is None:
            continue

        edge_score = compute_edge_score(signal, market)
        fk = kelly_fractions.get(signal.ticker, 0.0)
        rec_contracts = max(0, int(fk * bankroll / max(0.01, signal.market_price)))

        opportunities.append(OpportunityOut(
            ticker=signal.ticker,
            title=market.title,
            category=market.category,
            yes_bid=market.yes_bid,
            yes_ask=market.yes_ask,
            yes_mid=market.yes_mid,
            close_time=market.close_time,
            volume_24h=market.volume_24h,
            edge_score=round(edge_score, 1),
            fair_value=signal.fair_value,
            market_price=signal.market_price,
            edge=signal.edge,
            confidence=signal.confidence,
            kelly_fraction=fk,
            recommended_contracts=rec_contracts,
            strategy_name=signal.strategy_name,
            signal_direction=signal.direction,
            metadata=signal.metadata,
        ))
        seen_tickers.add(signal.ticker)

    return opportunities

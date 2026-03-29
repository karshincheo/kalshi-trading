"""
Scanner Service — Market opportunity scanning and ranking.

Runs all enabled strategies against current market data and
returns a ranked list of opportunities for the scanner UI.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import settings
from app.core.math.kelly import kelly_full
from app.core.signals.edge_detector import signals_to_opportunities
from app.schemas.strategy import OpportunityOut

if TYPE_CHECKING:
    from app.broker.base import IBroker
    from app.core.strategies.base import AbstractStrategy

log = logging.getLogger(__name__)


class ScannerService:
    def __init__(self, broker: "IBroker", strategies: list["AbstractStrategy"]) -> None:
        self._broker = broker
        self._strategies = strategies

    async def get_opportunities(
        self,
        strategy_filter: list[str] | None = None,
        min_edge_score: float = 0.0,
        limit: int = 50,
    ) -> list[OpportunityOut]:
        """
        Scan all active markets and return ranked opportunities.
        This runs even when auto-trading is disabled.
        """
        try:
            markets = await self._broker.get_markets(status="active", limit=200)
        except Exception as e:
            log.error("Failed to fetch markets for scanner: %s", e)
            return []

        if not markets:
            return []

        portfolio = await self._broker.get_portfolio_summary()
        equity = portfolio.total_equity

        markets_dict = {m.ticker: m for m in markets}
        all_signals = []

        for strategy in self._strategies:
            if strategy_filter and strategy.name not in strategy_filter:
                continue

            try:
                signals = strategy.generate_signals(markets, equity)
                all_signals.extend(signals)
            except Exception as e:
                log.error("Strategy %s scanner error: %s", strategy.name, e)

        # Compute Kelly for each signal
        kelly_fractions: dict[str, float] = {}
        for signal in all_signals:
            kelly_res = kelly_full(
                p_true=signal.fair_value,
                market_price=signal.market_price,
                bankroll=equity,
                fraction=settings.default_kelly_fraction,
                min_edge=settings.min_edge_threshold,
                max_position_pct=settings.max_position_pct,
            )
            # Use ticker as key (last signal wins if multiple strategies hit same market)
            kelly_fractions[signal.ticker] = kelly_res.kelly_fraction

        opportunities = signals_to_opportunities(
            all_signals, markets_dict, kelly_fractions, equity
        )

        # Filter and sort
        filtered = [o for o in opportunities if o.edge_score >= min_edge_score]
        sorted_opps = sorted(filtered, key=lambda o: o.edge_score, reverse=True)

        return sorted_opps[:limit]

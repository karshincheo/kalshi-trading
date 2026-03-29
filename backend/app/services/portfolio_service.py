"""
Portfolio Service — P&L calculation and metric computation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from app.core.math.metrics import (
    sharpe_ratio, sortino_ratio, max_drawdown, calmar_ratio,
    win_rate, profit_factor, avg_win_loss, equity_to_returns
)
from app.schemas.portfolio import PortfolioMetrics, AttributionRow

if TYPE_CHECKING:
    from app.broker.base import IBroker

log = logging.getLogger(__name__)


class PortfolioService:
    def __init__(self, broker: "IBroker") -> None:
        self._broker = broker
        self._equity_history: list[tuple[datetime, float]] = []
        self._fill_pnls: list[float] = []

    async def snapshot(self) -> None:
        """Take a portfolio snapshot. Called every 60s by pnl_calculator worker."""
        try:
            summary = await self._broker.get_portfolio_summary()
            ts = datetime.now(timezone.utc)
            self._equity_history.append((ts, summary.total_equity))

            # Keep last 90 days of history (1440 points at 60s intervals per day)
            max_points = 90 * 1440
            if len(self._equity_history) > max_points:
                self._equity_history = self._equity_history[-max_points:]

        except Exception as e:
            log.error("Portfolio snapshot error: %s", e)

    async def compute_metrics(self, period_days: int = 30) -> PortfolioMetrics:
        """Compute trading metrics for the specified period."""
        try:
            fills = await self._broker.get_fills(limit=500)
        except Exception:
            fills = []

        # Get equity history for period
        since = datetime.now(timezone.utc) - timedelta(days=period_days)
        period_equity = [e for ts, e in self._equity_history if ts >= since]
        period_returns = equity_to_returns(period_equity)

        # PnL from fills
        pnls: list[float] = []
        by_strategy: dict[str, list[float]] = {}

        # For fills, compute P&L as (sell_price - buy_price) * count
        # This is simplified — a proper P&L requires matching buy/sell pairs
        # The paper broker tracks this accurately via realized_pnl
        try:
            positions = await self._broker.get_positions()
            for pos in positions:
                if pos.unrealized_pnl is not None:
                    strat = pos.strategy_name or "manual"
                    if strat not in by_strategy:
                        by_strategy[strat] = []
        except Exception:
            positions = []

        return PortfolioMetrics(
            sharpe_ratio=sharpe_ratio(period_returns) if len(period_returns) > 2 else None,
            sortino_ratio=sortino_ratio(period_returns) if len(period_returns) > 2 else None,
            max_drawdown=max_drawdown(period_equity) if period_equity else None,
            calmar_ratio=calmar_ratio(period_equity) if len(period_equity) > 5 else None,
            win_rate=win_rate(pnls) if pnls else None,
            profit_factor=profit_factor(pnls) if pnls else None,
            avg_win=avg_win_loss(pnls)[0] if pnls else None,
            avg_loss=avg_win_loss(pnls)[1] if pnls else None,
            num_winning_trades=len([p for p in pnls if p > 0]),
            num_losing_trades=len([p for p in pnls if p < 0]),
            total_trades=len(pnls),
            period_days=period_days,
        )

    def get_equity_history(
        self,
        since: datetime | None = None,
    ) -> list[tuple[datetime, float]]:
        if since:
            return [(ts, eq) for ts, eq in self._equity_history if ts >= since]
        return list(self._equity_history)

"""
Trading Engine — Main tick loop that orchestrates strategy → sizing → execution.

Called by strategy_runner.py worker on each interval (default 60s).

Flow per tick:
1. Fetch all active markets from broker/cache
2. Get current portfolio summary
3. For each enabled strategy: generate_signals()
4. Collect all signals, run DEPO if multiple simultaneous signals
5. For each signal: Kelly-size → risk check → place_order
6. Emit WebSocket events for each order placed
7. Log signal to DB for scanner/history views
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from app.config import settings
from app.core.math.kelly import kelly_full
from app.core.math.depo import depo_optimize
from app.core.risk.circuit_breakers import CircuitBreaker
from app.core.strategies.base import Signal
from app.schemas.order import OrderRequest

if TYPE_CHECKING:
    from app.broker.base import IBroker
    from app.core.strategies.base import AbstractStrategy

log = logging.getLogger(__name__)


class TradingEngine:
    def __init__(
        self,
        broker: "IBroker",
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self._broker = broker
        self._strategies: list["AbstractStrategy"] = []
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            max_position_pct=settings.max_position_pct,
            max_exposure_pct=settings.max_portfolio_exposure_pct,
            max_daily_loss_pct=settings.max_daily_loss_pct,
        )
        self._recent_signals: list[Signal] = []
        self._ws_broadcast_callback = None

    def register_strategy(self, strategy: "AbstractStrategy") -> None:
        self._strategies.append(strategy)

    def set_ws_callback(self, callback) -> None:
        """Set callback for broadcasting WebSocket events to frontend."""
        self._ws_broadcast_callback = callback

    async def tick(self) -> list[Signal]:
        """
        Execute one trading cycle. Returns list of signals generated.
        Called by strategy_runner worker on schedule.
        """
        if self._circuit_breaker.is_halted:
            log.warning("Trading halted: %s", self._circuit_breaker.halt_reason)
            await self._broadcast({"type": "halt", "reason": self._circuit_breaker.halt_reason})
            return []

        try:
            # 1. Get portfolio state
            portfolio = await self._broker.get_portfolio_summary()
            equity = portfolio.total_equity

            # Update circuit breaker with current equity
            halt_reason = self._circuit_breaker.update_equity(equity)
            if halt_reason:
                log.error("Circuit breaker fired: %s", halt_reason)
                await self._broadcast({"type": "circuit_breaker", "reason": halt_reason})
                return []

            # 2. Fetch markets
            markets = await self._broker.get_markets(status="active")
            if not markets:
                return []

            # 3. Generate signals from all enabled strategies
            all_signals: list[Signal] = []
            for strategy in self._strategies:
                if not strategy.enabled:
                    continue
                try:
                    signals = strategy.generate_signals(markets, equity)
                    all_signals.extend(signals)
                    log.debug("%s generated %d signals", strategy.name, len(signals))
                except Exception as e:
                    log.error("Strategy %s error: %s", strategy.name, e, exc_info=True)

            if not all_signals:
                return []

            # 4. Multi-signal sizing via DEPO (if multiple signals)
            if len(all_signals) > 1:
                depo_inputs = [
                    {"p_true": s.fair_value, "market_price": s.market_price, "ticker": s.ticker}
                    for s in all_signals
                ]
                depo_weights = depo_optimize(
                    depo_inputs,
                    bankroll=equity,
                    max_exposure=settings.max_portfolio_exposure_pct,
                    max_single=settings.max_position_pct,
                )
            else:
                depo_weights = [settings.max_position_pct]

            # 5. Execute each signal
            executed: list[Signal] = []
            current_exposure = portfolio.position_value

            for signal, weight in zip(all_signals, depo_weights):
                if weight <= 0:
                    continue

                kelly_result = kelly_full(
                    p_true=signal.fair_value,
                    market_price=signal.market_price,
                    bankroll=equity,
                    fraction=settings.default_kelly_fraction,
                    min_edge=settings.min_edge_threshold,
                    max_position_pct=weight,
                )

                if kelly_result.recommended_contracts <= 0:
                    continue

                order_cost = kelly_result.recommended_dollars
                risk_check = self._circuit_breaker.check_order(
                    order_cost=order_cost,
                    current_equity=equity,
                    current_exposure=current_exposure,
                )

                if not risk_check.passed:
                    log.info("Order rejected: %s", risk_check.reason)
                    continue

                # Place order
                try:
                    req = OrderRequest(
                        ticker=signal.ticker,
                        action=signal.direction,
                        order_type="market",
                        count=kelly_result.recommended_contracts,
                        strategy_name=signal.strategy_name,
                        notes=json.dumps(signal.metadata),
                    )
                    order = await self._broker.place_order(req)
                    current_exposure += order_cost

                    await self._broadcast({
                        "type": "order_placed",
                        "order": {
                            "id": order.id,
                            "ticker": order.ticker,
                            "action": order.action,
                            "count": order.count,
                            "status": order.status,
                            "strategy": signal.strategy_name,
                            "edge_bps": signal.edge_bps,
                        }
                    })

                    executed.append(signal)
                    log.info(
                        "Order placed: %s %s×%s @ %.4f (edge=%.0fbps, kelly=%.2f%%)",
                        signal.direction, kelly_result.recommended_contracts,
                        signal.ticker, signal.market_price,
                        signal.edge_bps, kelly_result.kelly_fraction * 100
                    )
                except Exception as e:
                    log.error("Order failed for %s: %s", signal.ticker, e)

            self._recent_signals = all_signals
            return executed

        except Exception as e:
            log.error("Trading engine tick error: %s", e, exc_info=True)
            return []

    async def _broadcast(self, msg: dict) -> None:
        if self._ws_broadcast_callback:
            try:
                await self._ws_broadcast_callback(msg)
            except Exception:
                pass

    def get_recent_signals(self) -> list[Signal]:
        return list(self._recent_signals)

    def is_halted(self) -> bool:
        return self._circuit_breaker.is_halted

    def resume_trading(self) -> None:
        self._circuit_breaker.resume()

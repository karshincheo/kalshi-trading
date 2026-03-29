"""
Circuit Breakers — Auto-halt trading when risk limits are breached.

Checks performed before each order:
1. Max position size (% of portfolio)
2. Max total exposure (% of portfolio in open positions)
3. Max daily loss (circuit breaker: halt all trading)
4. Max drawdown from high-water mark

If a circuit breaker fires:
  - Order is rejected
  - Event is logged
  - Frontend receives a WebSocket alert
  - (Optionally) Telegram alert is sent
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskCheck:
    passed: bool
    reason: Optional[str] = None


class CircuitBreaker:
    def __init__(
        self,
        max_position_pct: float = 0.05,
        max_exposure_pct: float = 0.50,
        max_daily_loss_pct: float = 0.10,
        max_drawdown_pct: float = 0.20,
    ) -> None:
        self.max_position_pct = max_position_pct
        self.max_exposure_pct = max_exposure_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self._halted = False
        self._halt_reason: Optional[str] = None
        self._high_water_mark: float = 0.0
        self._day_start_equity: float = 0.0

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> Optional[str]:
        return self._halt_reason

    def reset_daily(self, current_equity: float) -> None:
        """Call at start of each trading day."""
        self._day_start_equity = current_equity

    def update_equity(self, current_equity: float) -> Optional[str]:
        """
        Update equity tracking. Returns halt reason if circuit breaker fires.
        Call this on each portfolio snapshot.
        """
        if current_equity > self._high_water_mark:
            self._high_water_mark = current_equity

        if self._day_start_equity > 0:
            daily_loss_pct = (self._day_start_equity - current_equity) / self._day_start_equity
            if daily_loss_pct >= self.max_daily_loss_pct:
                reason = f"Daily loss limit hit: {daily_loss_pct:.1%} > {self.max_daily_loss_pct:.1%}"
                self._halt(reason)
                return reason

        if self._high_water_mark > 0:
            drawdown = (self._high_water_mark - current_equity) / self._high_water_mark
            if drawdown >= self.max_drawdown_pct:
                reason = f"Max drawdown hit: {drawdown:.1%} > {self.max_drawdown_pct:.1%}"
                self._halt(reason)
                return reason

        return None

    def check_order(
        self,
        order_cost: float,
        current_equity: float,
        current_exposure: float,
    ) -> RiskCheck:
        """
        Check if a new order is allowed.
        Returns RiskCheck with passed=False if any limit is breached.
        """
        if self._halted:
            return RiskCheck(False, f"Trading halted: {self._halt_reason}")

        # Check position size
        if current_equity > 0:
            position_pct = order_cost / current_equity
            if position_pct > self.max_position_pct:
                return RiskCheck(
                    False,
                    f"Order too large: {position_pct:.1%} of equity (max {self.max_position_pct:.1%})"
                )

        # Check total exposure
        new_exposure = current_exposure + order_cost
        if current_equity > 0:
            exposure_pct = new_exposure / current_equity
            if exposure_pct > self.max_exposure_pct:
                return RiskCheck(
                    False,
                    f"Exposure limit: {exposure_pct:.1%} of equity (max {self.max_exposure_pct:.1%})"
                )

        return RiskCheck(True)

    def _halt(self, reason: str) -> None:
        self._halted = True
        self._halt_reason = reason

    def resume(self) -> None:
        """Manually resume trading (operator action only)."""
        self._halted = False
        self._halt_reason = None

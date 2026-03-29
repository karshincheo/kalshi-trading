"""Brier score and composite metrics for the autoresearch loop."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.math.metrics import (
    brier_score,
    compute_all_metrics,
)


def brier_skill_score(brier: float, brier_ref: float) -> Optional[float]:
    """
    Brier Skill Score: 1 - (brier / brier_ref).

    brier_ref is typically the climatological baseline (always predicting
    the historical base rate). BSS > 0 means the model beats climatology.
    """
    if brier_ref == 0:
        return None
    return 1.0 - (brier / brier_ref)


@dataclass
class EvaluationResult:
    """Full result of evaluating a strategy iteration."""

    brier_score: float
    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]
    max_drawdown: float
    win_rate: float
    profit_factor: Optional[float]
    total_return: Optional[float]
    num_trades: int
    elapsed_seconds: float
    error_log: str
    predictions: list  # list of dicts
    equity_curve: list  # list of floats
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        """Strategy passed if no errors, didn't time out, and traded."""
        return (
            not self.timed_out
            and not self.error_log
            and self.num_trades > 0
        )


def compute_autoresearch_metrics(
    predictions: list[float],
    outcomes: list[int],
    equity_curve: list[float],
    trade_pnls: list[float],
) -> dict:
    """Compute all metrics including Brier score."""
    base = compute_all_metrics(equity_curve, trade_pnls)
    base["brier_score"] = brier_score(predictions, outcomes)
    return base

"""
Performance metrics for trading strategies.

All functions take equity curves or return series as input.
Pure functions — no I/O or state.

Standard metrics used by best-in-class quantitative traders:
  - Sharpe ratio (excess return / volatility)
  - Sortino ratio (excess return / downside volatility)
  - Maximum drawdown (peak-to-trough decline)
  - Calmar ratio (annual return / max drawdown)
  - Win rate, profit factor, average win/loss
"""
from __future__ import annotations

import math
from typing import Optional


def sharpe_ratio(
    returns: list[float],
    risk_free_rate: float = 0.05,
    periods_per_year: int = 252,
) -> Optional[float]:
    """
    Annualized Sharpe ratio.

    Args:
        returns: List of period returns (e.g. daily P&L / starting equity)
        risk_free_rate: Annual risk-free rate (default 5%)
        periods_per_year: Number of periods in a year (252 for daily)

    Returns:
        Annualized Sharpe ratio, or None if insufficient data
    """
    if len(returns) < 2:
        return None
    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    rf_per_period = risk_free_rate / periods_per_year
    return (mean_r - rf_per_period) / std * math.sqrt(periods_per_year)


def sortino_ratio(
    returns: list[float],
    risk_free_rate: float = 0.05,
    periods_per_year: int = 252,
) -> Optional[float]:
    """
    Annualized Sortino ratio (penalizes only downside volatility).
    """
    if len(returns) < 2:
        return None
    n = len(returns)
    mean_r = sum(returns) / n
    rf_per_period = risk_free_rate / periods_per_year

    downside_returns = [r for r in returns if r < rf_per_period]
    if not downside_returns:
        return None
    downside_var = sum(r ** 2 for r in downside_returns) / len(downside_returns)
    downside_std = math.sqrt(downside_var)
    if downside_std == 0:
        return None
    return (mean_r - rf_per_period) / downside_std * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: list[float]) -> float:
    """
    Maximum peak-to-trough drawdown as a fraction (0.0 to 1.0).

    Returns: Max drawdown (positive number, e.g. 0.15 = 15% drawdown)
    """
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def calmar_ratio(
    equity_curve: list[float],
    periods_per_year: int = 252,
) -> Optional[float]:
    """
    Calmar ratio = annualized return / max drawdown.
    Higher is better. < 0.5 is poor, > 1.0 is good.
    """
    if len(equity_curve) < 2 or equity_curve[0] == 0:
        return None
    total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
    n_periods = len(equity_curve)
    annual_return = (1 + total_return) ** (periods_per_year / n_periods) - 1
    dd = max_drawdown(equity_curve)
    if dd == 0:
        return None
    return annual_return / dd


def win_rate(pnls: list[float]) -> float:
    """Fraction of trades with positive P&L."""
    if not pnls:
        return 0.0
    wins = sum(1 for p in pnls if p > 0)
    return wins / len(pnls)


def profit_factor(pnls: list[float]) -> Optional[float]:
    """
    Gross profit / gross loss.
    > 1.0 means profitable. > 1.5 is good. > 2.0 is excellent.
    """
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss == 0:
        return None
    return gross_profit / gross_loss


def avg_win_loss(pnls: list[float]) -> tuple[float, float]:
    """Returns (average_win, average_loss) in dollars."""
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    return avg_win, avg_loss


def brier_score(predictions: list[float], outcomes: list[int]) -> float:
    """
    Brier score: mean squared error between predicted probabilities and binary outcomes.

    Lower is better. Range [0, 1].
    A perfect forecaster scores 0; always predicting 0.5 scores 0.25.

    Args:
        predictions: Predicted probabilities (0-1) for the YES outcome.
        outcomes: Actual outcomes (0 or 1).

    Returns:
        Brier score (float). Returns 1.0 if inputs are empty.
    """
    if not predictions or not outcomes or len(predictions) != len(outcomes):
        return 1.0
    n = len(predictions)
    return sum((p - o) ** 2 for p, o in zip(predictions, outcomes)) / n


def equity_to_returns(equity_curve: list[float]) -> list[float]:
    """Convert equity curve to period returns."""
    if len(equity_curve) < 2:
        return []
    return [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        if equity_curve[i - 1] != 0 else 0.0
        for i in range(1, len(equity_curve))
    ]


def compute_all_metrics(
    equity_curve: list[float],
    trade_pnls: list[float],
    periods_per_year: int = 252,
) -> dict:
    """Compute all standard metrics in one call."""
    returns = equity_to_returns(equity_curve)
    return {
        "sharpe_ratio": sharpe_ratio(returns, periods_per_year=periods_per_year),
        "sortino_ratio": sortino_ratio(returns, periods_per_year=periods_per_year),
        "max_drawdown": max_drawdown(equity_curve),
        "calmar_ratio": calmar_ratio(equity_curve, periods_per_year=periods_per_year),
        "win_rate": win_rate(trade_pnls),
        "profit_factor": profit_factor(trade_pnls),
        "avg_win": avg_win_loss(trade_pnls)[0],
        "avg_loss": avg_win_loss(trade_pnls)[1],
        "num_trades": len(trade_pnls),
        "total_return": (
            (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
            if equity_curve and equity_curve[0] != 0
            else None
        ),
    }

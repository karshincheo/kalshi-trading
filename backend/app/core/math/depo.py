"""
DEPO — Discrete Entropic Portfolio Optimization for binary markets.

For multiple simultaneous binary bets, full Kelly treats each bet
independently and ignores correlations, leading to over-betting.

DEPO solves the log-wealth maximization under joint distribution:
  max_{w} E[log(1 + sum_i w_i * r_i)]
  s.t. sum_i w_i <= max_exposure, w_i >= 0, w_i <= max_single

Where r_i is the return on position i:
  r_i = (1 - c_i) / c_i  if bet wins (price was c_i)
  r_i = -1               if bet loses

Reference: Kelly, J.L. (1956) + extensions for correlated bets
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

try:
    from scipy.optimize import minimize
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


def depo_optimize(
    signals: list[dict],  # [{"p_true": float, "market_price": float, "ticker": str}]
    bankroll: float,
    max_exposure: float = 0.50,   # max fraction of bankroll in total positions
    max_single: float = 0.10,     # max fraction per position
    correlation_matrix: Optional[np.ndarray] = None,
) -> list[float]:
    """
    Optimize position sizes across multiple simultaneous signals.

    Args:
        signals: List of signal dicts with p_true and market_price
        bankroll: Total portfolio equity
        max_exposure: Maximum total exposure as fraction of bankroll
        max_single: Maximum single position as fraction of bankroll
        correlation_matrix: NxN correlation matrix of outcomes.
                          If None, assumes independence.

    Returns:
        List of weights (fractions of bankroll) for each signal.
        Returns independent fractional Kelly if scipy not available.
    """
    n = len(signals)
    if n == 0:
        return []
    if n == 1:
        from app.core.math.kelly import kelly_fraction
        fk = kelly_fraction(signals[0]["p_true"], signals[0]["market_price"])
        return [min(fk, max_single)]

    if not SCIPY_AVAILABLE:
        # Fallback: independent fractional Kelly, scaled to max_exposure
        from app.core.math.kelly import kelly_fraction
        weights = [
            kelly_fraction(s["p_true"], s["market_price"])
            for s in signals
        ]
        total = sum(weights)
        if total > max_exposure:
            weights = [w * max_exposure / total for w in weights]
        return [min(w, max_single) for w in weights]

    prices = np.array([s["market_price"] for s in signals])
    p_true = np.array([s["p_true"] for s in signals])

    # Returns: win returns and loss returns
    win_returns = (1 - prices) / prices  # profit per unit bet on YES
    lose_returns = np.full(n, -1.0)

    # Objective: negative expected log wealth (minimize → maximize)
    def neg_expected_log_wealth(w: np.ndarray) -> float:
        # Enumerate all 2^n outcomes (feasible up to ~15 signals)
        if n > 15:
            # Monte Carlo approximation for large n
            return _mc_neg_log_wealth(w, p_true, win_returns, correlation_matrix)

        total = 0.0
        for outcome in range(2 ** n):
            bits = [(outcome >> i) & 1 for i in range(n)]
            prob = 1.0
            for i, b in enumerate(bits):
                prob *= p_true[i] if b else (1 - p_true[i])
            portfolio_return = sum(
                w[i] * (win_returns[i] if bits[i] else lose_returns[i])
                for i in range(n)
            )
            wealth = 1.0 + portfolio_return
            if wealth <= 0:
                return 1e10  # Penalize ruin scenarios heavily
            total += prob * math.log(wealth)
        return -total

    # Gradient of objective (numerical)
    w0 = np.full(n, max_exposure / n)
    bounds = [(0.0, max_single)] * n
    constraints = [{"type": "ineq", "fun": lambda w: max_exposure - np.sum(w)}]

    result = minimize(
        neg_expected_log_wealth,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 200, "ftol": 1e-8},
    )

    if result.success:
        return result.x.tolist()
    else:
        # Fallback to equal Kelly
        from app.core.math.kelly import kelly_fraction
        weights = [
            kelly_fraction(s["p_true"], s["market_price"])
            for s in signals
        ]
        total = sum(weights)
        if total > max_exposure:
            weights = [w * max_exposure / total for w in weights]
        return [min(w, max_single) for w in weights]


def _mc_neg_log_wealth(
    w: np.ndarray,
    p_true: np.ndarray,
    win_returns: np.ndarray,
    correlation_matrix: Optional[np.ndarray],
    n_samples: int = 10_000,
) -> float:
    """Monte Carlo estimate for large-n case."""
    n = len(w)
    rng = np.random.default_rng(42)
    if correlation_matrix is not None:
        # Correlated Bernoulli via Gaussian copula
        z = rng.multivariate_normal(np.zeros(n), correlation_matrix, size=n_samples)
        from scipy.stats import norm
        outcomes = (norm.cdf(z) < p_true).astype(float)
    else:
        outcomes = (rng.random((n_samples, n)) < p_true).astype(float)

    portfolio_returns = outcomes * win_returns + (1 - outcomes) * (-1.0)
    wealth = 1.0 + portfolio_returns @ w
    wealth = np.maximum(wealth, 1e-10)
    return -float(np.mean(np.log(wealth)))

"""
Kelly Criterion for binary prediction markets.

Binary event: contract settles at $1 (YES) or $0 (NO).

For a BUY_YES at price p (expressed as probability, 0-1):
  - Win: gain (1 - p) per contract if YES resolves
  - Lose: lose p per contract if NO resolves
  - Net odds b = (1 - p) / p

Full Kelly: f* = (q * b - (1 - q)) / b
  Where q = true probability of YES

Simplified for binary markets:
  f* = q - (1 - q) / b = q - (1 - q) * p / (1 - p)
     = (q * (1 - p) - (1 - q) * p) / (1 - p)
     = (q - p) / (1 - p)  [for buy_yes]

For BUY_NO at price (1-p):
  f* = (r - (1-p)) / p   where r = true probability of NO = (1-q)

Fractional Kelly: f = f* * fraction (typically 0.25 to 0.5)

This module contains ONLY pure functions. No I/O, no state.
All functions are deterministic and unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KellyResult:
    kelly_fraction: float      # Fraction of bankroll to bet (0-1)
    edge: float                # fair_value - market_price (signed)
    net_odds: float            # b = payout per unit risked
    expected_value: float      # EV per unit bet (annualized in prob terms)
    recommended_dollars: float # Kelly fraction × bankroll
    recommended_contracts: int # recommended_dollars / price_per_contract


def kelly_fraction(
    p_true: float,
    market_price: float,
    fraction: float = 0.25,
    min_edge: float = 0.02,
    commission: float = 0.0,
) -> float:
    """
    Compute fractional Kelly position size for a binary market.

    Args:
        p_true: Your estimated true probability of YES (0-1)
        market_price: Current market price for the bet you're making (0-1)
            If buying YES: pass the YES price (e.g. 0.95)
            If buying NO: pass the NO price (e.g. 0.05)
        fraction: Fractional Kelly multiplier (0.25 = quarter-Kelly recommended)
        min_edge: Minimum edge to trade; returns 0 if edge < min_edge
        commission: Transaction cost per unit bet (reduces effective edge)

    Returns:
        Fraction of bankroll to bet (0.0 if no edge or below threshold)
    """
    if not (0 < market_price < 1) or not (0 < p_true < 1):
        return 0.0

    # Net odds: what you win per unit risked
    b = (1.0 - market_price) / market_price

    # Edge: your probability estimate minus the market's implied probability
    edge = p_true - market_price

    if abs(edge) < min_edge:
        return 0.0

    if edge < 0:
        # Market overprices YES relative to our estimate → no edge on YES side
        return 0.0

    # Full Kelly
    full_k = (p_true * (b + 1) - 1) / b
    full_k = max(0.0, full_k)

    # Apply commission drag
    if commission > 0:
        effective_b = b * (1 - commission) - commission
        if effective_b <= 0:
            return 0.0
        full_k = (p_true * (effective_b + 1) - 1) / effective_b
        full_k = max(0.0, full_k)

    return full_k * fraction


def kelly_full(
    p_true: float,
    market_price: float,
    bankroll: float,
    fraction: float = 0.25,
    min_edge: float = 0.02,
    commission: float = 0.0,
    max_position_pct: float = 0.10,
) -> KellyResult:
    """
    Full Kelly calculation with position sizing in dollars and contracts.

    Args:
        p_true: Estimated true probability of YES
        market_price: Current YES price (0-1)
        bankroll: Total portfolio equity in dollars
        fraction: Fractional Kelly multiplier
        min_edge: Minimum edge threshold
        commission: Transaction cost per unit
        max_position_pct: Hard cap on position size (fraction of bankroll)

    Returns:
        KellyResult with all sizing information
    """
    b = (1.0 - market_price) / market_price if market_price > 0 else 1.0
    edge = p_true - market_price
    ev = edge * (1.0 / market_price - 1) - (1 - p_true)  # EV per $1 bet

    fk = kelly_fraction(p_true, market_price, fraction, min_edge, commission)
    fk = min(fk, max_position_pct)  # Hard cap

    dollars = fk * bankroll
    contracts = max(0, int(dollars / market_price)) if market_price > 0 else 0

    return KellyResult(
        kelly_fraction=fk,
        edge=edge,
        net_odds=b,
        expected_value=ev,
        recommended_dollars=dollars,
        recommended_contracts=contracts,
    )


def kelly_for_no(
    p_true_yes: float,
    no_market_price: float,
    bankroll: float,
    fraction: float = 0.25,
    min_edge: float = 0.02,
    max_position_pct: float = 0.10,
) -> KellyResult:
    """
    Kelly sizing for buying NO contracts.

    p_true_yes: Your estimate of YES probability
    no_market_price: Current NO price (= 1 - yes_price)
    The edge on NO = (1 - p_true_yes) - no_market_price
    """
    p_true_no = 1.0 - p_true_yes
    return kelly_full(
        p_true=p_true_no,
        market_price=no_market_price,
        bankroll=bankroll,
        fraction=fraction,
        min_edge=min_edge,
        max_position_pct=max_position_pct,
    )


def multi_kelly(
    signals: list[tuple[float, float]],  # [(p_true, market_price), ...]
    bankroll: float,
    fraction: float = 0.25,
    min_edge: float = 0.02,
) -> list[float]:
    """
    Independent Kelly for multiple simultaneous positions.
    Returns list of fractional sizes (scaled to sum ≤ 1 if needed).

    Note: For correlated positions, use DEPO instead.
    """
    sizes = [
        kelly_fraction(p, mkt, fraction=fraction, min_edge=min_edge)
        for p, mkt in signals
    ]
    total = sum(sizes)
    if total > 1.0:
        sizes = [s / total for s in sizes]
    return sizes

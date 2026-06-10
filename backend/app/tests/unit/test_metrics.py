"""Unit tests for performance and calibration metrics."""

import pytest

from app.core.math.metrics import (
    brier_score,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    win_rate,
)


class TestBrierScore:
    def test_perfect_forecaster_scores_zero(self):
        assert brier_score([1.0, 0.0, 1.0], [1, 0, 1]) == 0.0

    def test_coin_flip_forecaster_scores_quarter(self):
        assert brier_score([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]) == pytest.approx(0.25)

    def test_hand_computed_value(self):
        # ((0.8-1)^2 + (0.3-0)^2) / 2 = (0.04 + 0.09) / 2 = 0.065
        assert brier_score([0.8, 0.3], [1, 0]) == pytest.approx(0.065)

    def test_empty_and_mismatched_inputs_return_worst_score(self):
        assert brier_score([], []) == 1.0
        assert brier_score([0.5], [1, 0]) == 1.0


class TestSharpeRatio:
    def test_insufficient_data_returns_none(self):
        assert sharpe_ratio([0.01]) is None

    def test_zero_variance_returns_none(self):
        assert sharpe_ratio([0.01, 0.01, 0.01]) is None

    def test_positive_returns_give_positive_sharpe(self):
        assert sharpe_ratio([0.01, 0.02, 0.015, 0.012], risk_free_rate=0.0) > 0


class TestSortinoRatio:
    def test_no_downside_periods_handled(self):
        # All-positive returns: no downside deviation to divide by.
        result = sortino_ratio([0.01, 0.02, 0.03])
        assert result is None or result > 0


class TestMaxDrawdown:
    def test_monotonic_rise_has_zero_drawdown(self):
        assert max_drawdown([100, 110, 120, 130]) == 0.0

    def test_known_drawdown(self):
        # Peak 120 → trough 90 = 25% drawdown
        assert max_drawdown([100, 120, 90, 110]) == pytest.approx(0.25)


class TestWinRateAndProfitFactor:
    def test_win_rate(self):
        assert win_rate([1.0, -1.0, 2.0, -0.5]) == pytest.approx(0.5)

    def test_profit_factor_zero_losses(self):
        # No losing trades → undefined (None) or inf-like behavior, never a crash
        result = profit_factor([1.0, 2.0])
        assert result is None or result > 0

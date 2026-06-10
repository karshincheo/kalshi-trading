"""Unit tests for DEPO and HRP portfolio sizing."""

import numpy as np
import pytest

from app.core.math.depo import depo_optimize
from app.core.math.hrp import hrp_weights


class TestDepoOptimize:
    def test_empty_signals_returns_empty(self):
        assert depo_optimize([], bankroll=1000.0) == []

    def test_single_signal_respects_max_single(self):
        weights = depo_optimize(
            [{"p_true": 0.9, "market_price": 0.5, "ticker": "A"}],
            bankroll=1000.0,
            max_single=0.10,
        )
        assert len(weights) == 1
        assert 0 <= weights[0] <= 0.10 + 1e-9

    def test_total_exposure_capped(self):
        signals = [
            {"p_true": 0.9, "market_price": 0.5, "ticker": t} for t in "ABCDEF"
        ]
        weights = depo_optimize(signals, bankroll=1000.0, max_exposure=0.50)
        assert sum(weights) <= 0.50 + 1e-9
        assert all(w >= 0 for w in weights)

    def test_no_edge_signals_get_no_allocation(self):
        weights = depo_optimize(
            [{"p_true": 0.5, "market_price": 0.5, "ticker": "A"}],
            bankroll=1000.0,
        )
        assert weights[0] == pytest.approx(0.0, abs=1e-6)


class TestHrpWeights:
    def test_single_asset_gets_full_weight(self):
        weights = hrp_weights(np.random.default_rng(0).normal(size=(20, 1)))
        assert weights == [1.0]

    def test_weights_sum_to_one_and_nonnegative(self):
        rng = np.random.default_rng(42)
        weights = hrp_weights(rng.normal(size=(50, 4)))
        assert sum(weights) == pytest.approx(1.0)
        assert all(w >= 0 for w in weights)

    def test_too_few_periods_falls_back_to_equal_weights(self):
        rng = np.random.default_rng(7)
        weights = hrp_weights(rng.normal(size=(3, 4)), min_periods=10)
        assert weights == pytest.approx([0.25, 0.25, 0.25, 0.25])

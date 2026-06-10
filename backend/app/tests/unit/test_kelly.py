"""Unit tests for Kelly position sizing."""

import pytest

from app.core.math.kelly import kelly_fraction, kelly_for_no, kelly_full


class TestKellyFraction:
    def test_textbook_value(self):
        # p=0.6 at price 0.5: b=1, full Kelly = (0.6*2 - 1)/1 = 0.2
        assert kelly_fraction(0.6, 0.5, fraction=1.0) == pytest.approx(0.2)

    def test_fractional_multiplier_scales_linearly(self):
        full = kelly_fraction(0.6, 0.5, fraction=1.0)
        quarter = kelly_fraction(0.6, 0.5, fraction=0.25)
        assert quarter == pytest.approx(full * 0.25)

    def test_no_bet_below_min_edge(self):
        # 1% edge with 2% min_edge → no trade
        assert kelly_fraction(0.51, 0.50, min_edge=0.02) == 0.0

    def test_no_bet_on_negative_edge(self):
        assert kelly_fraction(0.40, 0.50) == 0.0

    def test_commission_reduces_size(self):
        clean = kelly_fraction(0.6, 0.5)
        taxed = kelly_fraction(0.6, 0.5, commission=0.02)
        assert 0 < taxed < clean

    def test_prohibitive_commission_kills_trade(self):
        # Commission that wipes out the payout entirely
        assert kelly_fraction(0.99, 0.98, commission=0.99) == 0.0

    @pytest.mark.parametrize("p, price", [(0.5, 0.0), (0.5, 1.0), (0.0, 0.5), (1.0, 0.5), (-0.1, 0.5)])
    def test_degenerate_inputs_return_zero(self, p, price):
        assert kelly_fraction(p, price) == 0.0


class TestKellyFull:
    def test_result_fields_are_consistent(self):
        result = kelly_full(0.6, 0.5, bankroll=1000.0)
        assert result.kelly_fraction >= 0
        assert result.recommended_dollars == pytest.approx(
            result.kelly_fraction * 1000.0
        )
        assert result.edge == pytest.approx(0.1)

    def test_max_position_pct_hard_cap(self):
        # Huge edge, full Kelly — the cap must still bind.
        result = kelly_full(0.9, 0.5, bankroll=1000.0, fraction=1.0, max_position_pct=0.10)
        assert result.kelly_fraction <= 0.10 + 1e-9


class TestKellyForNo:
    def test_no_side_mirrors_yes_side(self):
        # Buying NO at NO-price 0.4 with p_true(YES)=0.4 is the same trade as
        # buying YES at price 0.4 with p_true(YES)=0.6.
        no_side = kelly_for_no(p_true_yes=0.4, no_market_price=0.4, bankroll=1000.0, fraction=1.0)
        yes_mirror = kelly_full(p_true=0.6, market_price=0.4, bankroll=1000.0, fraction=1.0)
        assert no_side.kelly_fraction == pytest.approx(yes_mirror.kelly_fraction)

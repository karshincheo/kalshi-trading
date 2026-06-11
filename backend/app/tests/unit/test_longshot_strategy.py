"""Strategy-level test: longshot bias fires on extreme prices and respects filters."""

from datetime import datetime, timedelta, timezone


from app.core.strategies.longshot_bias import LongshotBiasStrategy
from app.schemas.market import MarketOut


def make_market(**overrides) -> MarketOut:
    now = datetime.now(timezone.utc)
    base = dict(
        ticker="HIGHNY-26JUN15-T98",
        event_ticker="HIGHNY",
        title="Will the high in NYC exceed 98F?",
        category="climate",
        status="active",
        yes_mid=0.98,
        volume_24h=1000,
        close_time=now + timedelta(days=10),
        created_at=now,
        updated_at=now,
    )
    base.update(overrides)
    return MarketOut(**base)


class TestLongshotBias:
    def setup_method(self):
        # With the stock defaults (alpha=0.5, threshold=0.97, min_edge=150bps)
        # the modeled sell-YES edge is 0.5*(price-0.97), which only reaches
        # 150bps at price=1.0 — i.e. the default gate is effectively closed.
        # The engine runs this strategy with tuned params; tests do the same.
        self.strategy = LongshotBiasStrategy(params={"min_edge_bps": 40})

    def test_fires_sell_yes_on_98_cent_market(self):
        signals = self.strategy.generate_signals([make_market(yes_mid=0.98)], 10_000.0)
        assert len(signals) == 1
        sig = signals[0]
        assert sig.direction in {"sell_yes", "buy_no"}
        assert sig.fair_value < 0.98  # regression to mean pulls fair value down
        assert sig.edge_bps >= self.strategy.params["min_edge_bps"] - 1e-6
        assert 0.0 <= sig.confidence <= 1.0

    def test_silent_on_mid_priced_market(self):
        assert self.strategy.generate_signals([make_market(yes_mid=0.60)], 10_000.0) == []

    def test_illiquid_market_filtered(self):
        assert self.strategy.generate_signals([make_market(volume_24h=5)], 10_000.0) == []

    def test_day_of_settlement_filtered(self):
        close = datetime.now(timezone.utc) + timedelta(hours=6)
        assert self.strategy.generate_signals([make_market(close_time=close)], 10_000.0) == []

    def test_inactive_market_filtered(self):
        assert self.strategy.generate_signals([make_market(status="settled")], 10_000.0) == []

    def test_derives_mid_from_bid_ask_when_missing(self):
        m = make_market(yes_mid=None, yes_bid=0.97, yes_ask=0.99)
        signals = self.strategy.generate_signals([m], 10_000.0)
        assert len(signals) == 1

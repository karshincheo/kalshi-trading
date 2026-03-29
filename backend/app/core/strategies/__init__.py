from app.core.strategies.base import AbstractStrategy, Signal
from app.core.strategies.longshot_bias import LongshotBiasStrategy
from app.core.strategies.market_making import MarketMakingStrategy
from app.core.strategies.nowcasting import NowcastingStrategy
from app.core.strategies.cross_market_arb import CrossMarketArbStrategy
from app.core.strategies.lip_optimizer import LIPOptimizerStrategy

STRATEGY_REGISTRY: dict[str, type[AbstractStrategy]] = {
    "longshot_bias": LongshotBiasStrategy,
    "market_making": MarketMakingStrategy,
    "nowcasting": NowcastingStrategy,
    "cross_market_arb": CrossMarketArbStrategy,
    "lip_optimizer": LIPOptimizerStrategy,
}

__all__ = [
    "AbstractStrategy", "Signal",
    "LongshotBiasStrategy", "MarketMakingStrategy",
    "NowcastingStrategy", "CrossMarketArbStrategy", "LIPOptimizerStrategy",
    "STRATEGY_REGISTRY",
]

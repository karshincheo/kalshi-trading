from fastapi import APIRouter
from pydantic import BaseModel
from app.config import settings

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsOut(BaseModel):
    broker_mode: str
    paper_initial_balance: float
    max_position_pct: float
    max_portfolio_exposure_pct: float
    max_daily_loss_pct: float
    default_kelly_fraction: float
    min_edge_threshold: float
    market_poll_interval_seconds: int
    strategy_tick_interval_seconds: int
    has_kalshi_api_key: bool


@router.get("", response_model=SettingsOut)
async def get_settings():
    return SettingsOut(
        broker_mode=settings.broker_mode.value,
        paper_initial_balance=settings.paper_initial_balance,
        max_position_pct=settings.max_position_pct,
        max_portfolio_exposure_pct=settings.max_portfolio_exposure_pct,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        default_kelly_fraction=settings.default_kelly_fraction,
        min_edge_threshold=settings.min_edge_threshold,
        market_poll_interval_seconds=settings.market_poll_interval_seconds,
        strategy_tick_interval_seconds=settings.strategy_tick_interval_seconds,
        has_kalshi_api_key=bool(settings.kalshi_api_key),
    )

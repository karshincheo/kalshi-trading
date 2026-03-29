from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class PortfolioSummary(BaseModel):
    broker_mode: str
    cash_balance: float
    position_value: float
    total_equity: float
    unrealized_pnl: float
    realized_pnl: float
    daily_pnl: Optional[float] = None
    num_positions: int
    total_return_pct: Optional[float] = None  # vs initial balance
    timestamp: datetime


class PortfolioMetrics(BaseModel):
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    calmar_ratio: Optional[float] = None
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    num_winning_trades: int = 0
    num_losing_trades: int = 0
    total_trades: int = 0
    period_days: int = 30


class EquityPoint(BaseModel):
    timestamp: datetime
    total_equity: float
    daily_pnl: Optional[float] = None


class PortfolioHistory(BaseModel):
    broker_mode: str
    points: list[EquityPoint]
    initial_equity: float


class AttributionRow(BaseModel):
    strategy_name: str
    realized_pnl: float
    unrealized_pnl: float
    num_trades: int
    win_rate: Optional[float] = None

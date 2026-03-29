from __future__ import annotations
from datetime import datetime, date
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict, Field


class BacktestRequest(BaseModel):
    strategy_name: str
    params: dict[str, Any] = {}
    start_date: date
    end_date: date
    initial_capital: float = Field(default=10_000.0, ge=100.0)
    embargo_days: int = Field(default=5, ge=0)
    n_splits: int = Field(default=5, ge=2, le=20)


class FoldMetrics(BaseModel):
    fold_idx: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    total_return: float
    sharpe_ratio: Optional[float] = None
    max_drawdown: float
    win_rate: float
    num_trades: int


class BacktestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    strategy_name: str
    start_date: date
    end_date: date
    status: str
    total_return: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    num_trades: Optional[int] = None
    profit_factor: Optional[float] = None
    error_msg: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class BacktestTradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fold_idx: int
    ticker: str
    action: str
    count: int
    entry_price: float
    exit_price: Optional[float] = None
    entry_time: datetime
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None


class BacktestResult(BaseModel):
    run: BacktestRunOut
    fold_metrics: list[FoldMetrics]
    equity_curve: list[dict]  # [{timestamp, equity}]
    trades: list[BacktestTradeOut]

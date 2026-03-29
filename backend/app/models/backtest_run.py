from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from sqlalchemy import String, Float, Integer, DateTime, Date, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    params_json: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    embargo_days: Mapped[int] = mapped_column(Integer, default=5)
    n_splits: Mapped[int] = mapped_column(Integer, default=5)
    purge_pct: Mapped[float] = mapped_column(Float, default=0.01)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|complete|failed
    total_return: Mapped[Optional[float]] = mapped_column(Float)
    sharpe_ratio: Mapped[Optional[float]] = mapped_column(Float)
    sortino_ratio: Mapped[Optional[float]] = mapped_column(Float)
    max_drawdown: Mapped[Optional[float]] = mapped_column(Float)
    win_rate: Mapped[Optional[float]] = mapped_column(Float)
    num_trades: Mapped[Optional[int]] = mapped_column(Integer)
    profit_factor: Mapped[Optional[float]] = mapped_column(Float)
    results_json: Mapped[Optional[str]] = mapped_column(Text)  # full fold results
    error_msg: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    fold_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    ticker: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[Optional[float]] = mapped_column(Float)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    pnl: Mapped[Optional[float]] = mapped_column(Float)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)

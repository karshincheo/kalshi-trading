from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Integer, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        Index("idx_portfolio_ts", "broker_mode", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broker_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash_balance: Mapped[float] = mapped_column(Float, nullable=False)
    position_value: Mapped[float] = mapped_column(Float, nullable=False)
    total_equity: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    daily_pnl: Mapped[Optional[float]] = mapped_column(Float)
    num_positions: Mapped[Optional[int]] = mapped_column(Integer)
    sharpe_rolling: Mapped[Optional[float]] = mapped_column(Float)
    max_drawdown: Mapped[Optional[float]] = mapped_column(Float)

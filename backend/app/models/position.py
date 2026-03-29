from __future__ import annotations
from typing import Optional
from sqlalchemy import String, Float, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class Position(Base, TimestampMixin):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("broker_mode", "ticker", "contract_side", name="uq_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broker_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    ticker: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    contract_side: Mapped[str] = mapped_column(String(5), nullable=False)  # yes|no
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[Optional[float]] = mapped_column(Float)
    unrealized_pnl: Mapped[Optional[float]] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    strategy_name: Mapped[Optional[str]] = mapped_column(String(50))

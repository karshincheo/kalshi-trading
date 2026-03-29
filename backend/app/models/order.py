from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    broker_mode: Mapped[str] = mapped_column(String(10), nullable=False)  # paper|demo|live
    ticker: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)    # buy|sell
    order_type: Mapped[str] = mapped_column(String(10), nullable=False)  # market|limit
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # buy_yes|buy_no|sell_yes|sell_no
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[Optional[float]] = mapped_column(Float)
    filled_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_fill_price: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    strategy_name: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    signal_edge: Mapped[Optional[float]] = mapped_column(Float)
    signal_confidence: Mapped[Optional[float]] = mapped_column(Float)
    kelly_fraction: Mapped[Optional[float]] = mapped_column(Float)
    notes: Mapped[Optional[str]] = mapped_column(Text)

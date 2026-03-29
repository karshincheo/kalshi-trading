from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Fill(Base):
    __tablename__ = "fills"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    strategy_name: Mapped[Optional[str]] = mapped_column(String(50))
    broker_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

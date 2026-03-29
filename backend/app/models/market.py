from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Integer, DateTime, Text, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class Market(Base, TimestampMixin):
    __tablename__ = "markets"

    ticker: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_ticker: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active|closed|settled
    yes_bid: Mapped[Optional[float]] = mapped_column(Float)
    yes_ask: Mapped[Optional[float]] = mapped_column(Float)
    yes_mid: Mapped[Optional[float]] = mapped_column(Float)
    last_price: Mapped[Optional[float]] = mapped_column(Float)
    volume_24h: Mapped[Optional[int]] = mapped_column(Integer)
    open_interest: Mapped[Optional[int]] = mapped_column(Integer)
    close_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    result: Mapped[Optional[str]] = mapped_column(String(10))  # "yes" | "no"

    def mid_price(self) -> Optional[float]:
        if self.yes_bid is not None and self.yes_ask is not None:
            return (self.yes_bid + self.yes_ask) / 2
        return self.yes_mid or self.last_price


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (
        Index("idx_snapshots_ticker_ts", "ticker", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(100), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    yes_bid: Mapped[Optional[float]] = mapped_column(Float)
    yes_ask: Mapped[Optional[float]] = mapped_column(Float)
    yes_mid: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[Optional[int]] = mapped_column(Integer)
    open_interest: Mapped[Optional[int]] = mapped_column(Integer)


class OrderbookSnapshot(Base):
    __tablename__ = "orderbook_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bids_json: Mapped[str] = mapped_column(Text, nullable=False)  # [[price, size], ...]
    asks_json: Mapped[str] = mapped_column(Text, nullable=False)

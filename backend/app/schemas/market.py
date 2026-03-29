from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class MarketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    event_ticker: str
    title: str
    subtitle: Optional[str] = None
    category: Optional[str] = None
    status: str
    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    yes_mid: Optional[float] = None
    last_price: Optional[float] = None
    volume_24h: Optional[int] = None
    open_interest: Optional[int] = None
    close_time: Optional[datetime] = None
    result: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MarketSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    timestamp: datetime
    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    yes_mid: Optional[float] = None
    volume: Optional[int] = None


class OrderbookLevel(BaseModel):
    price: float
    size: int


class OrderbookOut(BaseModel):
    ticker: str
    timestamp: datetime
    bids: list[OrderbookLevel]
    asks: list[OrderbookLevel]

from __future__ import annotations
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field


class OrderRequest(BaseModel):
    ticker: str
    action: Literal["buy_yes", "buy_no", "sell_yes", "sell_no"]
    order_type: Literal["market", "limit"] = "market"
    count: int = Field(ge=1, description="Number of contracts")
    limit_price: Optional[float] = Field(None, ge=0.01, le=0.99, description="Limit price 0-1")
    strategy_name: Optional[str] = None
    notes: Optional[str] = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    broker_mode: str
    ticker: str
    side: str
    order_type: str
    action: str
    count: int
    limit_price: Optional[float] = None
    filled_count: int
    avg_fill_price: Optional[float] = None
    status: str
    strategy_name: Optional[str] = None
    signal_edge: Optional[float] = None
    kelly_fraction: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class FillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    ticker: str
    side: str
    action: str
    count: int
    price: float
    fee: float
    strategy_name: Optional[str] = None
    broker_mode: str
    filled_at: datetime

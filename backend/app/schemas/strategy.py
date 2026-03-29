from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict


class StrategyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    enabled: bool
    params: dict[str, Any] = {}
    capital_pct: float
    updated_at: datetime


class StrategyUpdate(BaseModel):
    enabled: Optional[bool] = None
    params: Optional[dict[str, Any]] = None
    capital_pct: Optional[float] = None


class SignalOut(BaseModel):
    ticker: str
    direction: str  # buy_yes|buy_no|sell_yes|sell_no
    fair_value: float  # estimated true probability
    market_price: float
    edge: float  # fair_value - market_price (signed)
    confidence: float  # 0-1
    suggested_size: int
    kelly_fraction: float
    strategy_name: str
    metadata: dict[str, Any] = {}
    generated_at: datetime


class OpportunityOut(BaseModel):
    ticker: str
    title: str
    category: Optional[str] = None
    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    yes_mid: Optional[float] = None
    close_time: Optional[datetime] = None
    volume_24h: Optional[int] = None
    edge_score: float        # composite 0-100
    fair_value: float
    market_price: float
    edge: float
    confidence: float
    kelly_fraction: float
    recommended_contracts: int
    strategy_name: str
    signal_direction: str
    metadata: dict[str, Any] = {}

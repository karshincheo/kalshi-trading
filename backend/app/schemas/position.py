from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    broker_mode: str
    ticker: str
    contract_side: str
    count: int
    avg_cost: float
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    realized_pnl: float
    strategy_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @property
    def pnl_pct(self) -> Optional[float]:
        if self.avg_cost and self.avg_cost > 0:
            return (self.unrealized_pnl or 0) / (self.avg_cost * self.count)
        return None

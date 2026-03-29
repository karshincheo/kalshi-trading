from __future__ import annotations
from typing import Optional
from sqlalchemy import String, Float, Integer, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class StrategyConfig(Base, TimestampMixin):
    __tablename__ = "strategy_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    params_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    capital_pct: Mapped[float] = mapped_column(Float, default=0.1)  # fraction of portfolio

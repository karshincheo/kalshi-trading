from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, DateTime, Text, UniqueConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class ExternalData(Base):
    __tablename__ = "external_data"
    __table_args__ = (
        UniqueConstraint("source", "series_id", "timestamp", name="uq_external_data"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # bls|fred|news
    series_id: Mapped[str] = mapped_column(String(100), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[Optional[float]] = mapped_column(Float)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)

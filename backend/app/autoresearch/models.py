"""ORM models for tracking autoresearch runs and iterations."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow


class AutoresearchRun(Base, TimestampMixin):
    """One execution of the autoresearch loop."""

    __tablename__ = "autoresearch_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running, completed, failed, stopped
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_iterations: Mapped[int] = mapped_column(Integer, default=0)
    best_brier: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    best_sharpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    best_iteration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    iterations: Mapped[list["AutoresearchIteration"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AutoresearchIteration(Base):
    """One iteration within an autoresearch run."""

    __tablename__ = "autoresearch_iterations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("autoresearch_runs.id"), nullable=False)
    iteration_num: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_code: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, default="")

    # Metrics
    train_brier: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    val_brier: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    train_sharpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    val_sharpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    num_trades: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    elapsed_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Status
    error_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    commit_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped["AutoresearchRun"] = relationship(back_populates="iterations")

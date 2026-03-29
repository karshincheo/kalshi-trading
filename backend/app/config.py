"""
Application configuration via pydantic-settings.
All settings are read from environment variables / .env file.
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BrokerMode(str, Enum):
    PAPER = "paper"
    DEMO = "demo"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────
    app_name: str = "Kalshi Trading Bot"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str | list) -> list[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return [v]
        return v

    # ── Broker ─────────────────────────────────────────────────
    broker_mode: BrokerMode = BrokerMode.PAPER
    kalshi_api_key: Optional[str] = None
    kalshi_private_key_path: Optional[str] = None
    kalshi_private_key_b64: Optional[str] = None
    kalshi_live_base_url: str = "https://trading-api.kalshi.com/trade-api/v2"
    kalshi_demo_base_url: str = "https://demo-trading-api.kalshi.co/trade-api/v2"

    @property
    def kalshi_base_url(self) -> str:
        if self.broker_mode == BrokerMode.LIVE:
            return self.kalshi_live_base_url
        return self.kalshi_demo_base_url

    # ── Database ───────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/kalshi.db"

    # ── Paper Trading ──────────────────────────────────────────
    paper_initial_balance: float = 10_000.0
    paper_slippage_bps: float = 5.0

    # ── Risk Controls ──────────────────────────────────────────
    max_position_pct: float = 0.05
    max_portfolio_exposure_pct: float = 0.50
    max_daily_loss_pct: float = 0.10
    default_kelly_fraction: float = 0.25
    min_edge_threshold: float = 0.02  # minimum edge to trade (2%)

    # ── Workers ────────────────────────────────────────────────
    market_poll_interval_seconds: int = 30
    strategy_tick_interval_seconds: int = 60
    pnl_calc_interval_seconds: int = 60

    # ── External APIs ──────────────────────────────────────────
    bls_api_key: Optional[str] = None
    fred_api_key: Optional[str] = None
    news_api_key: Optional[str] = None

    # ── Alerts ─────────────────────────────────────────────────
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


settings = Settings()

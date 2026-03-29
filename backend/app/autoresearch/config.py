"""Configuration for the Autonomous Climate Quant Researcher."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class AutoresearchSettings(BaseSettings):
    """All settings for the autoresearch loop, loaded from env / .env."""

    model_config = {"env_prefix": "AUTORESEARCH_"}

    # --- LLM ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4096

    # --- Loop control ---
    max_iterations: int = 1000
    target_brier: float = 0.15
    plateau_patience: int = 20

    # --- Sandbox ---
    sandbox_timeout_seconds: int = 60
    sandbox_max_retries: int = 3
    sandbox_dir: str = "/tmp/autoresearch_sandbox"

    # --- Data splits ---
    train_pct: float = 0.70
    val_pct: float = 0.15
    # holdout_pct is implicitly 1 - train_pct - val_pct

    # --- Trading sim ---
    initial_capital: float = 10_000.0
    kelly_fraction: float = 0.25
    slippage_bps: float = 5.0
    kalshi_fee_bps: float = 7.0  # Kalshi taker fee

    # --- Phase 3 live cap ---
    max_daily_spend: float = 50.0

    # --- Paths ---
    data_dir: Path = Path(__file__).resolve().parents[2] / "data" / "autoresearch"
    weather_cache_dir: Optional[Path] = None
    kalshi_cache_dir: Optional[Path] = None
    iterations_dir: Optional[Path] = None

    # --- Kalshi public API ---
    kalshi_api_base: str = "https://api.elections.kalshi.com/trade-api/v2"

    # --- Open-Meteo ---
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    climatology_years: int = 30

    # --- Collector ---
    collector_interval_seconds: int = 300  # 5 minutes

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.weather_cache_dir is None:
            self.weather_cache_dir = self.data_dir / "weather_cache"
        if self.kalshi_cache_dir is None:
            self.kalshi_cache_dir = self.data_dir / "kalshi_cache"
        if self.iterations_dir is None:
            self.iterations_dir = self.data_dir / "iterations"

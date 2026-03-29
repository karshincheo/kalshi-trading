"""
Module A: Immutable Data Pipeline.

Merges collected Kalshi temperature market snapshots with Open-Meteo weather
data into a standardized DataFrame. Splits into train/val/holdout sets.

The agent has read-only access to the output; label columns are stripped
before passing data to the strategy sandbox.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from app.autoresearch.config import AutoresearchSettings
from app.autoresearch.collector import TemperatureMarketCollector
from app.autoresearch.market_filter import CITY_COORDS
from app.autoresearch.weather_client import OpenMeteoClient

logger = logging.getLogger(__name__)

# Columns visible to the agent (NO labels)
AGENT_COLUMNS = [
    "timestamp", "market_ticker", "city", "target_date", "strike_temp_f",
    "yes_bid", "yes_ask", "yes_mid", "spread", "volume_24h", "open_interest",
    "hours_to_close",
    "forecast_high_f", "forecast_low_f", "forecast_mean_f",
    "forecast_spread_f", "forecast_precip_mm", "forecast_wind_kph",
    "forecast_humidity_pct", "forecast_lead_hours",
    "climatology_high_f", "climatology_low_f", "climatology_std_f",
    "forecast_vs_climo", "forecast_vs_strike", "implied_prob",
]

# Label columns — NEVER given to the agent
LABEL_COLUMNS = ["actual_high_f", "actual_low_f", "outcome"]


class DataPipeline:
    """Builds the merged Kalshi + weather dataset for autoresearch."""

    def __init__(self, config: AutoresearchSettings) -> None:
        self.config = config
        self.collector = TemperatureMarketCollector(config)
        self.weather = OpenMeteoClient(
            cache_dir=config.weather_cache_dir,
            archive_url=config.open_meteo_archive_url,
            forecast_url=config.open_meteo_forecast_url,
        )

    def close(self) -> None:
        self.collector.close()
        self.weather.close()

    def build_dataset(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """
        Build the full merged dataset from collected data.

        Returns DataFrame with both AGENT_COLUMNS and LABEL_COLUMNS.
        """
        # Load collected Kalshi snapshots
        snapshots = self.collector.load_all_snapshots()
        if snapshots.empty:
            logger.warning("No collected Kalshi data found.")
            return pd.DataFrame()

        settlements = self.collector.load_settlements()

        # Parse dates
        snapshots["timestamp"] = pd.to_datetime(snapshots["timestamp"])
        snapshots["target_date"] = pd.to_datetime(snapshots["target_date"]).dt.date

        if start_date:
            snapshots = snapshots[snapshots["target_date"] >= start_date]
        if end_date:
            snapshots = snapshots[snapshots["target_date"] <= end_date]

        if snapshots.empty:
            logger.warning("No data in date range.")
            return pd.DataFrame()

        # Enrich with weather data and labels
        rows = []
        cities_dates = snapshots.groupby(["city", "target_date"]).first().index.tolist()

        # Pre-fetch weather data per (city, target_date)
        weather_cache = {}
        climo_cache = {}

        for city, target_dt in cities_dates:
            if city not in CITY_COORDS:
                continue
            lat, lon = CITY_COORDS[city]

            # Climatology (cached per city+month+day)
            climo_key = (city, target_dt.month, target_dt.day)
            if climo_key not in climo_cache:
                climo_cache[climo_key] = self.weather.get_climatology(
                    lat, lon, target_dt, years=self.config.climatology_years
                )

            # Actual observations for the target date
            weather_cache[(city, target_dt)] = self.weather.get_historical_daily(
                lat, lon, target_dt, target_dt
            )

        # Build rows
        for _, snap in snapshots.iterrows():
            city = snap["city"]
            target_dt = snap["target_date"]

            if city not in CITY_COORDS:
                continue

            lat, lon = CITY_COORDS[city]
            ts = snap["timestamp"]

            # Forecast as of snapshot time
            issued_date = ts.date() if hasattr(ts, "date") else ts
            forecast = self.weather.get_forecast_for_date(
                lat, lon, target_dt, issued_date
            )

            # Climatology
            climo_key = (city, target_dt.month, target_dt.day)
            climo = climo_cache.get(climo_key, {})

            # Actual weather (for labels only)
            actual_df = weather_cache.get((city, target_dt), pd.DataFrame())
            actual_high = np.nan
            actual_low = np.nan
            if not actual_df.empty:
                actual_high = actual_df.iloc[0].get("high_f", np.nan)
                actual_low = actual_df.iloc[0].get("low_f", np.nan)

            # Settlement outcome
            outcome = np.nan
            strike = snap.get("strike_temp_f")
            is_high = snap.get("is_high", True)
            if strike is not None and not np.isnan(actual_high if is_high else actual_low):
                actual_temp = actual_high if is_high else actual_low
                outcome = 1 if actual_temp >= strike else 0

            # Also check settlements table
            if np.isnan(outcome) and not settlements.empty:
                match = settlements[settlements["ticker"] == snap["ticker"]]
                if not match.empty:
                    result = match.iloc[0]["result"]
                    outcome = 1 if result == "yes" else 0

            # Compute derived features
            yes_bid = snap.get("yes_bid") or 0
            yes_ask = snap.get("yes_ask") or 1
            yes_mid = snap.get("yes_mid") or (yes_bid + yes_ask) / 2

            close_time = pd.to_datetime(snap.get("close_time"))
            hours_to_close = np.nan
            if pd.notna(close_time) and pd.notna(ts):
                hours_to_close = max(0, (close_time - ts).total_seconds() / 3600)

            forecast_high = forecast["high_f"] if forecast else np.nan
            forecast_low = forecast["low_f"] if forecast else np.nan
            climo_high_mean = climo.get("high_f_mean", np.nan)
            climo_high_std = climo.get("high_f_std", 5.0)

            row = {
                # Identifiers
                "timestamp": ts,
                "market_ticker": snap["ticker"],
                "city": city,
                "target_date": target_dt,
                "strike_temp_f": strike,
                # Market data
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "yes_mid": yes_mid,
                "spread": yes_ask - yes_bid,
                "volume_24h": snap.get("volume_24h", 0),
                "open_interest": snap.get("open_interest", 0),
                "hours_to_close": hours_to_close,
                # Forecast
                "forecast_high_f": forecast_high,
                "forecast_low_f": forecast_low,
                "forecast_mean_f": forecast["mean_f"] if forecast else np.nan,
                "forecast_spread_f": (
                    abs(forecast_high - forecast_low) if forecast and not np.isnan(forecast_high) else np.nan
                ),
                "forecast_precip_mm": forecast["precip_mm"] if forecast else np.nan,
                "forecast_wind_kph": forecast["wind_kph"] if forecast else np.nan,
                "forecast_humidity_pct": forecast["humidity_pct"] if forecast else np.nan,
                "forecast_lead_hours": forecast["lead_days"] * 24 if forecast else np.nan,
                # Climatology
                "climatology_high_f": climo_high_mean,
                "climatology_low_f": climo.get("low_f_mean", np.nan),
                "climatology_std_f": climo_high_std,
                # Derived
                "forecast_vs_climo": (
                    forecast_high - climo_high_mean
                    if not np.isnan(forecast_high) and not np.isnan(climo_high_mean)
                    else np.nan
                ),
                "forecast_vs_strike": (
                    forecast_high - strike
                    if strike is not None and not np.isnan(forecast_high)
                    else np.nan
                ),
                "implied_prob": yes_mid,
                # Labels (NEVER visible to agent)
                "actual_high_f": actual_high,
                "actual_low_f": actual_low,
                "outcome": outcome,
            }
            rows.append(row)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df.sort_values(["target_date", "timestamp"]).reset_index(drop=True)
        logger.info(
            "Built dataset: %d rows, %d unique markets, dates %s to %s",
            len(df),
            df["market_ticker"].nunique(),
            df["target_date"].min(),
            df["target_date"].max(),
        )
        return df

    def split(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Chronological split by target_date.

        Returns (train, validation, holdout).
        """
        dates = sorted(df["target_date"].unique())
        n = len(dates)
        if n < 3:
            logger.warning("Too few dates to split: %d", n)
            return df, pd.DataFrame(), pd.DataFrame()

        train_cutoff = dates[int(n * self.config.train_pct)]
        val_cutoff = dates[int(n * (self.config.train_pct + self.config.val_pct))]

        train = df[df["target_date"] < train_cutoff].copy()
        val = df[
            (df["target_date"] >= train_cutoff) & (df["target_date"] < val_cutoff)
        ].copy()
        holdout = df[df["target_date"] >= val_cutoff].copy()

        logger.info(
            "Split: train=%d (<%s), val=%d (<%s), holdout=%d",
            len(train), train_cutoff, len(val), val_cutoff, len(holdout),
        )
        return train, val, holdout

    @staticmethod
    def get_agent_view(df: pd.DataFrame) -> pd.DataFrame:
        """Strip label columns — this is what the strategy sees."""
        cols = [c for c in AGENT_COLUMNS if c in df.columns]
        return df[cols].copy()

    @staticmethod
    def has_labels(df: pd.DataFrame) -> bool:
        """Check if a DataFrame contains valid outcome labels."""
        if "outcome" not in df.columns:
            return False
        return df["outcome"].notna().sum() > 0

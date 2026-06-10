"""
Open-Meteo weather data client.

Fetches historical observations, forecast archives, and climatology.
All responses are cached to disk to avoid repeat API calls.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

def _c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


class OpenMeteoClient:
    """Thin wrapper around the Open-Meteo Archive & Forecast APIs."""

    def __init__(
        self,
        cache_dir: Path,
        archive_url: str = "https://archive-api.open-meteo.com/v1/archive",
        forecast_url: str = "https://api.open-meteo.com/v1/forecast",
        timeout: float = 30.0,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.archive_url = archive_url
        self.forecast_url = forecast_url
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_historical_daily(
        self,
        lat: float,
        lon: float,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Fetch daily weather observations for a location.

        Returns DataFrame with columns:
            date, high_f, low_f, mean_f, precip_mm, wind_kph, humidity_pct
        """
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": ",".join([
                "temperature_2m_max",
                "temperature_2m_min",
                "temperature_2m_mean",
                "precipitation_sum",
                "wind_speed_10m_max",
                "relative_humidity_2m_mean",
            ]),
            "temperature_unit": "celsius",
            "timezone": "America/New_York",
        }

        data = self._cached_get(self.archive_url, params, "daily_obs")
        daily = data.get("daily", {})

        if not daily.get("time"):
            return pd.DataFrame()

        df = pd.DataFrame({
            "date": pd.to_datetime(daily["time"]).date,
            "high_f": [_c_to_f(t) if t is not None else np.nan for t in daily.get("temperature_2m_max", [])],
            "low_f": [_c_to_f(t) if t is not None else np.nan for t in daily.get("temperature_2m_min", [])],
            "mean_f": [_c_to_f(t) if t is not None else np.nan for t in daily.get("temperature_2m_mean", [])],
            "precip_mm": daily.get("precipitation_sum", []),
            "wind_kph": daily.get("wind_speed_10m_max", []),
            "humidity_pct": daily.get("relative_humidity_2m_mean", []),
        })
        return df

    def get_forecast_for_date(
        self,
        lat: float,
        lon: float,
        forecast_date: date,
        issued_date: date,
    ) -> Optional[dict]:
        """
        Get what the forecast predicted for `forecast_date` as of `issued_date`.

        Uses the Open-Meteo archive to retrieve historical forecasts.
        Returns dict with: high_f, low_f, mean_f, precip_mm, wind_kph, humidity_pct, lead_days
        """
        lead_days = (forecast_date - issued_date).days
        if lead_days < 0:
            return None

        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": issued_date.isoformat(),
            "end_date": forecast_date.isoformat(),
            "daily": ",".join([
                "temperature_2m_max",
                "temperature_2m_min",
                "temperature_2m_mean",
                "precipitation_sum",
                "wind_speed_10m_max",
                "relative_humidity_2m_mean",
            ]),
            "temperature_unit": "celsius",
            "timezone": "America/New_York",
        }

        data = self._cached_get(self.archive_url, params, "forecast_hist")
        daily = data.get("daily", {})
        times = daily.get("time", [])

        if not times:
            return None

        # Find the index for the forecast_date
        target = forecast_date.isoformat()
        if target not in times:
            # Use the last available date
            idx = len(times) - 1
        else:
            idx = times.index(target)

        def _safe_get(key, idx):
            vals = daily.get(key, [])
            if idx < len(vals) and vals[idx] is not None:
                return vals[idx]
            return np.nan

        high_c = _safe_get("temperature_2m_max", idx)
        low_c = _safe_get("temperature_2m_min", idx)
        mean_c = _safe_get("temperature_2m_mean", idx)

        return {
            "high_f": _c_to_f(high_c) if not np.isnan(high_c) else np.nan,
            "low_f": _c_to_f(low_c) if not np.isnan(low_c) else np.nan,
            "mean_f": _c_to_f(mean_c) if not np.isnan(mean_c) else np.nan,
            "precip_mm": _safe_get("precipitation_sum", idx),
            "wind_kph": _safe_get("wind_speed_10m_max", idx),
            "humidity_pct": _safe_get("relative_humidity_2m_mean", idx),
            "lead_days": lead_days,
        }

    def get_climatology(
        self,
        lat: float,
        lon: float,
        target_date: date,
        years: int = 30,
    ) -> dict:
        """
        Compute 30-year climatological average and std for a calendar date.

        Returns: {high_f_mean, high_f_std, low_f_mean, low_f_std}
        """
        month = target_date.month
        day = target_date.day
        current_year = target_date.year


        # Fetch in large chunks to minimize API calls
        start_year = max(current_year - years, 1950)
        chunk_start = date(start_year, 1, 1)
        chunk_end = date(current_year - 1, 12, 31)

        df = self.get_historical_daily(lat, lon, chunk_start, chunk_end)
        if df.empty:
            return {"high_f_mean": np.nan, "high_f_std": np.nan, "low_f_mean": np.nan, "low_f_std": np.nan}

        # Filter to matching calendar date (allow +/- 2 days for robustness)
        df["_date"] = pd.to_datetime(df["date"])
        df["_month"] = df["_date"].dt.month
        df["_day"] = df["_date"].dt.day

        mask = (df["_month"] == month) & (df["_day"].between(max(1, day - 2), min(31, day + 2)))
        subset = df.loc[mask]

        if subset.empty:
            return {"high_f_mean": np.nan, "high_f_std": np.nan, "low_f_mean": np.nan, "low_f_std": np.nan}

        return {
            "high_f_mean": float(subset["high_f"].mean()),
            "high_f_std": float(subset["high_f"].std()) if len(subset) > 1 else 5.0,
            "low_f_mean": float(subset["low_f"].mean()),
            "low_f_std": float(subset["low_f"].std()) if len(subset) > 1 else 5.0,
        }

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------

    def _cache_key(self, url: str, params: dict, prefix: str) -> Path:
        """Generate a deterministic cache file path."""
        raw = json.dumps({"url": url, "params": params}, sort_keys=True)
        h = hashlib.md5(raw.encode()).hexdigest()[:12]
        return self.cache_dir / f"{prefix}_{h}.json"

    def _cached_get(self, url: str, params: dict, prefix: str) -> dict:
        """GET with disk caching."""
        cache_path = self._cache_key(url, params, prefix)
        if cache_path.exists():
            with open(cache_path) as f:
                return json.load(f)

        logger.info("Open-Meteo request: %s params=%s", url, params)
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(data, f)

        return data

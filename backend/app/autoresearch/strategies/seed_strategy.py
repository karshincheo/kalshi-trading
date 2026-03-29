"""
Seed Strategy: Forecast-vs-strike probability estimation.

Hypothesis: The weather forecast high temperature, compared to the strike
temperature and normalized by climatological standard deviation, provides
a baseline probability estimate via the normal CDF. When this estimate
diverges from the market's implied probability by more than 5%, there is
a tradeable edge.
"""
from scipy.stats import norm


def predict(row: dict) -> dict:
    forecast_high = row.get("forecast_high_f")
    strike = row.get("strike_temp_f")
    climo_std = row.get("climatology_std_f")
    market_mid = row.get("yes_mid", 0.5) or 0.5

    # If missing data, pass
    if forecast_high is None or strike is None or climo_std is None:
        return {
            "action": "PASS",
            "fair_value": market_mid,
            "confidence": 0.0,
            "limit_price": None,
        }

    # Handle zero or near-zero std
    if climo_std <= 0.5:
        climo_std = 5.0

    # Z-score: how many std devs the forecast is above the strike
    z = (forecast_high - strike) / climo_std

    # Convert to probability via normal CDF
    fair_value = float(norm.cdf(z))

    # Clamp to avoid extreme values
    fair_value = max(0.02, min(0.98, fair_value))

    edge = fair_value - market_mid
    min_edge = 0.05

    if abs(edge) < min_edge:
        return {
            "action": "PASS",
            "fair_value": fair_value,
            "confidence": 0.3,
            "limit_price": None,
        }
    elif edge > 0:
        return {
            "action": "BUY_YES",
            "fair_value": fair_value,
            "confidence": min(0.8, abs(edge) * 5),
            "limit_price": None,
        }
    else:
        return {
            "action": "BUY_NO",
            "fair_value": fair_value,
            "confidence": min(0.8, abs(edge) * 5),
            "limit_price": None,
        }

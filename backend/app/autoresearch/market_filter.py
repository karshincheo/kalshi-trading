"""Identify and parse Kalshi temperature prediction markets."""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from app.schemas.market import MarketOut


# --- City coordinates for Open-Meteo lookups ---
CITY_COORDS: dict[str, tuple[float, float]] = {
    "NYC": (40.7128, -74.0060),
    "CHI": (41.8781, -87.6298),
    "LAX": (34.0522, -118.2437),
    "MIA": (25.7617, -80.1918),
    "DEN": (39.7392, -104.9903),
    "ATL": (33.7490, -84.3880),
    "AUS": (30.2672, -97.7431),
    "DAL": (32.7767, -96.7970),
    "HOU": (29.7604, -95.3698),
    "PHX": (33.4484, -112.0740),
    "SEA": (47.6062, -122.3321),
    "BOS": (42.3601, -71.0589),
    "DCA": (38.9072, -77.0369),  # Washington DC
    "MSP": (44.9778, -93.2650),  # Minneapolis
    "DET": (42.3314, -83.0458),
    "SFO": (37.7749, -122.4194),
}

# Aliases that appear in tickers / titles
CITY_ALIASES: dict[str, str] = {
    "NEW YORK": "NYC",
    "NEWYORK": "NYC",
    "CHICAGO": "CHI",
    "LOS ANGELES": "LAX",
    "LA": "LAX",
    "MIAMI": "MIA",
    "DENVER": "DEN",
    "ATLANTA": "ATL",
    "AUSTIN": "AUS",
    "DALLAS": "DAL",
    "HOUSTON": "HOU",
    "PHOENIX": "PHX",
    "SEATTLE": "SEA",
    "BOSTON": "BOS",
    "WASHINGTON": "DCA",
    "DC": "DCA",
    "MINNEAPOLIS": "MSP",
    "DETROIT": "DET",
    "SAN FRANCISCO": "SFO",
    "SF": "SFO",
}

# Regex patterns for temperature market tickers
_TICKER_PATTERNS = [
    re.compile(r"^(?:KX)?HIGHTEMP", re.IGNORECASE),
    re.compile(r"^(?:KX)?LOWTEMP", re.IGNORECASE),
    re.compile(r"^TEMP-", re.IGNORECASE),
    re.compile(r"INXHIGHTEMP", re.IGNORECASE),
    re.compile(r"INXLOWTEMP", re.IGNORECASE),
]

_TITLE_KEYWORDS = [
    "temperature",
    "high temp",
    "low temp",
    "degrees",
    "°f",
    "fahrenheit",
]

# Pattern to extract date from ticker: e.g. KXHIGHTEMP-NYC-24DEC20 → 2024-12-20
_TICKER_DATE_RE = re.compile(
    r"(\d{2})([A-Z]{3})(\d{2})$", re.IGNORECASE
)
_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# Pattern to extract strike temperature from title
# e.g. "Will the high temperature in NYC be above 75°F?" → 75
_STRIKE_RE = re.compile(
    r"(?:above|below|at least|under|over|exceed)\s+(\d+)\s*(?:°?[fF]|degrees)",
    re.IGNORECASE,
)
# Fallback: any number followed by °F
_STRIKE_FALLBACK_RE = re.compile(r"(\d+)\s*°\s*[fF]")


def is_temperature_market(market: MarketOut) -> bool:
    """Return True if this market is a daily temperature prediction market."""
    ticker = market.event_ticker or market.ticker
    title = market.title or ""

    # Check ticker patterns
    for pattern in _TICKER_PATTERNS:
        if pattern.search(ticker):
            return True

    # Check title keywords
    title_lower = title.lower()
    if any(kw in title_lower for kw in _TITLE_KEYWORDS):
        # Extra check: must also mention a city or "temp"
        if "temp" in title_lower or _match_city_in_text(title_lower):
            return True

    # Check category
    if market.category and market.category.lower() in ("climate", "weather"):
        if "temp" in title_lower or "degree" in title_lower:
            return True

    return False


def _match_city_in_text(text: str) -> Optional[str]:
    """Return city code if any known city name appears in text."""
    text_upper = text.upper()
    for alias, code in CITY_ALIASES.items():
        if alias in text_upper:
            return code
    for code in CITY_COORDS:
        if code in text_upper:
            return code
    return None


def extract_city(market: MarketOut) -> Optional[str]:
    """Extract the city code from a temperature market's ticker or title."""
    ticker = (market.event_ticker or market.ticker).upper()
    title = (market.title or "").upper()

    # Try ticker first: KXHIGHTEMP-NYC-24DEC20
    for code in CITY_COORDS:
        if code in ticker:
            return code

    # Try title
    return _match_city_in_text(title)


def extract_target_date(market: MarketOut) -> Optional[date]:
    """Extract the target date from a temperature market's ticker."""
    ticker = market.event_ticker or market.ticker
    m = _TICKER_DATE_RE.search(ticker)
    if m:
        # Kalshi date segments are YEAR-MONTH-DAY, e.g. 26JUN11 -> 2026-06-11.
        year_short = int(m.group(1))
        month_str = m.group(2).upper()
        day = int(m.group(3))
        month = _MONTH_MAP.get(month_str)
        if month:
            try:
                candidate = date(2000 + year_short, month, day)
            except ValueError:
                candidate = None
            # Guard against format drift: the target date must sit near the
            # market close. If it doesn't, fall through to close_time below.
            if candidate is not None:
                if market.close_time is None:
                    return candidate
                if abs((candidate - market.close_time.date()).days) <= 2:
                    return candidate

    # Fallback: try to parse from close_time
    if market.close_time:
        return market.close_time.date()
    return None


def extract_city_and_date(
    market: MarketOut,
) -> Optional[tuple[str, date]]:
    """Extract (city_code, target_date) from a temperature market."""
    city = extract_city(market)
    target = extract_target_date(market)
    if city and target:
        return (city, target)
    return None


_TICKER_STRIKE_RE = __import__("re").compile(r"-[TB](\d+(?:\.\d+)?)$")


def extract_strike_temp(market: MarketOut) -> Optional[float]:
    """Extract the strike temperature (°F) from the ticker suffix or title."""
    # Current Kalshi format encodes the strike in the ticker: -T95, -B94.5
    m = _TICKER_STRIKE_RE.search(market.ticker or "")
    if m:
        return float(m.group(1))
    title = market.title or ""
    m = _STRIKE_RE.search(title)
    if m:
        return float(m.group(1))
    m = _STRIKE_FALLBACK_RE.search(title)
    if m:
        return float(m.group(1))
    return None


def is_high_temp_market(market: MarketOut) -> bool:
    """Return True if this is a HIGH temperature market (vs low)."""
    ticker = (market.event_ticker or market.ticker).upper()
    title = (market.title or "").lower()
    if "HIGHTEMP" in ticker or "high temp" in title or "high temperature" in title:
        return True
    if "LOWTEMP" in ticker or "low temp" in title or "low temperature" in title:
        return False
    # Default to high if ambiguous
    return True


def parse_temperature_market(market: MarketOut) -> Optional[dict]:
    """
    Parse all relevant fields from a temperature market.

    Returns None if this isn't a temperature market or fields can't be parsed.
    Returns dict with: city, target_date, strike_temp_f, is_high, ticker, title
    """
    if not is_temperature_market(market):
        return None

    city = extract_city(market)
    target = extract_target_date(market)
    strike = extract_strike_temp(market)

    if not city or not target:
        return None

    return {
        "city": city,
        "target_date": target,
        "strike_temp_f": strike,
        "is_high": is_high_temp_market(market),
        "ticker": market.ticker,
        "event_ticker": market.event_ticker,
        "title": market.title,
    }

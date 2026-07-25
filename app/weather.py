"""Weather fetching and season calculation utilities."""
import time
from datetime import date
from typing import Optional

import httpx

# Module-level cache: (lat, lon) -> (data, timestamp)
_weather_cache = {}
CACHE_TTL_SECONDS = 30 * 60  # 30 minutes

# WMO weather code descriptions
WMO_CODES = {
    0: "clear",
    1: "partly cloudy",
    2: "partly cloudy",
    3: "partly cloudy",
    45: "fog",
    48: "fog",
    51: "rain",
    53: "rain",
    55: "rain",
    56: "rain",
    57: "rain",
    61: "rain",
    63: "rain",
    65: "rain",
    66: "rain",
    67: "rain",
    71: "snow",
    73: "snow",
    75: "snow",
    77: "snow",
    80: "showers",
    81: "showers",
    82: "showers",
    85: "snow",
    86: "snow",
    95: "thunderstorm",
    96: "thunderstorm",
    99: "thunderstorm",
}


def weather_code_to_description(code: int) -> str:
    """Map WMO weather code to short description."""
    return WMO_CODES.get(code, "unknown")


async def fetch_weather(lat: float, lon: float) -> Optional[dict]:
    """Fetch weather from Open-Meteo with caching."""
    cache_key = (lat, lon)
    now = time.time()

    # Check cache
    if cache_key in _weather_cache:
        data, timestamp = _weather_cache[cache_key]
        if now - timestamp < CACHE_TTL_SECONDS:
            return data

    # Fetch from API
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,weather_code,apparent_temperature"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        f"&temperature_unit=fahrenheit&timezone=auto&forecast_days=1"
    )

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        raw = resp.json()

    # Parse response
    current = raw.get("current", {})
    daily = raw.get("daily", {})

    data = {
        "temp_f": current.get("temperature_2m"),
        "feels_like_f": current.get("apparent_temperature"),
        "weather_code": current.get("weather_code"),
        "description": weather_code_to_description(current.get("weather_code", 0)),
        "high_f": daily.get("temperature_2m_max", [None])[0],
        "low_f": daily.get("temperature_2m_min", [None])[0],
        "precip_prob": daily.get("precipitation_probability_max", [None])[0],
    }

    # Update cache
    _weather_cache[cache_key] = (data, now)

    return data


async def geocode(name: str, count: int = 5) -> list:
    """
    Resolve a place name to candidate locations via Open-Meteo's free
    geocoding API. Returns a list of dicts:
    {name, latitude, longitude, country, admin1}
    """
    url = (
        f"https://geocoding-api.open-meteo.com/v1/search"
        f"?name={name}&count={count}&language=en&format=json"
    )
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        raw = resp.json()

    results = []
    for r in raw.get("results", []) or []:
        results.append(
            {
                "name": r.get("name", ""),
                "latitude": r.get("latitude"),
                "longitude": r.get("longitude"),
                "country": r.get("country", ""),
                "admin1": r.get("admin1", ""),
            }
        )
    return results


# Open-Meteo's standard forecast endpoint covers ~16 days out.
MAX_FORECAST_DAYS_AHEAD = 16

# (lat, lon, start, end) -> (data, timestamp)
_forecast_cache = {}


async def fetch_forecast_range(
    lat: float, lon: float, start_date: str, end_date: str
) -> Optional[list]:
    """
    Fetch a daily forecast for a date range (ISO dates, inclusive).

    Returns a list of day dicts:
    {date, high_f, low_f, precip_prob, weather_code, description}
    or None when the range is entirely beyond forecast coverage.
    Days beyond coverage are simply absent from the result.
    """
    from datetime import date as date_cls, timedelta

    today = date_cls.today()
    start = date_cls.fromisoformat(start_date)
    end = date_cls.fromisoformat(end_date)
    horizon = today + timedelta(days=MAX_FORECAST_DAYS_AHEAD - 1)

    # Entirely out of range (past trips or too far out) -> no forecast
    if end < today or start > horizon:
        return None

    # Clamp to what the API can answer
    q_start = max(start, today)
    q_end = min(end, horizon)

    cache_key = (lat, lon, q_start.isoformat(), q_end.isoformat())
    now = time.time()
    if cache_key in _forecast_cache:
        data, ts = _forecast_cache[cache_key]
        if now - ts < CACHE_TTL_SECONDS:
            return data

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max,temperature_2m_min,"
        f"precipitation_probability_max,weather_code"
        f"&temperature_unit=fahrenheit&timezone=auto"
        f"&start_date={q_start.isoformat()}&end_date={q_end.isoformat()}"
    )
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        raw = resp.json()

    daily = raw.get("daily", {})
    dates = daily.get("time", []) or []
    highs = daily.get("temperature_2m_max", []) or []
    lows = daily.get("temperature_2m_min", []) or []
    precips = daily.get("precipitation_probability_max", []) or []
    codes = daily.get("weather_code", []) or []

    days = []
    for i, d in enumerate(dates):
        code = codes[i] if i < len(codes) else None
        days.append(
            {
                "date": d,
                "high_f": highs[i] if i < len(highs) else None,
                "low_f": lows[i] if i < len(lows) else None,
                "precip_prob": precips[i] if i < len(precips) else None,
                "weather_code": code,
                "description": weather_code_to_description(code if code is not None else -1),
            }
        )

    _forecast_cache[cache_key] = (days, now)
    return days


def season_for_month(month: int) -> str:
    """Get base season from month (Northern Hemisphere)."""
    if month in (12, 1, 2):
        return "winter"
    elif month in (3, 4, 5):
        return "spring"
    elif month in (6, 7, 8):
        return "summer"
    else:  # 9, 10, 11
        return "fall"


def season_for(dt: date, high_f: Optional[float], bands: dict) -> str:
    """
    Determine season based on date and temperature.

    - Base season from month
    - If spring/fall and high_f >= summer_min_f -> summer
    - If spring/fall and high_f <= winter_max_f -> winter
    """
    base = season_for_month(dt.month)

    if high_f is None:
        return base

    if base in ("spring", "fall"):
        summer_min = bands.get("summer_min_f", 75)
        winter_max = bands.get("winter_max_f", 45)

        if high_f >= summer_min:
            return "summer"
        elif high_f <= winter_max:
            return "winter"

    return base

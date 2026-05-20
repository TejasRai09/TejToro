"""
data_fetcher.py  —  Fetch candle data from Upstox API v2.

Key points:
- Upstox does NOT have a native 10-minute interval.
- We fetch 1-minute candles and resample them to 10-minute using pandas.
- Daily/Monthly data is fetched with the 'day' interval.
"""

import time
import requests
import pandas as pd
import threading
from datetime import datetime, date, timedelta
from auth import load_token

# ── API base ──────────────────────────────────────────────────────────────
BASE_URL = "https://api-v2.upstox.com"
# Global lock to prevent overlapping API calls triggerring strict rate limits
API_LOCK = threading.Semaphore(5)  # allow up to 5 concurrent API calls

def _get_headers() -> dict:
    return {
        "accept":        "application/json",
        "Authorization": f"Bearer {load_token()}",
    }


# ── Low-level fetch ───────────────────────────────────────────────────────

def _safe_get(url: str, params: dict = None, max_retries: int = 3) -> requests.Response:
    """Wrapper with global lock and 429 handling."""
    with API_LOCK:
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, headers=_get_headers(), params=params, timeout=15)
                if resp.status_code == 429:
                    # Exponential backoff: 2s, 4s, 8s
                    wait = 2 ** (attempt + 1)
                    print(f"   [WARN] Rate limited (429). Sleeping {wait}s...")
                    time.sleep(wait)
                    continue
                return resp
            except Exception as e:
                print(f"   [WARN] Request error: {e}")
                time.sleep(1)
        return requests.get(url, headers=_get_headers(), params=params, timeout=15) # final try


def _fetch_historical(
    instrument_key: str,
    interval: str,
    from_date: str,
    to_date: str,
) -> pd.DataFrame:
    url = (
        f"{BASE_URL}/historical-candle"
        f"/{requests.utils.quote(instrument_key, safe='')}"
        f"/{interval}/{to_date}/{from_date}"
    )

    resp = _safe_get(url)
    if resp.status_code == 401:
        raise Exception("❌ Upstox API Token Expired (401). Please run 'python auth.py' again.")
    if resp.status_code != 200:
        # print(f"   ❌ {instrument_key}: HTTP {resp.status_code}")
        return pd.DataFrame()

    candles = resp.json().get("data", {}).get("candles", [])
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(
        candles,
        columns=["timestamp", "open", "high", "low", "close", "volume", "oi"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df


def _fetch_intraday(instrument_key: str, interval: str = "1minute") -> pd.DataFrame:
    url = (
        f"{BASE_URL}/historical-candle/intraday"
        f"/{requests.utils.quote(instrument_key, safe='')}"
        f"/{interval}"
    )
    resp = _safe_get(url)
    if resp.status_code == 401:
        raise Exception("❌ Upstox API Token Expired (401). Please run 'python auth.py' again.")
    if resp.status_code != 200:
        return pd.DataFrame()

    candles = resp.json().get("data", {}).get("candles", [])
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(
        candles,
        columns=["timestamp", "open", "high", "low", "close", "volume", "oi"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df


# ── Public API ────────────────────────────────────────────────────────────

def get_10min_candles(instrument_key: str, days_back: int = 5) -> pd.DataFrame:
    """Combines intraday and historical data to return resampled 10-min candles."""
    today_str = date.today().strftime("%Y-%m-%d")
    hist_from = (date.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    hist_df = _fetch_historical(instrument_key, "1minute", hist_from, today_str)
    live_df = _fetch_intraday(instrument_key, "1minute")

    combined = pd.concat([hist_df, live_df])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()

    if combined.empty:
        return pd.DataFrame()

    df_10 = combined.resample("10min", offset="5min", closed="left", label="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["close"])

    df_10 = df_10.between_time("09:15", "15:20")
    return df_10


def get_daily_candles(instrument_key: str, days_back: int = 365) -> pd.DataFrame:
    today_str = date.today().strftime("%Y-%m-%d")
    from_str  = (date.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    return _fetch_historical(instrument_key, "day", from_str, today_str)


def get_monthly_candles(instrument_key: str, months_back: int = 36) -> pd.DataFrame:
    today_str = date.today().strftime("%Y-%m-%d")
    from_str  = (date.today() - timedelta(days=months_back * 30)).strftime("%Y-%m-%d")
    return _fetch_historical(instrument_key, "month", from_str, today_str)


def get_market_quotes(instrument_keys: list[str]) -> dict:
    if not instrument_keys:
        return {}

    url = f"{BASE_URL}/market-quote/quotes"
    params = {"instrument_key": ",".join(instrument_keys)}
    
    resp = _safe_get(url, params=params)
    if resp.status_code == 401:
        raise Exception("❌ Upstox API Token Expired (401). Please run 'python auth.py' again.")
    if resp.status_code != 200:
        return {}

    return resp.json().get("data", {})

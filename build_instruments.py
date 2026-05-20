"""
build_instruments.py — One-time script to build your stock universe.

Run this manually once a month:
    python build_instruments.py

What it does:
1. Downloads Upstox NSE master instrument file
2. Downloads NSE market cap data (bhavcopy)
3. Merges and filters to your tradeable universe
4. Saves instruments.csv — used by the scanner every day

You do NOT run this daily. The scanner reads the saved CSV.
"""

import requests
import pandas as pd
import gzip
import io
import os
from datetime import date, timedelta
from auth import load_token
from config import (
    UPSTOX_INSTRUMENTS_URL,
    INSTRUMENTS_FILE,
    MIN_STOCK_PRICE,
    MAX_STOCK_PRICE,
    MIN_MARKET_CAP_CR,
)

# ── Step 1: Download Upstox NSE Instrument Master ─────────────────────────

def download_upstox_instruments() -> pd.DataFrame:
    print("[FETCH] Downloading Upstox NSE instrument master...")
    resp = requests.get(UPSTOX_INSTRUMENTS_URL, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"Failed to download instruments: HTTP {resp.status_code}")

    # File is gzipped CSV
    with gzip.open(io.BytesIO(resp.content)) as f:
        df = pd.read_csv(f)

    print(f"   Total instruments in NSE master: {len(df)}")
    return df


def filter_upstox_instruments(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip().lower() for c in df.columns]

    print("Columns available:", df.columns.tolist())
    print("Exchange values:", df["exchange"].value_counts().head())

    # ✅ Keep only NSE Equity
    df = df[df["exchange"] == "NSE_EQ"].copy()

    # Clean
    df = df[df["instrument_key"].notna()].copy()
    df = df[df["tradingsymbol"].notna()].copy()

    df = df.rename(columns={"tradingsymbol": "symbol"})
    df = df[["symbol", "instrument_key"]].drop_duplicates(subset="symbol")

    print(f"   After filtering: {len(df)} stocks")
    return df

# ── Step 2: Fetch Real Market Caps from NSE Live API ─────────────────────

_NSE_INDEX_NAMES = [
    "NIFTY 500",
    "NIFTY MIDCAP 150",
    "NIFTY SMALLCAP 250",
]

_NSE_SYMBOL_URLS = [
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
]


def _nse_session() -> requests.Session:
    """Returns a requests Session with NSE cookies initialised."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    })
    session.get("https://www.nseindia.com", timeout=15)
    import time; time.sleep(1)
    return session


def fetch_market_caps_nse() -> pd.DataFrame:
    """
    Fetches real free-float market caps from NSE's live index API.
    Returns DataFrame with columns: symbol, market_cap_cr.
    ffmc (free-float market cap) is in rupees — divide by 1e7 for crores.
    """
    print("[FETCH] Fetching real market caps from NSE live API...")
    session = _nse_session()
    mcap_map = {}

    for index_name in _NSE_INDEX_NAMES:
        url = f"https://www.nseindia.com/api/equity-stockIndices?index={requests.utils.quote(index_name)}"
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                print(f"   [WARN] {index_name}: HTTP {resp.status_code}")
                continue
            rows = resp.json().get("data", [])
            count = 0
            for row in rows:
                sym  = row.get("symbol", "").strip().upper()
                ffmc = row.get("ffmc")
                if sym and ffmc and ffmc > 0:
                    mcap_cr = round(ffmc / 1e7, 2)
                    if sym not in mcap_map:          # first seen = keep (larger index first)
                        mcap_map[sym] = mcap_cr
                    count += 1
            print(f"   {index_name}: {count} stocks with market cap")
        except Exception as e:
            print(f"   [WARN] {index_name}: {e}")

    df = pd.DataFrame([{"symbol": s, "market_cap_cr": m} for s, m in mcap_map.items()])
    print(f"[OK] Real market caps fetched for {len(df)} symbols")
    return df


def get_nse_symbols() -> set:
    """Downloads NSE index constituent symbol lists (for universe building)."""
    headers = {"User-Agent": "Mozilla/5.0"}
    symbols = set()
    for url in _NSE_SYMBOL_URLS:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
            if col:
                symbols |= set(df[col].str.strip().str.upper().dropna())
        except Exception as e:
            print(f"   [WARN] {url}: {e}")
    return symbols


# ── Step 3: Merge Upstox Keys with NSE Universe ───────────────────────────

def filter_by_price_and_build(upstox_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merges Upstox instrument keys with NSE universe + real market caps.
    """
    # Get real market caps from NSE live API
    mcap_df = fetch_market_caps_nse()

    if mcap_df.empty:
        # Fallback: use symbol list only, no market cap filter
        print("   [WARN] Market cap fetch failed — including all NSE symbols without market cap filter")
        syms = get_nse_symbols()
        filtered = upstox_df[upstox_df["symbol"].isin(syms)].copy()
        filtered["market_cap_cr"] = 0
        return filtered

    merged = pd.merge(upstox_df, mcap_df, on="symbol", how="inner")
    before = len(merged)
    merged = merged[merged["market_cap_cr"] >= MIN_MARKET_CAP_CR]
    print(f"   After market cap filter (>= {MIN_MARKET_CAP_CR} Cr): {len(merged)} stocks (removed {before - len(merged)})")
    return merged


# ── Step 4: Get Live Prices And Apply Price Filter ────────────────────────

def apply_price_filter(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fetches live prices in batches and filters stocks outside price range.
    Uses Upstox market quotes API.
    """
    from data_fetcher import get_market_quotes

    print(f"\n[FETCH] Fetching live prices to apply Rs {MIN_STOCK_PRICE}-Rs {MAX_STOCK_PRICE} price filter...")
    print(f"   Stocks to check: {len(df)}")

    keys = df["instrument_key"].tolist()
    price_map = {}

    # Fetch in batches of 50
    for i in range(0, len(keys), 50):
        batch = keys[i: i + 50]
        try:
            quotes = get_market_quotes(batch)
            for api_key, data in quotes.items():
                token = data.get("instrument_token")
                ltp = data.get("last_price")
                if token and ltp:
                    price_map[token] = float(ltp)
        except Exception as e:
            print(f"   [WARN] Batch {i//50 + 1} error: {e}")

    # Map prices back to dataframe
    df = df.copy()
    df["last_price"] = df["instrument_key"].map(price_map)

    before = len(df)
    # Keep stocks within price range (drop those with no price data too)
    df = df[
        (df["last_price"] >= MIN_STOCK_PRICE) &
        (df["last_price"] <= MAX_STOCK_PRICE)
    ]
    print(f"   After price filter Rs {MIN_STOCK_PRICE}-Rs {MAX_STOCK_PRICE}: {len(df)} stocks (removed {before - len(df)})")

    return df


# ── Main Build Flow ───────────────────────────────────────────────────────

def build_instruments():
    print("=" * 60)
    print("  BUILDING INSTRUMENTS UNIVERSE — All NSE EQ")
    print(f"  Filters: NSE EQ | MarketCap >= {MIN_MARKET_CAP_CR}Cr | Price Rs {MIN_STOCK_PRICE}-Rs {MAX_STOCK_PRICE}")
    print("=" * 60)

    # Step 1: Upstox instrument master (all NSE EQ, no index whitelist)
    raw_df = download_upstox_instruments()
    instruments_df = filter_upstox_instruments(raw_df)

    # Step 2 & 3: Yahoo Finance market cap & filter
    merged_df = filter_by_price_and_build(instruments_df)

    # Step 4: Live price filter (requires valid token)
    try:
        final_df = apply_price_filter(merged_df)
    except FileNotFoundError:
        print("\n   [WARN] token.txt not found. Skipping price filter.")
        print("   Run 'python auth.py' first, then re-run this script for price filtering.")
        final_df = merged_df

    # Step 5: Clean and save
    final_df = final_df[["symbol", "instrument_key", "market_cap_cr"]].copy()
    final_df = final_df.sort_values("market_cap_cr", ascending=False).reset_index(drop=True)

    final_df.to_csv(INSTRUMENTS_FILE, index=False)

    print(f"\n[OK] instruments.csv saved with {len(final_df)} stocks")
    print(f"   Location: {os.path.abspath(INSTRUMENTS_FILE)}")
    print(f"\n   Top 10 stocks by market cap:")
    print(final_df.head(10).to_string(index=False))
    print("\n   Run this script again monthly to refresh the universe.")


if __name__ == "__main__":
    build_instruments()

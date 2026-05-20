"""
Fetch real market cap data for NSE instruments using Yahoo Finance.
Reads symbol + instrument_key from instruments.csv and updates market_cap_cr.

Requirements:
    pip install yfinance pandas

Usage:
    python fetch_market_cap.py
"""

import time
import pandas as pd
import yfinance as yf

INPUT_CSV  = "instruments.csv"
OUTPUT_CSV = "instruments.csv"   # overwrite in place
BATCH_SIZE = 50                  # yfinance handles bulk downloads well
SLEEP_SEC  = 1.0                 # polite delay between batches

INR_TO_CR = 1e7  # 1 crore = 10,000,000


def symbol_to_yahoo(symbol: str) -> str:
    """Convert NSE symbol to Yahoo Finance ticker (append .NS)."""
    return f"{symbol}.NS"


def fetch_market_caps(symbols: list) -> dict:
    """
    Download market cap for a list of NSE symbols via yfinance.
    Returns dict: {symbol: market_cap_in_crores or None}
    """
    tickers = [symbol_to_yahoo(s) for s in symbols]
    result  = {}

    data = yf.Tickers(" ".join(tickers))

    for sym, ticker_str in zip(symbols, tickers):
        try:
            info = data.tickers[ticker_str].fast_info
            # fast_info.market_cap is in the stock's currency (INR for .NS)
            mc = getattr(info, "market_cap", None)
            if mc and mc > 0:
                result[sym] = round(mc / INR_TO_CR, 2)
            else:
                # fallback: try full info dict
                full = data.tickers[ticker_str].info
                mc2  = full.get("marketCap")
                result[sym] = round(mc2 / INR_TO_CR, 2) if mc2 else None
        except Exception:
            result[sym] = None

    return result


def main():
    df = pd.read_csv(INPUT_CSV)
    required = {"symbol", "instrument_key", "market_cap_cr"}
    if not required.issubset(df.columns):
        raise ValueError(f"CSV must have columns: {required}")

    print(f"Loaded {len(df)} instruments from '{INPUT_CSV}'")

    symbols  = df["symbol"].tolist()
    batches  = [symbols[i:i+BATCH_SIZE] for i in range(0, len(symbols), BATCH_SIZE)]
    all_caps = {}

    for idx, batch in enumerate(batches, 1):
        print(f"  Batch {idx}/{len(batches)} ({len(batch)} symbols)...", end=" ", flush=True)
        caps = fetch_market_caps(batch)
        all_caps.update(caps)
        got = sum(1 for v in caps.values() if v is not None)
        print(f"{got}/{len(batch)} fetched")
        if idx < len(batches):
            time.sleep(SLEEP_SEC)

    # Map back
    updated, missing = 0, 0
    for i, row in df.iterrows():
        mc = all_caps.get(row["symbol"])
        if mc is not None:
            df.at[i, "market_cap_cr"] = mc
            updated += 1
        else:
            missing += 1
            print(f"  No data for {row['symbol']}")

    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nDone! Updated {updated} rows, {missing} missing.")
    print(f"Saved to '{OUTPUT_CSV}'")


if __name__ == "__main__":
    main()
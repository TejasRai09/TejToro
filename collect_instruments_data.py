"""
collect_instruments_data.py — Download 1 year of daily OHLCV data for ALL stocks in instruments.csv.

This ensures we have data for April 24, 2026 and enough history for backtesting indicators.
"""

import os
import sys
import time
import pandas as pd
from datetime import date, timedelta
from data_fetcher import _fetch_historical

# ── Config ────────────────────────────────────────────────────────────────
OUTPUT_DIR = "backtest_data"
DAYS_BACK  = 400   # ~1 year + buffer for indicator warmup
INSTRUMENTS_FILE = "instruments.csv"

def collect():
    # 1. Load instruments
    if not os.path.exists(INSTRUMENTS_FILE):
        print(f"❌ {INSTRUMENTS_FILE} not found. Run build_instruments.py first.")
        sys.exit(1)

    df_inst = pd.read_csv(INSTRUMENTS_FILE)
    df_inst = df_inst.dropna(subset=["symbol", "instrument_key"])
    
    # 2. Setup output
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    total = len(df_inst)
    print("=" * 60)
    print("  COLLECTING DAILY DATA FOR BACKTESTING")
    print(f"  Stocks to fetch: {total}")
    print(f"  Period: ~1 year ({(date.today() - timedelta(days=DAYS_BACK)).strftime('%Y-%m-%d')} to {date.today().strftime('%Y-%m-%d')})")
    print(f"  Output: {os.path.abspath(OUTPUT_DIR)}/")
    print("=" * 60)

    today_str = date.today().strftime("%Y-%m-%d")
    from_str  = (date.today() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")

    success = 0
    failed  = 0
    skipped = 0

    for i, row in df_inst.iterrows():
        symbol = row["symbol"]
        instrument_key = row["instrument_key"]
        csv_path = os.path.join(OUTPUT_DIR, f"{symbol}.csv")

        # Skip if already downloaded with enough data (minimal check: > 200 rows)
        if os.path.exists(csv_path):
            try:
                existing = pd.read_csv(csv_path, index_col=0)
                if len(existing) >= 200:
                    skipped += 1
                    if (i + 1) % 50 == 0:
                        print(f"   [{i+1}/{total}] ... (skipping existing)")
                    continue
            except:
                pass

        try:
            # Fetch daily data
            df = _fetch_historical(instrument_key, "day", from_str, today_str)

            if df.empty or len(df) < 50:
                failed += 1
                print(f"   [{i+1}/{total}] {symbol}: FAIL - insufficient data ({len(df)} rows)")
                continue

            df.to_csv(csv_path)
            success += 1
            if (i + 1) % 10 == 0 or success == 1:
                print(f"   [{i+1}/{total}] {symbol}: OK - {len(df)} daily candles")

        except Exception as e:
            failed += 1
            print(f"   [{i+1}/{total}] {symbol}: FAIL - {e}")

        # Small delay to respect API limits (Upstox is usually okay with 0.2s)
        time.sleep(0.2)

    print(f"\n{'=' * 60}")
    print(f"  COLLECTION COMPLETE")
    print(f"  Downloaded: {success}")
    print(f"  Already had: {skipped}")
    print(f"  Failed: {failed}")
    print(f"  Data: {os.path.abspath(OUTPUT_DIR)}/")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    collect()

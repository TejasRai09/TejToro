
import os
import time
import pandas as pd
from datetime import date, timedelta
from data_fetcher import _fetch_historical

def collect_data():
    if not os.path.exists("instruments.csv"):
        print("instruments.csv not found.")
        return

    # Create folder for storage
    DATA_DIR = "backtest_30d"
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    instruments = pd.read_csv("instruments.csv")
    total = len(instruments)
    
    # Range: 30 days ago to yesterday
    to_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    from_date = (date.today() - timedelta(days=31)).strftime("%Y-%m-%d")

    print(f"Starting download for {total} stocks ({from_date} to {to_date})...")
    print("This will take some time due to Upstox rate limits...")

    success_count = 0
    for i, row in instruments.iterrows():
        symbol = row["symbol"]
        ikey = row["instrument_key"]
        file_path = os.path.join(DATA_DIR, f"{symbol}.csv")

        if os.path.exists(file_path):
            success_count += 1
            continue

        if (i+1) % 10 == 0:
            print(f"   Progress: {i+1}/{total} stocks processed...")

        try:
            # Fetch 1-minute data for the whole month
            df = _fetch_historical(ikey, "1minute", from_date, to_date)
            if not df.empty:
                df.to_csv(file_path)
                success_count += 1
            
            # Tiny sleep to be polite to the API
            time.sleep(0.1) 
        except Exception as e:
            print(f"   [ERR] Failed {symbol}: {e}")
            time.sleep(1)

    print(f"\n[DONE] Successfully collected data for {success_count}/{total} stocks.")
    print(f"Data saved in '{DATA_DIR}/' folder.")

if __name__ == "__main__":
    collect_data()

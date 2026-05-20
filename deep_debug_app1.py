
import pandas as pd
from zoneinfo import ZoneInfo
from datetime import time

IST = ZoneInfo("Asia/Kolkata")

def deep_debug():
    file_path = "backtest_30d/COFORGE.csv"
    df = pd.read_csv(file_path)
    if 'timestamp' in df.columns:
        df = df.rename(columns={'timestamp': 'datetime'})
    
    # Matching the exact logic in the backtester
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True).dt.tz_convert(IST)
    df.set_index('datetime', inplace=True)
    
    df_10m = df.resample("10min", closed="left", label="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last"
    }).dropna()

    print(f"First 10 candles of COFORGE (resampled):")
    print(df_10m.head(10))
    
    print("\nChecking for Open Drive (Open == Low) today or recently:")
    for ts, row in df_10m.iterrows():
        if ts.time() == time(9, 15):
            diff = abs(row['open'] - row['low'])
            tol = row['open'] * 0.0005
            print(f"  {ts} | O: {row['open']} | L: {row['low']} | Diff: {diff:.4f} | Tol: {tol:.4f} | OD: {diff <= tol}")

if __name__ == "__main__":
    deep_debug()

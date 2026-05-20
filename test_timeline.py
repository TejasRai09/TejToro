
import pandas as pd
from datetime import datetime, time
from zoneinfo import ZoneInfo
import os

from data_fetcher import get_10min_candles
from indicators import prepare_indicators

IST = ZoneInfo("Asia/Kolkata")
TARGET_DATE = "2026-04-15"

def test_time_window(symbol, times):
    print("=" * 60)
    print(f"  TIMELINE TEST FOR {symbol} ON {TARGET_DATE}")
    print("=" * 60)

    instruments = pd.read_csv("instruments.csv")
    row = instruments[instruments["symbol"] == symbol]
    instrument_key = row.iloc[0]["instrument_key"]

    df_raw = get_10min_candles(instrument_key, days_back=7)

    for t in times:
        print(f"\nChecking at {t}...")
        target_dt = pd.Timestamp(f"{TARGET_DATE} {t}").tz_localize(IST)
        df_sliced = df_raw[df_raw.index <= target_dt].copy()
        
        today_df, pivots = prepare_indicators(df_sliced)
        if today_df.empty:
            print("  No data.")
            continue

        live_candle = today_df.iloc[-1]
        first_candle = today_df.iloc[0]
        
        ltp = live_candle["close"]
        vwap = live_candle["vwap"]
        rsi = live_candle["rsi"]
        wma = live_candle["wma_rsi"]
        
        first_open = first_candle["open"]
        first_low = first_candle["low"]
        is_od = abs(first_open - first_low) <= (first_open * 0.0005)
        
        print(f"  LTP: {ltp:.2f} | VWAP: {vwap:.2f} | Above: {ltp > vwap}")
        print(f"  Open Drive: {is_od} (O:{first_open}, L:{first_low})")
        print(f"  Momentum: {rsi:.2f} >= {wma:.2f} ({rsi >= wma})")

if __name__ == "__main__":
    test_time_window("GROWW", ["09:20:00", "09:25:00", "09:30:00"])


import pandas as pd
from datetime import datetime, time
from zoneinfo import ZoneInfo
import os

from data_fetcher import get_10min_candles
from indicators import prepare_indicators

IST = ZoneInfo("Asia/Kolkata")
TARGET_DATE = "2026-04-24"
TARGET_TIME = "09:30:00"

def test_stocks(symbols):
    print("=" * 60)
    print(f"  TESTING SPECIFIC STOCKS FOR {TARGET_DATE} AT {TARGET_TIME}")
    print("=" * 60)

    instruments = pd.read_csv("instruments.csv")
    
    results = []

    for symbol in symbols:
        row = instruments[instruments["symbol"] == symbol]
        if row.empty:
            print(f"Symbol {symbol} not found in instruments.csv")
            continue
        
        instrument_key = row.iloc[0]["instrument_key"]
        print(f"\nAnalyzing {symbol}...")

        try:
            df_raw = get_10min_candles(instrument_key, days_back=7)
            if df_raw.empty:
                print(f"  No data for {symbol}")
                continue

            target_dt = pd.Timestamp(f"{TARGET_DATE} {TARGET_TIME}").tz_localize(IST)
            df_sliced = df_raw[df_raw.index <= target_dt].copy()

            if df_sliced.empty:
                print(f"  No data up to {TARGET_TIME} for {symbol}")
                continue

            today_df, pivots = prepare_indicators(df_sliced)
            if today_df.empty:
                print(f"  Indicator prep failed for {symbol} (possibly not enough data today)")
                continue

            live_candle = today_df.iloc[-1]
            first_candle = today_df.iloc[0]

            print(f"  Data time: {live_candle.name}")
            
            # Rule Checks
            ltp = live_candle["close"]
            vwap = live_candle["vwap"]
            rsi = live_candle["rsi"]
            wma_rsi = live_candle["wma_rsi"]
            PP = pivots["PP"]
            R1 = pivots["R1"]

            first_open = first_candle["open"]
            first_low = first_candle["low"]
            tolerance = first_open * 0.0005
            is_open_drive = abs(first_open - first_low) <= tolerance

            print(f"  [Rule 4] Open={first_open}, Low={first_low}, Match={is_open_drive}")
            print(f"  [Rule 5] Price={ltp:.2f}, VWAP={vwap:.2f}, Above={ltp > vwap}")
            print(f"  [Rule 6] Pivot={PP:.2f}, Above={ltp > PP}")
            print(f"  [Rule 7] RSI={rsi:.2f}, WMA={wma_rsi:.2f}, Momentum={rsi >= wma_rsi}")
            
            risk = ltp - vwap
            reward = R1 - ltp
            rr = reward / risk if risk > 0 else 0
            print(f"  [Rule 8] R:R={rr:.2f}, Valid={rr >= 1.5}")
            
            if is_open_drive and ltp > vwap and ltp > PP and rsi >= wma_rsi and rr >= 1.5:
                print(f"  ✅ {symbol} PASSED ALL RULES")
            else:
                print(f"  ❌ {symbol} FAILED")

        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    test_stocks(["GROWW", "PICCADIL"])

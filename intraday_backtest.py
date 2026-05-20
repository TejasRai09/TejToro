
import pandas as pd
from datetime import datetime, time
from zoneinfo import ZoneInfo
import os

from data_fetcher import get_10min_candles
from indicators import prepare_indicators
from scanner import evaluate_stock
from config import MIN_MARKET_CAP_CR

IST = ZoneInfo("Asia/Kolkata")
TARGET_DATE = "2026-04-24"
TARGET_TIME = "09:30:00"

def run_intraday_backtest():
    print("=" * 60)
    print(f"  INTRADAY BACKTEST FOR {TARGET_DATE} AT {TARGET_TIME}")
    print("=" * 60)

    # Load instruments
    if not os.path.exists("instruments.csv"):
        print("instruments.csv not found.")
        return
    
    instruments = pd.read_csv("instruments.csv")
    total = len(instruments)
    print(f"Scanning {total} instruments...")

    results = []

    for i, row in instruments.iterrows():
        symbol = row["symbol"]
        instrument_key = row["instrument_key"]
        mcap = row.get("market_cap_cr", 0.0)

        if (i+1) % 50 == 0:
            print(f"   Processed {i+1}/{total}...")

        try:
            # Fetch 10-min candles (includes history)
            df_raw = get_10min_candles(instrument_key, days_back=5)
            if df_raw.empty:
                continue

            # Slice data to end at the target time on the target date
            target_dt = pd.Timestamp(f"{TARGET_DATE} {TARGET_TIME}").tz_localize(IST)
            df_sliced = df_raw[df_raw.index <= target_dt].copy()

            if df_sliced.empty:
                continue

            # We need to run the logic on this slice
            # To simulate evaluate_stock, we'll manually run the rules on df_sliced
            
            # Prepare indicators on the sliced data
            today_df, pivots = prepare_indicators(df_sliced)

            if today_df.empty or not pivots or pivots.get("R1") is None:
                continue

            # Latest candle in our slice
            live_candle = today_df.iloc[-1]
            first_candle = today_df.iloc[0]

            # Only check if the last candle is actually from today (April 24)
            if live_candle.name.date() != datetime.strptime(TARGET_DATE, "%Y-%m-%d").date():
                continue

            # Strategy Rules (simplified from scanner.py)
            ltp = live_candle["close"]
            vwap = live_candle["vwap"]
            rsi = live_candle["rsi"]
            wma_rsi = live_candle["wma_rsi"]
            PP = pivots["PP"]
            R1 = pivots["R1"]

            # Rule 4: Open Drive
            first_open = first_candle["open"]
            first_low = first_candle["low"]
            tolerance = first_open * 0.0005
            is_open_drive = abs(first_open - first_low) <= tolerance

            # Rule 5, 6, 7
            is_above_vwap = ltp > vwap
            is_above_pp = ltp > PP
            has_momentum = rsi >= wma_rsi

            # Risk:Reward
            risk = ltp - vwap
            reward = R1 - ltp
            rr_ratio = reward / risk if risk > 0 else 0
            is_good_rr = rr_ratio >= 1.5

            if is_open_drive and is_above_vwap and is_above_pp and has_momentum and is_good_rr:
                results.append({
                    "Symbol": symbol,
                    "LTP": round(ltp, 2),
                    "VWAP": round(vwap, 2),
                    "RSI": round(rsi, 2),
                    "WMA": round(wma_rsi, 2),
                    "PP": round(PP, 2),
                    "R1": round(R1, 2),
                    "RR": round(rr_ratio, 2)
                })

        except Exception as e:
            # print(f"Error for {symbol}: {e}")
            continue

    print("\n" + "=" * 60)
    if not results:
        print(f"No signals found at {TARGET_TIME} on {TARGET_DATE}.")
    else:
        results_df = pd.DataFrame(results)
        print(f"Found {len(results_df)} signals:")
        print(results_df.to_string(index=False))
    print("=" * 60)

if __name__ == "__main__":
    run_intraday_backtest()

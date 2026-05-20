
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import os

from data_fetcher import get_10min_candles
from indicators import prepare_indicators
from config import OPEN_LOW_TOLERANCE, MIN_RR_RATIO, MIN_R1_DISTANCE_PCT

IST = ZoneInfo("Asia/Kolkata")
TARGET_DATE = "2026-04-27"
TARGET_TIME = "09:25:00"

def simulate_today():
    print("=" * 60)
    print(f"  SIMULATING SCAN FOR {TARGET_DATE} AT {TARGET_TIME}")
    print("=" * 60)

    if not os.path.exists("instruments.csv"):
        print("instruments.csv not found.")
        return
    
    instruments = pd.read_csv("instruments.csv")
    total = len(instruments)
    print(f"Scanning {total} instruments...")

    results = []

    # Target timestamp for slicing
    target_dt = pd.Timestamp(f"{TARGET_DATE} {TARGET_TIME}").tz_localize(IST)

    for i, row in instruments.iterrows():
        symbol = row["symbol"]
        instrument_key = row["instrument_key"]

        if (i+1) % 50 == 0:
            print(f"   Processed {i+1}/{total}...")

        try:
            # Fetch data (includes today's live data)
            df_raw = get_10min_candles(instrument_key, days_back=3)
            if df_raw.empty: continue

            # Slice to 9:25 AM today
            df_sliced = df_raw[df_raw.index <= target_dt].copy()
            if df_sliced.empty: continue

            # Check if we actually have today's data in the slice
            today_data = df_sliced[df_sliced.index.date == datetime.strptime(TARGET_DATE, "%Y-%m-%d").date()]
            if today_data.empty: continue

            # Prepare indicators
            today_df, pivots = prepare_indicators(df_sliced)
            if today_df.empty or not pivots or pivots.get("R1") is None: continue

            # Get candles
            live_candle = today_df.iloc[-1]
            first_candle = today_df.iloc[0]
            
            # Rule 4: Open Drive (Strict 09:15 check)
            if first_candle.name.time() != datetime.strptime("09:15", "%H:%M").time():
                continue
                
            ltp = live_candle["close"]
            vwap = live_candle["vwap"]
            rsi = live_candle["rsi"]
            wma = live_candle["wma_rsi"]
            PP = pivots["PP"]
            R1 = pivots["R1"]

            first_open = first_candle["open"]
            first_low = first_candle["low"]
            is_od = abs(first_open - first_low) <= (first_open * OPEN_LOW_TOLERANCE)

            if is_od and ltp > vwap and ltp > PP and rsi >= wma:
                # Risk Reward
                risk = ltp - vwap
                reward = R1 - ltp
                if risk > 0:
                    rr = reward / risk
                    r1_dist = ((R1 - ltp) / ltp) * 100
                    
                    if rr >= MIN_RR_RATIO and r1_dist >= MIN_R1_DISTANCE_PCT:
                        results.append({
                            "Symbol": symbol,
                            "LTP": round(ltp, 2),
                            "VWAP": round(vwap, 2),
                            "RSI": round(rsi, 1),
                            "WMA": round(wma, 1),
                            "R1": round(R1, 2),
                            "RR": round(rr, 2),
                            "Dist%": round(r1_dist, 2)
                        })

        except Exception:
            continue

    print("\n" + "=" * 60)
    if not results:
        print(f"No signals would have fired at {TARGET_TIME} today.")
    else:
        results_df = pd.DataFrame(results)
        print(f"Found {len(results_df)} signals:")
        print(results_df.to_string(index=False))
    print("=" * 60)

if __name__ == "__main__":
    simulate_today()


import pandas as pd
import glob
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo
from indicators import prepare_indicators
from scanner2 import evaluate_stock_v2

IST = ZoneInfo("Asia/Kolkata")

def run_backtest_v2():
    print("=" * 60)
    print("  BACKTEST: CONVERGENCE STRATEGY (V2)")
    print("  Period: April 13 - April 17, 2026")
    print("  Resolution: 10-min scan sweeping every 10 minutes")
    print("=" * 60)

    data_files = glob.glob("nifty500_data/*.csv")
    if not data_files:
        print("No data found in nifty500_data folder.")
        return

    # Load instruments to get market caps
    instruments = pd.read_csv("instruments.csv")
    mcap_map = dict(zip(instruments['symbol'], instruments['market_cap_cr']))

    all_signals = []

    for file_path in data_files:
        symbol = os.path.basename(file_path).replace(".csv", "")
        mcap = mcap_map.get(symbol, 0)
        
        # Load 1-min data
        df_1m = pd.read_csv(file_path)
        df_1m['datetime'] = pd.to_datetime(df_1m['datetime'])
        df_1m.set_index('datetime', inplace=True)
        
        # Resample to 10-min (matching live logic)
        df_10m = df_1m.resample("10min", closed="left", label="left").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()

        # Iterate through days
        dates = df_10m.index.normalize().unique()
        for d in dates:
            day_data = df_10m[df_10m.index.normalize() == d]
            if len(day_data) < 5: continue
            
            # Simulate "Sweeping" the market at different times
            # We start after the first few candles for indicator warmup
            for i in range(3, len(day_data)):
                current_time = day_data.index[i]
                
                # We only scan between 9:15 and 15:15
                if not (time(9, 15) <= current_time.time() <= time(15, 15)):
                    continue

                # Prepare indicators for the data seen UP TO THIS POINT
                df_slice = df_10m[df_10m.index <= current_time]
                
                # evaluate_stock_v2 logic
                # We'll use a modified version of evaluate_stock_v2 here for efficiency
                try:
                    today_df, pivots = prepare_indicators(df_slice)
                    if today_df.empty or not pivots or pivots.get("PP") is None: continue
                    
                    live_candle = today_df.iloc[-1]
                    prev_1 = today_df.iloc[-2] if len(today_df) >= 2 else None
                    prev_2 = today_df.iloc[-3] if len(today_df) >= 3 else None
                    
                    close = live_candle["close"]
                    vwap  = live_candle["vwap"]
                    st    = live_candle["st"]
                    PP    = pivots["PP"]
                    R1    = pivots["R1"]

                    # Pre-filters
                    if abs(st - vwap) > (close * 0.01): continue
                    if abs(vwap - PP) > (close * 0.01): continue
                    if abs(PP - st) > (close * 0.01): continue
                    if abs(close - PP) > (close * 0.002): continue
                    
                    # Main Scan
                    if mcap < 1000: continue
                    if close < st: continue
                    if close < PP: continue
                    if close < vwap: continue
                    if prev_1 is not None and prev_1["close"] < prev_1["vwap"]: continue
                    if prev_2 is not None and prev_2["close"] < prev_2["vwap"]: continue
                    
                    # If we reach here, signal found!
                    all_signals.append({
                        "Symbol": symbol,
                        "Time": current_time.strftime("%Y-%m-%d %H:%M"),
                        "Price": round(close, 2),
                        "VWAP": round(vwap, 2),
                        "ST": round(st, 2),
                        "PP": round(PP, 2),
                        "Target(R1)": round(R1, 2)
                    })
                    # Once a signal is found for a stock on a day, we skip the rest of the day
                    break 

                except Exception:
                    continue

    print("\n" + "=" * 60)
    if not all_signals:
        print("No signals found for this strategy in the backtest period.")
    else:
        results = pd.DataFrame(all_signals)
        print(f"Found {len(results)} Potential Signals:")
        print(results.to_string(index=False))
    print("=" * 60)

if __name__ == "__main__":
    run_backtest_v2()

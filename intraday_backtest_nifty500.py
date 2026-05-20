
import os
import pandas as pd
import numpy as np
from datetime import datetime, time
from zoneinfo import ZoneInfo
from indicators import prepare_indicators
from config import (
    OPEN_LOW_TOLERANCE, MIN_RR_RATIO, MIN_R1_DISTANCE_PCT,
    MAX_RISK_PER_TRADE, MAX_TRADE_VALUE, T1_EXIT_PCT
)

IST = ZoneInfo("Asia/Kolkata")
DATA_DIR = "nifty500_data"

def run_nifty500_backtest():
    print("=" * 60)
    print("  INTRADAY BACKTEST: NIFTY 500 (1-MIN DATA)")
    print("  Period: April 13 - April 17, 2026")
    print("=" * 60)

    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".csv")]
    if not files:
        print(f"No CSV files found in {DATA_DIR}")
        return

    all_trades = []

    for f_idx, filename in enumerate(files):
        symbol = filename.replace(".csv", "")
        filepath = os.path.join(DATA_DIR, filename)

        try:
            # Load 1-min data
            df_1m = pd.read_csv(filepath)
            df_1m['datetime'] = pd.to_datetime(df_1m['datetime'])
            df_1m.set_index('datetime', inplace=True)
            df_1m.sort_index(inplace=True)

            # Resample to 10-min candles (Matching live scanner)
            df_10m = df_1m.resample("10min", closed="left", label="left").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            }).dropna()

            # Filter to trading hours
            df_10m = df_10m.between_time("09:15", "15:20")

            # Calculate indicators once for the whole dataset
            # (prepare_indicators internally slices today/yesterday for pivots)
            # Actually, let's call it per day to ensure correct pivot logic
            days = df_10m.index.normalize().unique()
            
            for i in range(1, len(days)):
                today = days[i]
                
                # Use data up to today for indicators
                df_subset = df_10m[df_10m.index.normalize() <= today].copy()
                today_indicators, pivots = prepare_indicators(df_subset)
                
                if today_indicators.empty or not pivots or pivots.get("R1") is None:
                    continue

                # Scan from 9:25 AM to 11:00 AM
                # The first candle is 09:15. End of first candle is 09:25.
                # So we can start scanning at 09:25.
                possible_times = ["09:15:00", "09:25:00", "09:35:00", "09:45:00", "09:55:00", "10:05:00"]
                
                for st in possible_times:
                    scan_dt_str = today.strftime("%Y-%m-%d") + " " + st
                    # Match timezone of the index
                    scan_dt = pd.Timestamp(scan_dt_str).tz_localize(IST)
                    
                    if scan_dt not in today_indicators.index:
                        continue
                    
                    row = today_indicators.loc[scan_dt]
                    # The 9:15 candle is the first candle of the day
                    day_start = pd.Timestamp(today.strftime("%Y-%m-%d") + " 09:15:00").tz_localize(IST)
                    if day_start not in today_indicators.index: continue
                    first_candle = today_indicators.loc[day_start]
                    
                    # --- Strategy Rules ---
                    ltp = row["close"]
                    vwap = row["vwap"]
                    rsi = row["rsi"]
                    wma = row["wma_rsi"]
                    PP = pivots["PP"]
                    R1 = pivots["R1"]
                    R2 = pivots["R2"]

                    # Open Drive Check
                    f_open = first_candle["open"]
                    f_low = first_candle["low"]
                    is_od = abs(f_open - f_low) <= (f_open * OPEN_LOW_TOLERANCE)
                    
                    if not is_od: continue
                    if ltp <= vwap: continue
                    if ltp <= PP: continue
                    if rsi < wma: continue
                    
                    # Risk Reward
                    risk = ltp - vwap
                    reward = R1 - ltp
                    if risk <= 0: continue
                    rr = reward / risk
                    if rr < MIN_RR_RATIO: continue
                    
                    # R1 Distance
                    r1_dist = ((R1 - ltp) / ltp) * 100
                    if r1_dist < MIN_R1_DISTANCE_PCT: continue
                    
                    # --- Signal Found! ---
                    shares = int(MAX_RISK_PER_TRADE / risk)
                    if shares * ltp > MAX_TRADE_VALUE:
                        shares = int(MAX_TRADE_VALUE / ltp)
                    if shares <= 0: continue

                    # Exit Simulation (using 1-min data)
                    # We enter at the end of the candle, so we look at 1-min data AFTER st
                    # For a 9:25 signal, we enter at 9:25:00.
                    df_exit = df_1m[df_1m.index > scan_dt]
                    df_exit = df_exit[df_exit.index.normalize() == today]
                    
                    pnl = 0.0
                    exit_type = "TIME_EXIT"
                    exit_price = 0.0
                    t1_shares = int(shares * T1_EXIT_PCT)
                    t2_shares = shares - t1_shares
                    
                    stop_hit = False
                    t1_hit = False
                    t2_hit = False
                    
                    for _, minute in df_exit.iterrows():
                        if minute["low"] <= vwap:
                            stop_hit = True
                            exit_price = vwap
                            exit_type = "STOPPED"
                            break
                        if minute["high"] >= R2 and t1_hit:
                            t2_hit = True
                            exit_price = R2
                            exit_type = "T2_HIT"
                            break
                        if minute["high"] >= R1 and not t1_hit:
                            t1_hit = True
                        
                    if stop_hit:
                        pnl = shares * (vwap - ltp)
                    elif t2_hit:
                        pnl = (t1_shares * (R1 - ltp)) + (t2_shares * (R2 - ltp))
                    elif t1_hit:
                        cl_pr = df_exit.iloc[-1]["close"]
                        pnl = (t1_shares * (R1 - ltp)) + (t2_shares * (cl_pr - ltp))
                        exit_type = "T1_HIT"
                        exit_price = R1
                    else:
                        cl_pr = df_exit.iloc[-1]["close"]
                        pnl = shares * (cl_pr - ltp)
                        exit_price = cl_pr

                    all_trades.append({
                        "Date": today.strftime("%Y-%m-%d"),
                        "Symbol": symbol,
                        "Time": st,
                        "Entry": round(ltp, 2),
                        "Exit": exit_type,
                        "ExitPrice": round(exit_price, 2),
                        "PnL": round(pnl, 2)
                    })
                    break

        except Exception:
            continue

    print("\n" + "=" * 60)
    if not all_trades:
        print("No signals found in the available range.")
    else:
        trades_df = pd.DataFrame(all_trades)
        print(f"Found {len(trades_df)} signals:")
        print(trades_df.to_string(index=False))
        print(f"\nTotal P&L for the week: Rs.{trades_df['PnL'].sum():,.2f}")
    print("=" * 60)

if __name__ == "__main__":
    run_nifty500_backtest()

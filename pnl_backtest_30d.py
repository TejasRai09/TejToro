
import pandas as pd
import glob
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo
import pandas as pd
from indicators import prepare_indicators

IST = ZoneInfo("Asia/Kolkata")
CAPITAL = 200000
RISK_PER_TRADE = 2000

def run_30d_backtest():
    print("=" * 60)
    print("  30-DAY MONTHLY P&L REPORT: CONVERGENCE STRATEGY")
    print(f"  Capital: Rs {CAPITAL:,} | Risk/Trade: Rs {RISK_PER_TRADE:,}")
    print("=" * 60)

    data_files = glob.glob("backtest_30d/*.csv")
    instruments = pd.read_csv("instruments.csv")
    mcap_map = dict(zip(instruments['symbol'], instruments['market_cap_cr']))

    trades = []

    total_files = len(data_files)
    for idx, file_path in enumerate(data_files):
        symbol = os.path.basename(file_path).replace(".csv", "")
        mcap = mcap_map.get(symbol, 0)
        
        if (idx + 1) % 50 == 0:
            print(f"  Progress: {idx+1}/{total_files} stocks analyzed...")

        try:
            df_1m = pd.read_csv(file_path)
            # Upstox downloads use 'timestamp' column
            if 'timestamp' in df_1m.columns:
                df_1m = df_1m.rename(columns={'timestamp': 'datetime'})
            
            df_1m['datetime'] = pd.to_datetime(df_1m['datetime'])
            df_1m.set_index('datetime', inplace=True)
            
            # Resample to 10-min
            df_10m = df_1m.resample("10min", closed="left", label="left").agg({
                "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
            }).dropna()

            dates = df_10m.index.normalize().unique()
            for d in dates:
                day_data_10m = df_10m[df_10m.index.normalize() == d]
                day_data_1m  = df_1m[df_1m.index.normalize() == d]
                if len(day_data_10m) < 10: continue
                
                signal_found = False
                for i in range(5, len(day_data_10m)):
                    current_time = day_data_10m.index[i]
                    if not (time(9, 30) <= current_time.time() <= time(14, 30)): continue

                    df_slice = df_10m[df_10m.index <= current_time]
                    
                    try:
                        today_df, pivots = prepare_indicators(df_slice)
                        if today_df.empty: continue
                        
                        row = today_df.iloc[-1]
                        prev_1 = today_df.iloc[-2]
                        prev_2 = today_df.iloc[-3]
                        
                        close, vwap, st, pp = row['close'], row['vwap'], row['st'], pivots['PP']
                        r1, r2 = pivots['R1'], pivots['R2']

                        # Convergence Rules
                        if abs(st - vwap) > (close * 0.01): continue
                        if abs(vwap - pp) > (close * 0.01): continue
                        if abs(pp - st) > (close * 0.01): continue
                        if abs(close - pp) > (close * 0.002): continue
                        
                        # Trend Rules
                        if mcap < 1000: continue
                        if close < st or close < pp: continue
                        if close < vwap or prev_1['close'] < prev_1['vwap'] or prev_2['close'] < prev_2['vwap']: continue
                        
                        # --- SIGNAL FOUND ---
                        entry_price = close
                        stop_loss = min(vwap, st) - (close * 0.001) 
                        risk_per_share = entry_price - stop_loss
                        
                        if risk_per_share <= 0: continue
                        
                        shares = int(RISK_PER_TRADE / risk_per_share)
                        if shares <= 0: continue
                        
                        # Track trade using 1-minute data
                        future_data = day_data_1m[day_data_1m.index > current_time]
                        exit_price = entry_price
                        exit_reason = "3:15 PM"
                        
                        for ts, min_row in future_data.iterrows():
                            if ts.time() >= time(15, 15): break
                            if min_row['low'] <= stop_loss:
                                exit_price = stop_loss
                                exit_reason = "STOP"
                                break
                            if min_row['high'] >= r1:
                                exit_price = r1
                                exit_reason = "TARGET 1"
                                break
                        
                        trades.append({
                            "Date": d.strftime("%Y-%m-%d"),
                            "Symbol": symbol,
                            "Entry": round(entry_price, 2),
                            "Exit": round(exit_price, 2),
                            "PnL": round((exit_price - entry_price) * shares, 2),
                            "Reason": exit_reason
                        })
                        signal_found = True
                        break 
                    except Exception: continue
                if signal_found: continue
        except Exception: continue

    print("\n" + "=" * 60)
    if not trades:
        print("No trades triggered in the 30-day period.")
    else:
        df_results = pd.DataFrame(trades)
        total_pnl = df_results['PnL'].sum()
        win_rate = (len(df_results[df_results['PnL'] > 0]) / len(df_results)) * 100
        
        print(f"Total Trades: {len(df_results)}")
        print(f"Win Rate: {win_rate:.1f}%")
        print(f"Net Profit: Rs {total_pnl:,.2f}")
        print(f"Estimated Monthly ROI: {(total_pnl/CAPITAL)*100:.2f}%")
        print("-" * 60)
        print("Top 10 Profitable Trades:")
        print(df_results.sort_values('PnL', ascending=False).head(10).to_string(index=False))
    print("=" * 60)

if __name__ == "__main__":
    run_30d_backtest()

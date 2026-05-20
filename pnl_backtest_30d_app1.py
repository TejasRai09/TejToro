
import pandas as pd
import glob
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo
from indicators import calculate_vwap, calculate_rsi, calculate_wma, calculate_supertrend
from config import OPEN_LOW_TOLERANCE, MIN_RR_RATIO, MIN_R1_DISTANCE_PCT

IST = ZoneInfo("Asia/Kolkata")
CAPITAL = 200000
RISK_PER_TRADE = 2000

def run_30d_backtest_app1():
    print("=" * 60)
    print("  30-DAY MONTHLY P&L REPORT: OPEN DRIVE (APP 1)")
    print(f"  Capital: Rs {CAPITAL:,} | Risk/Trade: Rs {RISK_PER_TRADE:,}")
    print("=" * 60)

    data_files = glob.glob("backtest_30d/*.csv")
    total_files = len(data_files)
    trades = []

    for idx, file_path in enumerate(data_files):
        symbol = os.path.basename(file_path).replace(".csv", "")
        
        if (idx + 1) % 50 == 0:
            print(f"  Processed {idx+1}/{total_files} stocks...")

        try:
            df_1m = pd.read_csv(file_path)
            if 'timestamp' in df_1m.columns:
                df_1m = df_1m.rename(columns={'timestamp': 'datetime'})
            df_1m['datetime'] = pd.to_datetime(df_1m['datetime'], utc=True).dt.tz_convert(IST)
            df_1m.set_index('datetime', inplace=True)
            
            # Resample to 10-min starting from 09:15 (using 5min offset to align 9:15, 9:25...)
            df_10m = df_1m.resample("10min", closed="left", label="left", offset="5min").agg({
                "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
            }).dropna()

            # Indicators once per stock
            df_10m['vwap'] = calculate_vwap(df_10m)
            df_10m['rsi']  = calculate_rsi(df_10m['close'])
            df_10m['wma_rsi'] = calculate_wma(df_10m['rsi'])
            
            dates = df_10m.index.normalize().unique()
            for d in dates:
                # Pivots
                prev_df = df_10m[df_10m.index.normalize() < d]
                if prev_df.empty: continue
                last_day = prev_df.index.normalize().max()
                prev_day_df = prev_df[prev_df.index.normalize() == last_day]
                p_high, p_low, p_close = prev_day_df['high'].max(), prev_day_df['low'].min(), prev_day_df['close'].iloc[-1]
                pp = (p_high + p_low + p_close) / 3
                r1 = (2 * pp) - p_low
                
                day_data_10m = df_10m[df_10m.index.normalize() == d]
                day_data_1m  = df_1m[df_1m.index.normalize() == d]
                if len(day_data_10m) < 2: continue

                # Rule 4: Open Drive (Must be the 09:15 candle)
                first_candle = day_data_10m.iloc[0]
                if first_candle.name.time() != time(9, 15): continue
                
                is_od = abs(first_candle['open'] - first_candle['low']) <= (first_candle['open'] * OPEN_LOW_TOLERANCE)
                if not is_od: continue

                # If Open Drive passed, scan from 9:25 onwards
                signal_found = False
                for i in range(1, len(day_data_10m)):
                    row = day_data_10m.iloc[i]
                    if not (time(9, 25) <= row.name.time() <= time(10, 30)): continue # Primary window
                    
                    close, vwap, rsi, wma = row['close'], row['vwap'], row['rsi'], row['wma_rsi']

                    # Rules 5-9
                    if close < vwap or close < pp: continue
                    if rsi < wma: continue
                    
                    risk = close - vwap
                    reward = r1 - close
                    if risk <= 0 or (reward / risk) < MIN_RR_RATIO: continue
                    
                    # --- SIGNAL ---
                    entry_price = close
                    sl = vwap - (close * 0.0005)
                    shares = int(RISK_PER_TRADE / (entry_price - sl)) if entry_price > sl else 0
                    if shares <= 0: continue
                    
                    future = day_data_1m[day_data_1m.index > row.name]
                    exit_p, reason = entry_price, "3:15 PM"
                    for ts, m_row in future.iterrows():
                        if ts.time() >= time(15, 15): break
                        if m_row['low'] <= sl:
                            exit_p, reason = sl, "STOP"
                            break
                        if m_row['high'] >= r1:
                            exit_p, reason = r1, "TARGET 1"
                            break
                    
                    trades.append({"Date": d.strftime("%Y-%m-%d"), "Symbol": symbol, "PnL": (exit_p - entry_price) * shares, "Reason": reason})
                    signal_found = True
                    break
                if signal_found: continue
        except Exception: continue

    print("\n" + "=" * 60)
    if not trades:
        print("No trades found for App 1 strategy.")
    else:
        df = pd.DataFrame(trades)
        pnl = df['PnL'].sum()
        win_rate = (len(df[df['PnL']>0])/len(df)*100)
        print(f"Total Trades: {len(df)} | Win Rate: {win_rate:.1f}%")
        print(f"Net Profit: Rs {pnl:,.2f} | ROI: {(pnl/CAPITAL*100):.2f}%")
        print("-" * 60)
        print(df.sort_values('PnL', ascending=False).head(10).to_string(index=False))
    print("=" * 60)

if __name__ == "__main__":
    run_30d_backtest_app1()

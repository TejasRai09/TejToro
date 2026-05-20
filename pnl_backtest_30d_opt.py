
import pandas as pd
import glob
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo
from indicators import prepare_indicators

IST = ZoneInfo("Asia/Kolkata")
CAPITAL = 200000
RISK_PER_TRADE = 2000

def run_30d_backtest_optimized():
    print("=" * 60)
    print("  OPTIMIZED 30-DAY MONTHLY P&L REPORT")
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
        if mcap < 1000: continue
        
        if (idx + 1) % 50 == 0:
            print(f"  Processed {idx+1}/{total_files} stocks...")

        try:
            df_1m = pd.read_csv(file_path)
            if 'timestamp' in df_1m.columns:
                df_1m = df_1m.rename(columns={'timestamp': 'datetime'})
            df_1m['datetime'] = pd.to_datetime(df_1m['datetime'])
            df_1m.set_index('datetime', inplace=True)
            
            # Resample to 10-min
            df_10m = df_1m.resample("10min", closed="left", label="left").agg({
                "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
            }).dropna()

            # Calculate ALL indicators once for the entire 30 days
            # Note: prepare_indicators expects a slice, but we can call our sub-functions
            from indicators import calculate_vwap, calculate_rsi, calculate_wma, calculate_supertrend
            
            df_10m['vwap'] = calculate_vwap(df_10m)
            df_10m['rsi']  = calculate_rsi(df_10m['close'])
            df_10m['wma_rsi'] = calculate_wma(df_10m['rsi'])
            df_10m['st'] = calculate_supertrend(df_10m)
            
            dates = df_10m.index.normalize().unique()
            for d in dates:
                # Pivots need yesterday's data
                prev_df = df_10m[df_10m.index.normalize() < d]
                if prev_df.empty: continue
                
                # Get last trading day's data for pivots
                last_day = prev_df.index.normalize().max()
                prev_day_df = prev_df[prev_df.index.normalize() == last_day]
                
                p_high, p_low, p_close = prev_day_df['high'].max(), prev_day_df['low'].min(), prev_day_df['close'].iloc[-1]
                pp = (p_high + p_low + p_close) / 3
                r1 = (2 * pp) - p_low
                
                day_data_10m = df_10m[df_10m.index.normalize() == d]
                day_data_1m  = df_1m[df_1m.index.normalize() == d]
                
                signal_found = False
                for i in range(2, len(day_data_10m)):
                    row = day_data_10m.iloc[i]
                    if not (time(9, 30) <= row.name.time() <= time(14, 30)): continue
                    
                    prev_1 = day_data_10m.iloc[i-1]
                    prev_2 = day_data_10m.iloc[i-2]
                    
                    close, vwap, st = row['close'], row['vwap'], row['st']

                    # Rules
                    if abs(st - vwap) > (close * 0.01): continue
                    if abs(vwap - pp) > (close * 0.01): continue
                    if abs(pp - st) > (close * 0.01): continue
                    if abs(close - pp) > (close * 0.002): continue
                    if close < st or close < pp: continue
                    if close < vwap or prev_1['close'] < prev_1['vwap'] or prev_2['close'] < prev_2['vwap']: continue
                    
                    # --- SIGNAL ---
                    entry_price = close
                    sl = min(vwap, st) - (close * 0.001)
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
        print("No trades found.")
    else:
        df = pd.DataFrame(trades)
        pnl = df['PnL'].sum()
        print(f"Total Trades: {len(df)} | Win Rate: {(len(df[df['PnL']>0])/len(df)*100):.1f}%")
        print(f"Net Profit: Rs {pnl:,.2f} | ROI: {(pnl/CAPITAL*100):.2f}%")
        print("-" * 60)
        print(df.sort_values('PnL', ascending=False).head(10).to_string(index=False))
    print("=" * 60)

if __name__ == "__main__":
    run_30d_backtest_optimized()

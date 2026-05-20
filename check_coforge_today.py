
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from data_fetcher import get_10min_candles
from indicators import prepare_indicators
from config import OPEN_LOW_TOLERANCE

IST = ZoneInfo("Asia/Kolkata")
TARGET_DATE = "2026-04-27"

def check_stock_timeline(symbol, instrument_key):
    print(f"Timeline for {symbol} on {TARGET_DATE}:")
    df_raw = get_10min_candles(instrument_key, days_back=3)
    if df_raw.empty: return

    today_df, pivots = prepare_indicators(df_raw)
    if today_df.empty: return

    R1 = pivots['R1']
    PP = pivots['PP']
    
    first_candle = today_df.iloc[0]
    f_open = first_candle['open']
    f_low = first_candle['low']
    is_od = abs(f_open - f_low) <= (f_open * OPEN_LOW_TOLERANCE)
    print(f"  Open Drive: {is_od} (O:{f_open}, L:{f_low}, Time:{first_candle.name.time()})")
    print(f"  Pivots: PP={PP}, R1={R1}")

    for ts, row in today_df.iterrows():
        ltp = row['close']
        vwap = row['vwap']
        rsi = row['rsi']
        wma = row['wma_rsi']
        risk = ltp - vwap
        reward = R1 - ltp
        rr = reward/risk if risk > 0 else 0
        
        print(f"  {ts.time()} | LTP:{ltp:.2f} | VWAP:{vwap:.2f} | RSI:{rsi:.1f} | WMA:{wma:.1f} | RR:{rr:.2f} | Pass:{is_od and ltp>vwap and ltp>PP and rsi>=wma and rr>=1.5}")

if __name__ == "__main__":
    # From instruments.csv: COFORGE,NSE_EQ|INE591G01025
    check_stock_timeline("COFORGE", "NSE_EQ|INE591G01025")

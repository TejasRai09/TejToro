
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from data_fetcher import get_market_quotes, get_10min_candles
from scanner import prefilter_by_quotes, evaluate_stock
from indicators import prepare_indicators
from config import MIN_DAILY_CHANGE_PCT, MIN_STOCK_PRICE, MAX_STOCK_PRICE, MIN_RR_RATIO

IST = ZoneInfo("Asia/Kolkata")

def debug_live():
    print("=" * 60)
    print(f"  DIAGNOSING LIVE SCAN AT {datetime.now(IST).strftime('%H:%M:%S')}")
    print("=" * 60)

    instruments = pd.read_csv("instruments.csv")
    
    # Phase 1: Prefilter
    print(f"Checking {len(instruments)} stocks for daily movement (>= {MIN_DAILY_CHANGE_PCT}%)...")
    passed_prefilter = prefilter_by_quotes(instruments)
    print(f"   {len(passed_prefilter)} stocks passed the initial movement/price check.")

    if not passed_prefilter:
        print("No stocks are moving up today. Strategy cannot find long entries.")
        return

    # Look at the top 5 movers
    passed_prefilter = sorted(passed_prefilter, key=lambda x: x['pct_change'], reverse=True)
    top_5 = passed_prefilter[:5]
    
    print("\nAnalyzing Top 5 Movers:")
    for stock in top_5:
        sym = stock['symbol']
        print(f"\n[{sym}] (Up {stock['pct_change']}%):")
        
        df_raw = get_10min_candles(stock['instrument_key'], days_back=3)
        if df_raw.empty:
            print("  - No candle data available.")
            continue
            
        today_df, pivots = prepare_indicators(df_raw)
        if today_df.empty:
            print("  - Indicators failed (warmup issue).")
            continue
            
        first_candle = today_df.iloc[0]
        live_candle = today_df.iloc[-1]
        
        # Rule 4: Open Drive
        from config import OPEN_LOW_TOLERANCE
        f_open = first_candle['open']
        f_low = first_candle['low']
        is_od = abs(f_open - f_low) <= (f_open * OPEN_LOW_TOLERANCE)
        print(f"  - Rule 4 (Open Drive): {'PASS' if is_od else 'FAIL'} (O:{f_open}, L:{f_low})")
        
        # Rule 5, 6, 7
        ltp = live_candle['close']
        vwap = live_candle['vwap']
        rsi = live_candle['rsi']
        wma = live_candle['wma_rsi']
        PP = pivots['PP']
        R1 = pivots['R1']
        
        print(f"  - Rule 5 (Above VWAP): {'PASS' if ltp > vwap else 'FAIL'} (LTP:{ltp:.2f}, VWAP:{vwap:.2f})")
        print(f"  - Rule 6 (Above PP): {'PASS' if ltp > PP else 'FAIL'} (PP:{PP:.2f})")
        print(f"  - Rule 7 (RSI Momentum): {'PASS' if rsi >= wma else 'FAIL'} (RSI:{rsi:.1f}, WMA:{wma:.1f})")
        
        # Rule 8: R:R
        risk = ltp - vwap
        reward = R1 - ltp
        rr = reward/risk if risk > 0 else 0
        print(f"  - Rule 8 (R:R >= 1.5): {'PASS' if rr >= MIN_RR_RATIO else 'FAIL'} (RR:{rr:.2f}, R1:{R1:.2f})")
        if ltp >= R1:
            print("    [!] REASON: Stock is already above its Target (R1). Entry is too late.")

if __name__ == "__main__":
    debug_live()

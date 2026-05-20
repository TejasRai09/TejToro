
import pandas as pd
import sys
import os
from datetime import time

# Add current directory to path
sys.path.append(os.getcwd())

import data_fetcher
import indicators
import config
from instruments import load_instruments

def evaluate_stock_verbose(symbol, instrument_key, market_cap_cr):
    print(f"  [DEBUG] Fetching candles for {symbol}...")
    try:
        df_raw = data_fetcher.get_10min_candles(instrument_key, days_back=3)
    except Exception as e:
        print(f"  [FAIL] Data fetch error: {e}")
        return None

    if df_raw.empty:
        print("  [FAIL] No candle data returned.")
        return None
        
    if len(df_raw) < (21 + 14 + 2):
        print(f"  [FAIL] Not enough candles for indicators (got {len(df_raw)}).")
        return None

    print(f"  [DEBUG] Preparing indicators...")
    today_df, pivots = indicators.prepare_indicators(df_raw)

    if today_df.empty:
        print("  [FAIL] today_df is empty after processing indicators.")
        return None
        
    if not pivots or pivots.get("R1") is None:
        print("  [FAIL] Pivots could not be calculated.")
        return None

    first_candle = today_df.iloc[0]
    live_candle  = today_df.iloc[-1]
    
    ltp      = live_candle["close"]
    vwap     = live_candle["vwap"]
    rsi      = live_candle["rsi"]
    wma_rsi  = live_candle["wma_rsi"]
    PP = pivots["PP"]
    R1 = pivots["R1"]
    
    print(f"  [DEBUG] Values - LTP: {ltp}, VWAP: {vwap:.2f}, RSI: {rsi:.2f}, WMA: {wma_rsi:.2f}, PP: {PP}, R1: {R1}")

    # Rule 2: Market cap
    if market_cap_cr > 0 and market_cap_cr < config.MIN_MARKET_CAP_CR:
        print(f"  [FAIL] Rule 2: Market Cap too low ({market_cap_cr} < {config.MIN_MARKET_CAP_CR})")
        return None

    # Rule 3: Price range
    if not (config.MIN_STOCK_PRICE <= ltp <= config.MAX_STOCK_PRICE):
        print(f"  [FAIL] Rule 3: Price out of range ({ltp})")
        return None

    # Rule 4: Open Drive
    first_open = first_candle["open"]
    first_low  = first_candle["low"]
    first_time = first_candle.name.time()
    tolerance  = first_open * config.OPEN_LOW_TOLERANCE
    is_open_drive = abs(first_open - first_low) <= tolerance
    
    print(f"  [DEBUG] First candle time: {first_time}, Open: {first_open}, Low: {first_low}, Tol: {tolerance:.4f}")
    
    if first_time > time(9, 15):
        print(f"  [FAIL] Rule 4: Missed 9:15 candle (first candle is {first_time})")
        return None

    if not is_open_drive:
        print(f"  [FAIL] Rule 4: Not an Open Drive (diff: {abs(first_open - first_low):.4f} > {tolerance:.4f})")
        return None

    # Rule 5: VWAP
    if ltp <= vwap:
        print(f"  [FAIL] Rule 5: Price below VWAP ({ltp} <= {vwap:.2f})")
        return None

    # Rule 6: PP
    if ltp <= PP:
        print(f"  [FAIL] Rule 6: Price below PP ({ltp} <= {PP})")
        return None

    # Rule 7: RSI momentum
    if rsi < wma_rsi:
        print(f"  [FAIL] Rule 7: RSI < WMA ({rsi:.2f} < {wma_rsi:.2f})")
        return None

    # Rule 8: RR
    risk_per_share   = ltp - vwap
    reward_per_share = R1 - ltp
    if risk_per_share <= 0:
        print(f"  [FAIL] Rule 8: Invalid risk (<= 0)")
        return None
    rr_ratio = reward_per_share / risk_per_share
    if rr_ratio < config.MIN_RR_RATIO:
        print(f"  [FAIL] Rule 8: RR Ratio too low ({rr_ratio:.2f} < {config.MIN_RR_RATIO})")
        return None

    # Rule 9: R1 distance
    r1_distance_pct = ((R1 - ltp) / ltp) * 100
    if r1_distance_pct < config.MIN_R1_DISTANCE_PCT:
        print(f"  [FAIL] Rule 9: R1 distance too low ({r1_distance_pct:.2f}% < {config.MIN_R1_DISTANCE_PCT}%)")
        return None

    print("  [SUCCESS] All rules passed!")
    return True

def diag():
    print("Loading instruments...")
    instruments = load_instruments()
    test_symbols = ["COFORGE", "RELIANCE", "GROWW", "HDFCBANK"]
    test_inst = instruments[instruments['symbol'].isin(test_symbols)]
    
    if test_inst.empty:
        test_inst = instruments.head(3)

    for _, row in test_inst.iterrows():
        print(f"\n--- Testing {row['symbol']} ---")
        evaluate_stock_verbose(row['symbol'], row['instrument_key'], row.get('market_cap_cr', 0))

if __name__ == "__main__":
    diag()

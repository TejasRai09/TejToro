import sys
import codecs
sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

from data_fetcher import get_market_quotes, get_10min_candles, get_daily_candles
from indicators import prepare_indicators
from instruments import load_instruments
from config import (
    MIN_MARKET_CAP_CR, MIN_STOCK_PRICE, MAX_STOCK_PRICE,
    OPEN_LOW_TOLERANCE, MIN_RR_RATIO, MIN_R1_DISTANCE_PCT,
    MAX_RISK_PER_TRADE
)
import pandas as pd
import time

df = load_instruments()
if df.empty:
    print("NO INSTRUMENTS LOADED.")
    sys.exit()

print(f"Testing first 20 stocks of {len(df)}...")
fail_reasons = {}

def track_fail(reason):
    fail_reasons[reason] = fail_reasons.get(reason, 0) + 1

for i in range(min(20, len(df))):
    sym = df.iloc[i]['symbol']
    key = df.iloc[i]['instrument_key']
    mcap = df.iloc[i]['market_cap_cr']
    print(f"[{i+1}/20] Checking {sym}...", end=" ", flush=True)

    try:
        candles = get_10min_candles(key)
        
        if candles.empty:
            print("FAILED (Empty candles)")
            track_fail("Empty candles")
            continue
            
        res = prepare_indicators(candles)
        if not res or res[0].empty:
            print("FAILED (Indicators failed)")
            track_fail("Indicators failed")
            continue
            
        today_df, pivots = res
        
        latest = today_df.iloc[-1]
        first_candle = today_df.iloc[0] if not today_df.empty else None
        
        if first_candle is None:
            print("FAILED (No first candle)")
            track_fail("No first candle")
            continue

        ltp = latest["close"]
        vwap = latest["vwap"]
        rsi = latest["rsi"]
        wma_rsi = latest["wma_rsi"]
        PP = pivots.get("PP")
        R1 = pivots.get("R1")
        R2 = pivots.get("R2")

        if any(v is None or pd.isna(v) for v in [ltp, vwap, rsi, wma_rsi, PP, R1, R2]):
            print("FAILED (NaN in indicators)")
            track_fail("NaN in indicators")
            continue

        if mcap > 0 and mcap < MIN_MARKET_CAP_CR:
            print("FAILED (Market cap)")
            track_fail("Rule 2: Market cap")
            continue
        
        if not (MIN_STOCK_PRICE <= ltp <= MAX_STOCK_PRICE):
            print("FAILED (Price range)")
            track_fail("Rule 3: Price range")
            continue

        first_open = first_candle["open"]
        first_low  = first_candle["low"]
        tolerance  = first_open * OPEN_LOW_TOLERANCE
        if abs(first_open - first_low) > tolerance:
            print("FAILED (Open != Low)")
            track_fail("Rule 4: Open != Low")
            continue

        if ltp <= vwap:
            print("FAILED (<= VWAP)")
            track_fail("Rule 5: <= VWAP")
            continue

        if ltp <= PP:
            print("FAILED (<= PP)")
            track_fail("Rule 6: <= PP")
            continue

        if rsi < wma_rsi:
            print("FAILED (RSI < WMA)")
            track_fail("Rule 7: RSI < WMA")
            continue

        risk_per_share   = ltp - vwap
        reward_per_share = R1 - ltp

        if risk_per_share <= 0:
            print("FAILED (Risk <= 0)")
            track_fail("Rule 8: Risk <= 0")
            continue

        rr_ratio = reward_per_share / risk_per_share
        if rr_ratio < MIN_RR_RATIO:
            print(f"FAILED (Low R:R {rr_ratio:.2f})")
            track_fail("Rule 8: Low R:R")
            continue

        r1_distance_pct = ((R1 - ltp) / ltp) * 100
        if r1_distance_pct < MIN_R1_DISTANCE_PCT:
            print(f"FAILED (R1 too close {r1_distance_pct:.2f}%)")
            track_fail("Rule 9: R1 too close")
            continue
            
        shares = int(MAX_RISK_PER_TRADE / risk_per_share)
        if shares <= 0:
            print("FAILED (Shares <= 0)")
            track_fail("Shares <= 0")
            continue
            
        print("PASSED")
        track_fail("PASSED")
    except Exception as e:
        print(f"ERROR: {e}")
        track_fail(f"Exception: {type(e).__name__}")
    
    time.sleep(0.1) # Be gentle

print("\nSummary of Failure reasons:")
for r, c in fail_reasons.items():
    print(f"  {r}: {c}")

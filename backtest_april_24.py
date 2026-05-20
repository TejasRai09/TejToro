"""
backtest_april_24.py — Specifically test the Open Drive strategy for April 24, 2026.
"""

import os
import pandas as pd
import numpy as np
from datetime import date
from backtester import load_all_data, calc_rsi, calc_wma, calc_pivots
from config import (
    MIN_STOCK_PRICE, MAX_STOCK_PRICE,
    MIN_RR_RATIO, MIN_R1_DISTANCE_PCT, OPEN_LOW_TOLERANCE,
    MAX_RISK_PER_TRADE, MAX_TRADE_VALUE,
    T1_EXIT_PCT, T2_EXIT_PCT,
    TOTAL_CAPITAL, RSI_PERIOD, WMA_PERIOD,
)

TARGET_DATE = date(2026, 4, 24)

def run():
    print("=" * 60)
    print(f"  BACKTESTING FOR {TARGET_DATE}")
    print("=" * 60)

    all_data = load_all_data()
    if not all_data:
        print("No data found in backtest_data/")
        return

    print(f"Loaded {len(all_data)} stocks.")

    signals = []
    
    for symbol, df in all_data.items():
        # Indicators
        rsi = calc_rsi(df["close"], RSI_PERIOD)
        wma_rsi = calc_wma(rsi, WMA_PERIOD)

        # Check if Target Date and Previous Day exist
        if TARGET_DATE not in df.index.date:
            continue
            
        today_rows = df[df.index.date == TARGET_DATE]
        prev_mask = df.index.date < TARGET_DATE
        prev_rows = df[prev_mask]
        
        if today_rows.empty or prev_rows.empty:
            continue
            
        today_candle = today_rows.iloc[0]
        prev_candle = prev_rows.iloc[-1]
        
        # Strategy Logic
        open_p = today_candle["open"]
        low_p  = today_candle["low"]
        high_p = today_candle["high"]
        close_p = today_candle["close"]
        
        # Rule 4: Open=Low
        tolerance = open_p * OPEN_LOW_TOLERANCE
        if abs(open_p - low_p) > tolerance:
            continue
            
        # Pivots
        PP, R1, R2, S1, S2 = calc_pivots(prev_candle["high"], prev_candle["low"], prev_candle["close"])
        
        # Entry
        entry = round(open_p * 1.003, 2)
        
        # Rules 5 & 6: Above Pivot
        if entry <= PP:
            continue
            
        # Rule 7: RSI Momentum
        rsi_val = rsi.get(prev_rows.index[-1], np.nan)
        wma_val = wma_rsi.get(prev_rows.index[-1], np.nan)
        if pd.isna(rsi_val) or rsi_val < wma_val:
            continue
            
        # Rule 8: R:R
        risk = entry - PP
        reward = R1 - entry
        if risk <= 0 or (reward/risk) < MIN_RR_RATIO:
            continue
            
        # Rule 9: R1 Distance
        if ((R1 - entry) / entry) * 100 < MIN_R1_DISTANCE_PCT:
            continue

        # Position Sizing
        shares = int(MAX_RISK_PER_TRADE / risk)
        if shares * entry > MAX_TRADE_VALUE:
            shares = int(MAX_TRADE_VALUE / entry)
        if shares <= 0:
            continue

        # Exit Simulation
        pnl = 0
        exit_type = ""
        if low_p <= PP:
            exit_type = "STOPPED"
            pnl = shares * (PP - entry)
        elif high_p >= R2:
            exit_type = "T2_HIT"
            pnl = (int(shares * T1_EXIT_PCT) * (R1 - entry)) + ((shares - int(shares * T1_EXIT_PCT)) * (R2 - entry))
        elif high_p >= R1:
            exit_type = "T1_HIT"
            pnl = (int(shares * T1_EXIT_PCT) * (R1 - entry)) + ((shares - int(shares * T1_EXIT_PCT)) * (close_p - entry))
        else:
            exit_type = "TIME_EXIT"
            pnl = shares * (close_p - entry)

        signals.append({
            "Symbol": symbol,
            "Entry": entry,
            "Stop": PP,
            "Target1": R1,
            "Target2": R2,
            "Exit": exit_type,
            "PnL": round(pnl, 2)
        })

    if not signals:
        print(f"\nNo signals found for {TARGET_DATE}.")
    else:
        results_df = pd.DataFrame(signals)
        print(f"\nFound {len(results_df)} signals:")
        print(results_df.to_string(index=False))
        print(f"\nTotal P&L for the day: Rs.{results_df['PnL'].sum():,.2f}")

if __name__ == "__main__":
    run()

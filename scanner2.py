
import math
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from data_fetcher import get_10min_candles, get_market_quotes
from indicators import prepare_indicators
from config import (
    MIN_STOCK_PRICE, MAX_STOCK_PRICE,
    MAX_RISK_PER_TRADE, MAX_TRADE_VALUE,
    T1_EXIT_PCT, T2_EXIT_PCT, MIN_RR_RATIO,
)

IST = ZoneInfo("Asia/Kolkata")

def evaluate_stock_v2(symbol: str, instrument_key: str, market_cap_cr: float) -> dict | None:
    """
    Implementation of the Convergence Strategy (App2).
    """
    try:
        # Fetch 10-min candles (days_back=3 for indicators)
        df_raw = get_10min_candles(instrument_key, days_back=3)
    except Exception:
        return None

    if df_raw.empty or len(df_raw) < 5: 
        return None

    # Prepare indicators (VWAP, RSI, WMA, and now Supertrend 6,2)
    today_df, pivots = prepare_indicators(df_raw)
    if today_df.empty or not pivots or pivots.get("PP") is None:
        return None

    # ── Current & Historical Candles ──────────────────────────────────────
    live_candle = today_df.iloc[-1]
    prev_1      = today_df.iloc[-2] if len(today_df) >= 2 else None
    prev_2      = today_df.iloc[-3] if len(today_df) >= 3 else None

    close = live_candle["close"]
    vwap  = live_candle["vwap"]
    st    = live_candle["st"]  # Supertrend (6,2)
    PP    = pivots["PP"]

    # ═════════════════════════════════════════════════════════════════════
    #  PRE-FILTER (Proximity Checks)
    # ═════════════════════════════════════════════════════════════════════
    # Rules: ST, VWAP, and PP must be close to each other (within 1%)
    # And price must be hugging Pivot Point (within 0.2%)
    
    st_vwap_diff = abs(st - vwap)
    vwap_pp_diff = abs(vwap - PP)
    pp_st_diff   = abs(PP - st)
    price_pp_diff = abs(close - PP)

    if st_vwap_diff > (close * 0.01): return None
    if vwap_pp_diff > (close * 0.01): return None
    if pp_st_diff   > (close * 0.01): return None
    if price_pp_diff > (close * 0.002): return None

    # ═════════════════════════════════════════════════════════════════════
    #  MAIN SCAN RULES
    # ═════════════════════════════════════════════════════════════════════
    
    # 1. Market Cap >= 1000 Cr
    if market_cap_cr < 1000:
        return None

    # 2. Bullish Supertrend
    if close < st:
        return None

    # 3. Above Daily Pivot
    if close < PP:
        return None

    # 4. Above VWAP (Current + Previous 2 candles)
    if close < vwap: return None
    if prev_1 is not None and prev_1["close"] < prev_1["vwap"]: return None
    if prev_2 is not None and prev_2["close"] < prev_2["vwap"]: return None

    # 5. Price Range
    if not (MIN_STOCK_PRICE <= close <= MAX_STOCK_PRICE):
        return None

    # ═════════════════════════════════════════════════════════════════════
    #  POSITION SIZING
    # ═════════════════════════════════════════════════════════════════════
    R1 = pivots.get("R1")
    R2 = pivots.get("R2")
    S1 = pivots.get("S1")
    if not R1 or not R2 or not S1:
        return None

    # Stop at S1 (pivot support below PP)
    stop_loss = S1
    stop_dist = close - stop_loss
    if stop_dist <= 0:
        return None

    shares = int(MAX_RISK_PER_TRADE / stop_dist)
    shares = min(shares, int(MAX_TRADE_VALUE / close))
    if shares <= 0:
        return None

    t1_shares = math.floor(shares * T1_EXIT_PCT)
    t2_shares = shares - t1_shares
    if t2_shares <= 0:
        t1_shares = shares - 1
        t2_shares = 1

    trade_value = round(shares * close, 2)
    max_loss    = round(shares * stop_dist, 2)
    max_gain    = round(t1_shares * (R1 - close) + t2_shares * (R2 - close), 2)
    rr_ratio    = round(max_gain / max_loss, 2) if max_loss > 0 else 0

    if rr_ratio < MIN_RR_RATIO:
        return None

    # ═════════════════════════════════════════════════════════════════════
    #  SIGNAL FOUND
    # ═════════════════════════════════════════════════════════════════════
    return {
        "symbol":         symbol,
        "instrument_key": instrument_key,
        "entry":          round(close, 2),
        "st":             round(st, 2),
        "vwap":           round(vwap, 2),
        "pp":             round(PP, 2),
        "R1":             R1,
        "R2":             R2,
        "S1":             S1,
        "stop_loss":      round(stop_loss, 2),
        "shares":         shares,
        "t1_shares":      t1_shares,
        "t2_shares":      t2_shares,
        "trade_value":    trade_value,
        "max_loss":       max_loss,
        "max_gain":       max_gain,
        "rr_ratio":       rr_ratio,
        "market_cap_cr":  market_cap_cr,
        "signal_time":    datetime.now(IST).strftime("%H:%M:%S"),
        "st_vwap_gap":    round(st_vwap_diff / close * 100, 3),
        "price_pp_gap":   round(price_pp_diff / close * 100, 3),
    }

def run_scanner_v2(instruments: pd.DataFrame):
    """Generator for app2.py UI."""
    total = len(instruments)
    yield (0, total, "scan", None)

    for i, (_, row) in enumerate(instruments.iterrows()):
        result = evaluate_stock_v2(
            symbol=row["symbol"],
            instrument_key=row["instrument_key"],
            market_cap_cr=row["market_cap_cr"]
        )
        yield (i + 1, total, "scan", result)

    yield (total, total, "scan", "DONE")

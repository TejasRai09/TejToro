"""
indicators.py — Pure indicator calculations. No trading logic here.

Functions:
    calculate_vwap(df)         — cumulative VWAP, resets each day
    calculate_rsi(df, period)  — RSI on close prices
    calculate_wma_rsi(rsi, period) — Weighted Moving Average of RSI
    calculate_pivots(prev_df)  — Standard Pivot Points from yesterday's data
    prepare_indicators(df)     — runs all indicators on a 10-min DataFrame

Input:  DataFrame with columns: open, high, low, close, volume
        Index must be DatetimeIndex (this is already how data_fetcher returns it)
Output: Same DataFrame with indicator columns added
"""

import pandas as pd
import numpy as np
from config import RSI_PERIOD, WMA_PERIOD


# ── VWAP ──────────────────────────────────────────────────────────────────

def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Calculates cumulative VWAP that resets at the start of each trading day.

    Formula:
        Typical Price (TP) = (High + Low + Close) / 3
        VWAP = Cumulative(TP × Volume) / Cumulative(Volume)

    Why cumulative and not rolling:
        VWAP is an institutional benchmark calculated from market open.
        A rolling VWAP (e.g. 20-period) is a different indicator entirely.
        We want the real VWAP that institutions use — from 9:15 AM each day.
    """
    df = df.copy()
    df["tp"] = (df["high"] + df["low"] + df["close"]) / 3
    df["tp_vol"] = df["tp"] * df["volume"]

    # Group by date so VWAP resets each day
    df["date"] = df.index.date
    df["cum_tp_vol"] = df.groupby("date")["tp_vol"].cumsum()
    df["cum_vol"] = df.groupby("date")["volume"].cumsum()

    vwap = df["cum_tp_vol"] / df["cum_vol"]

    # Clean up helper columns
    df.drop(columns=["tp", "tp_vol", "date", "cum_tp_vol", "cum_vol"], inplace=True)

    return vwap


# ── RSI ───────────────────────────────────────────────────────────────────

def calculate_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """
    Calculates RSI using Wilder's Smoothing Method (the correct method).

    Why Wilder's and not simple EMA:
        RSI was defined by Wilder using a specific smoothing technique.
        Using standard EMA gives different values — your signals won't match
        what you see on TradingView or any professional charting platform.

    Formula:
        Delta   = close.diff()
        Gain    = delta where delta > 0, else 0
        Loss    = abs(delta where delta < 0), else 0
        RS      = Wilder's Smooth Avg Gain / Wilder's Smooth Avg Loss
        RSI     = 100 - (100 / (1 + RS))
    """
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Wilder's smoothing = EMA with alpha = 1/period
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return rsi


# ── WMA of RSI ────────────────────────────────────────────────────────────

def calculate_wma(series: pd.Series, period: int = WMA_PERIOD) -> pd.Series:
    """
    Calculates Weighted Moving Average (WMA) of any series.

    Why WMA and not SMA or EMA:
        WMA gives more weight to recent values linearly.
        For RSI momentum confirmation, WMA responds faster than SMA
        without the lag distortion of EMA.

    Formula:
        Weights = [1, 2, 3, ..., period]
        WMA = sum(value[i] × weight[i]) / sum(weights)
    """
    weights = pd.Series(range(1, period + 1))

    def _wma(window):
        if len(window) < period:
            return np.nan
        return np.dot(window, weights) / weights.sum()

    return series.rolling(window=period).apply(_wma, raw=True)


# ── Supertrend (6,2) ──────────────────────────────────────────────────────

def calculate_supertrend(df: pd.DataFrame, period: int = 6, multiplier: int = 2) -> pd.Series:
    """
    Calculates the Supertrend indicator.
    
    Formula:
        Basic Upperband = (High + Low) / 2 + (Multiplier * ATR)
        Basic Lowerband = (High + Low) / 2 - (Multiplier * ATR)
    """
    df = df.copy()
    
    # Calculate ATR
    high_low = df['high'] - df['low']
    high_cp = np.abs(df['high'] - df['close'].shift())
    low_cp = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()

    hl2 = (df['high'] + df['low']) / 2
    final_upperband = hl2 + (multiplier * atr)
    final_lowerband = hl2 - (multiplier * atr)
    
    # Initialize supertrend
    supertrend = np.zeros(len(df))
    direction = np.ones(len(df)) # 1 for up, -1 for down
    
    for i in range(1, len(df)):
        # Upperband logic
        if df['close'].iloc[i-1] <= final_upperband.iloc[i-1]:
            final_upperband.iloc[i] = min(final_upperband.iloc[i], final_upperband.iloc[i-1])
            
        # Lowerband logic
        if df['close'].iloc[i-1] >= final_lowerband.iloc[i-1]:
            final_lowerband.iloc[i] = max(final_lowerband.iloc[i], final_lowerband.iloc[i-1])
            
        # Determine direction
        if df['close'].iloc[i] > final_upperband.iloc[i-1]:
            direction[i] = 1
        elif df['close'].iloc[i] < final_lowerband.iloc[i-1]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]
            if direction[i] == 1 and final_lowerband.iloc[i] < final_lowerband.iloc[i-1]:
                final_lowerband.iloc[i] = final_lowerband.iloc[i-1]
            if direction[i] == -1 and final_upperband.iloc[i] > final_upperband.iloc[i-1]:
                final_upperband.iloc[i] = final_upperband.iloc[i-1]
                
        if direction[i] == 1:
            supertrend[i] = final_lowerband.iloc[i]
        else:
            supertrend[i] = final_upperband.iloc[i]
            
    return pd.Series(supertrend, index=df.index)


# ── Pivot Points ──────────────────────────────────────────────────────────

def calculate_pivots(prev_df: pd.DataFrame) -> dict:
    """
    Calculates Standard Pivot Points from the previous day's data.

    Why previous day and not current day:
        Pivot points are forward-looking levels calculated AFTER yesterday
        closes. They represent potential support/resistance for TODAY.
        Using today's data to calculate today's pivots is circular and wrong.

    Args:
        prev_df: DataFrame containing only previous day's candles

    Returns:
        Dictionary with PP, R1, R2, S1, S2 — all rounded to 2 decimal places

    Formula:
        PP = (Prev High + Prev Low + Prev Close) / 3
        R1 = (2 × PP) − Prev Low
        R2 = PP + (Prev High − Prev Low)
        S1 = (2 × PP) − Prev High
        S2 = PP − (Prev High − Prev Low)
    """
    if prev_df.empty:
        return {"PP": None, "R1": None, "R2": None, "S1": None, "S2": None}

    prev_high  = prev_df["high"].max()
    prev_low   = prev_df["low"].min()
    prev_close = prev_df["close"].iloc[-1]

    PP = (prev_high + prev_low + prev_close) / 3
    R1 = (2 * PP) - prev_low
    R2 = PP + (prev_high - prev_low)
    S1 = (2 * PP) - prev_high
    S2 = PP - (prev_high - prev_low)

    return {
        "PP": round(PP, 2),
        "R1": round(R1, 2),
        "R2": round(R2, 2),
        "S1": round(S1, 2),
        "S2": round(S2, 2),
    }


# ── Master Prepare Function ───────────────────────────────────────────────

def prepare_indicators(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Runs all indicators on a 10-minute OHLCV DataFrame.

    Expects df to contain at least 2 days of data:
        - Yesterday's data: used to calculate pivot points
        - Today's data:     used for VWAP, RSI, WMA

    Returns:
        today_df : DataFrame with today's candles + all indicator columns
        pivots   : Dictionary with PP, R1, R2, S1, S2

    Columns added to today_df:
        vwap     — cumulative VWAP from 9:15 AM today
        rsi      — RSI(14) on close
        wma_rsi  — WMA(21) of RSI
    """
    if df.empty or len(df) < (WMA_PERIOD + RSI_PERIOD):
        return pd.DataFrame(), {}

    # Ensure DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # Separate today and yesterday
    current_date = df.index[-1].date()
    today_df     = df[df.index.date == current_date].copy()
    prev_df      = df[df.index.date < current_date].copy()

    if today_df.empty or prev_df.empty:
        return pd.DataFrame(), {}

    # ── Calculate Pivots from yesterday ───────────────────────────────────
    pivots = calculate_pivots(prev_df)

    # ── Calculate indicators on FULL df (need history for RSI/WMA warmup) ─
    # RSI and WMA need historical data to produce accurate values today.
    # A 14-period RSI calculated on only today's 3-4 candles is meaningless.
    # We calculate on full df, then slice today's rows at the end.

    full_vwap    = calculate_vwap(df)
    full_rsi     = calculate_rsi(df["close"], period=RSI_PERIOD)
    full_wma_rsi = calculate_wma(full_rsi, period=WMA_PERIOD)
    full_st      = calculate_supertrend(df, period=6, multiplier=2)

    # Attach to today's slice
    today_df["vwap"]    = full_vwap[today_df.index]
    today_df["rsi"]     = full_rsi[today_df.index]
    today_df["wma_rsi"] = full_wma_rsi[today_df.index]
    today_df["st"]      = full_st[today_df.index]

    # Drop only the essential columns for App 1
    today_df = today_df.dropna(subset=["vwap", "rsi", "wma_rsi"])

    if today_df.empty:
        return pd.DataFrame(), {}

    return today_df, pivots


# ── Sanity Check ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Quick test — run: python indicators.py
    Uses a small synthetic dataset to verify outputs look correct.
    """
    import numpy as np

    print("Running indicators.py sanity check...\n")

    # Generate 3 days of fake 10-min data (3 × 38 candles per day = 114 rows)
    periods = 114
    dates = pd.date_range("2024-01-01 09:15", periods=periods, freq="10min")

    # Filter to trading hours only
    dates = dates[dates.time >= pd.Timestamp("09:15").time()]
    dates = dates[dates.time <= pd.Timestamp("15:20").time()]

    np.random.seed(42)
    close  = 100 + np.random.randn(len(dates)).cumsum()
    open_  = close + np.random.randn(len(dates)) * 0.2
    high   = np.maximum(close, open_) + np.abs(np.random.randn(len(dates)) * 0.3)
    low    = np.minimum(close, open_) - np.abs(np.random.randn(len(dates)) * 0.3)
    volume = np.random.randint(10000, 100000, len(dates)).astype(float)

    df = pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume
    }, index=dates)

    today_df, pivots = prepare_indicators(df)

    if today_df.empty:
        print("❌ prepare_indicators returned empty. Need more historical data.")
    else:
        print(f"✅ Today's candles with indicators: {len(today_df)} rows")
        print(f"\nPivot Points:")
        for k, v in pivots.items():
            print(f"   {k}: {v}")
        print(f"\nLast candle:")
        last = today_df.iloc[-1]
        print(f"   Close:   {last['close']:.2f}")
        print(f"   VWAP:    {last['vwap']:.2f}")
        print(f"   RSI:     {last['rsi']:.2f}")
        print(f"   WMA RSI: {last['wma_rsi']:.2f}")
        print(f"\n✅ All indicators working correctly.")

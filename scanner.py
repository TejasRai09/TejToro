"""
scanner.py — The core signal engine.

What this file does:
    1. Takes one stock at a time
    2. Fetches its 10-min candle data
    3. Runs all 9 entry rules in sequence (fails fast — stops at first failure)
    4. If all rules pass: calculates fixed stop, position size, R:R ratio
    5. Returns a complete signal dictionary or None

What this file does NOT do:
    - Place orders (that's manual)
    - Send alerts (that's notifier.py)
    - Display anything (that's app.py)
    - Track positions (that's tracker.py)

Run order:
    config.py → instruments.py → data_fetcher.py → indicators.py → scanner.py
"""

import pandas as pd
from datetime import datetime, time
from zoneinfo import ZoneInfo

from data_fetcher import get_10min_candles, get_market_quotes
from indicators import prepare_indicators
from config import (
    MIN_STOCK_PRICE,
    MAX_STOCK_PRICE,
    MIN_MARKET_CAP_CR,
    MIN_RR_RATIO,
    MIN_R1_DISTANCE_PCT,
    OPEN_LOW_TOLERANCE,
    MIN_DAILY_CHANGE_PCT,
    MAX_RISK_PER_TRADE,
    MAX_TRADE_VALUE,
    SCAN_START_TIME,
    SCAN_END_TIME,
    T1_EXIT_PCT,
    T2_EXIT_PCT,
    STOP_LOSS_PCT,
)

IST = ZoneInfo("Asia/Kolkata")


# ── Time Gate (disabled — scanner runs anytime) ───────────────────────────

def is_scan_window_open() -> bool:
    """Always returns True — scan window restriction removed."""
    return True


def get_scan_window_status() -> str:
    """Always returns 'open' — scan window restriction removed."""
    return "open"


# ── Pre-filter: Quote Check ───────────────────────────────────────────────

def prefilter_by_quotes(instruments: pd.DataFrame) -> list[dict]:
    """
    Phase 1: Fast batch quote check before fetching candle data.

    Fetches live quotes in batches of 50.
    Filters out stocks that:
        - Have not moved >= MIN_DAILY_CHANGE_PCT today
        - Are outside the price range

    This eliminates ~80% of stocks before expensive candle fetches.
    Returns list of dicts: {symbol, instrument_key, market_cap_cr, ltp}
    """
    all_keys  = instruments["instrument_key"].tolist()
    key_info  = {
        row["instrument_key"]: {
            "symbol":        row["symbol"],
            "instrument_key": row["instrument_key"],
            "market_cap_cr": row.get("market_cap_cr", 0.0),
        }
        for _, row in instruments.iterrows()
    }

    passed = []

    for i in range(0, len(all_keys), 50):
        batch = all_keys[i: i + 50]
        try:
            quotes = get_market_quotes(batch)
            for _, data in quotes.items():
                token = data.get("instrument_token")
                info  = key_info.get(token)
                if not info:
                    continue

                ltp        = data.get("last_price")
                net_change = data.get("net_change")

                if not ltp or net_change is None:
                    continue

                # Price range filter
                if not (MIN_STOCK_PRICE <= ltp <= MAX_STOCK_PRICE):
                    continue

                # Daily change filter — stock must be moving up today
                prev_close = ltp - net_change
                if prev_close <= 0:
                    continue

                pct_change = (net_change / prev_close) * 100
                if pct_change < MIN_DAILY_CHANGE_PCT:
                    continue

                passed.append({**info, "ltp": ltp, "pct_change": round(pct_change, 2)})

        except Exception as e:
            print(f"   [WARN] Prefilter batch error: {e}")
            continue

    return passed


# ── The 9 Rules ───────────────────────────────────────────────────────────

def evaluate_stock(
    symbol: str,
    instrument_key: str,
    market_cap_cr: float,
) -> dict | None:
    """
    Fetches candle data and applies all 9 entry rules for one stock.
    Returns a complete signal dict if all rules pass, else None.

    Fail-fast design: rules are checked in order of cheapest to most
    restrictive. The moment one fails, we return None immediately
    without checking the rest. This keeps the scanner fast.
    """

    # ── Fetch Data ────────────────────────────────────────────────────────
    try:
        # days_back=3 gives enough history for RSI/WMA warmup
        df_raw = get_10min_candles(instrument_key, days_back=3)
    except Exception:
        return None

    if df_raw.empty or len(df_raw) < (21 + 14 + 2):  # WMA_PERIOD + RSI_PERIOD + buffer
        return None

    # ── Prepare Indicators ────────────────────────────────────────────────
    today_df, pivots = prepare_indicators(df_raw)

    if today_df.empty or not pivots or pivots.get("R1") is None:
        return None

    if len(today_df) < 1:
        return None

    # ── Extract Values ────────────────────────────────────────────────────
    first_candle = today_df.iloc[0]   # first 10-min candle of today
    live_candle  = today_df.iloc[-1]  # most recent 10-min candle

    ltp      = live_candle["close"]
    vwap     = live_candle["vwap"]
    rsi      = live_candle["rsi"]
    wma_rsi  = live_candle["wma_rsi"]

    # Live Candle OHLCV
    live_open   = live_candle["open"]
    live_high   = live_candle["high"]
    live_low    = live_candle["low"]
    live_close  = live_candle["close"]
    live_volume = live_candle["volume"]
    live_time_str = live_candle.name.strftime("%H:%M")

    # First Candle OHLCV
    first_open   = first_candle["open"]
    first_high   = first_candle["high"]
    first_low    = first_candle["low"]
    first_close  = first_candle["close"]
    first_volume = first_candle["volume"]
    first_time   = first_candle.name.time()
    first_time_str = first_candle.name.strftime("%H:%M")

    PP = pivots["PP"]
    R1 = pivots["R1"]
    R2 = pivots["R2"]

    # Basic NaN guard
    if any(pd.isna(v) for v in [ltp, vwap, rsi, wma_rsi, PP, R1, R2]):
        return None

    # ═════════════════════════════════════════════════════════════════════
    #  THE 9 RULES — checked in order, fail fast
    # ═════════════════════════════════════════════════════════════════════

    # Rule 1: Time gate — disabled, scanner runs anytime

    # Rule 2: Market cap >= 500 Cr (only if data is available)
    if market_cap_cr > 0 and market_cap_cr < MIN_MARKET_CAP_CR:
        return None

    # Rule 3: Price in valid range
    if not (MIN_STOCK_PRICE <= ltp <= MAX_STOCK_PRICE):
        return None

    # Rule 4: First candle of the day — Open = Low (within tolerance)
    # We explicitly look for the 09:15 AM candle. If it's missing, we use the first available
    # but compare against the Day Open if possible.
    tolerance  = first_open * OPEN_LOW_TOLERANCE

    is_open_drive = abs(first_open - first_low) <= tolerance
    
    # If the first candle isn't 09:15, it might be an unreliable signal
    if first_time > time(9, 15):
        # Additional safety: If we missed the 9:15 candle, this isn't a true "Open Drive"
        return None

    if not is_open_drive:
        return None  # Not an Open Drive

    # Rule 5: Current price > VWAP
    # Stock must be trading above its volume-weighted average.
    # Below VWAP = institutional selling pressure dominates.
    if ltp <= vwap:
        return None

    # Rule 6: Current price > Standard Pivot (PP)
    # Price must have cleared yesterday's pivot — a key institutional level.
    if ltp <= PP:
        return None

    # Rule 7: RSI >= WMA of RSI
    # Momentum must be accelerating, not decelerating.
    # RSI below its own moving average = momentum fading.
    if rsi < wma_rsi:
        return None

    # Set Stop Loss to a fixed 1% below the entry price to avoid tight VWAP wick outs
    stop_loss_level = ltp * (1 - STOP_LOSS_PCT)

    # Rule 8: Risk:Reward >= 1.5
    # This is the most important filter.
    # We risk (entry - Stop Loss). We target (R1 - entry).
    # If we risk more than we can make, skip the trade entirely.
    risk_per_share   = ltp - stop_loss_level
    reward_per_share = R1 - ltp

    if risk_per_share <= 0:
        return None  # Entry is at or below Stop Loss — invalid

    rr_ratio = reward_per_share / risk_per_share

    if rr_ratio < MIN_RR_RATIO:
        return None  # Not worth the risk

    # Rule 9: R1 must be at least 0.5% above entry
    # Filters out cases where R1 is so close that brokerage
    # and slippage eat the entire profit.
    r1_distance_pct = ((R1 - ltp) / ltp) * 100

    if r1_distance_pct < MIN_R1_DISTANCE_PCT:
        return None  # R1 too close — not enough room to profit

    # ═════════════════════════════════════════════════════════════════════
    #  ALL 9 RULES PASSED — calculate trade parameters
    # ═════════════════════════════════════════════════════════════════════

    # Position sizing
    # How many shares can we buy such that if stop is hit, loss = MAX_RISK_PER_TRADE
    shares = int(MAX_RISK_PER_TRADE / risk_per_share)  # round down, never up

    if shares <= 0:
        return None  # Risk per share is larger than our max risk — skip

    trade_value = shares * ltp

    # Cap trade value at MAX_TRADE_VALUE
    if trade_value > MAX_TRADE_VALUE:
        shares      = int(MAX_TRADE_VALUE / ltp)
        trade_value = shares * ltp

    if shares <= 0:
        return None

    # Partial exit quantities (for manual reference in the alert)
    t1_shares = max(1, int(shares * T1_EXIT_PCT))   # 60% at R1
    t2_shares = shares - t1_shares                  # remaining 40% at R2

    # Maximum possible loss if stop is hit (entire position)
    max_loss = round(shares * risk_per_share, 2)

    # Maximum possible gain if both targets hit
    max_gain_t1 = round(t1_shares * (R1 - ltp), 2)
    max_gain_t2 = round(t2_shares * (R2 - ltp), 2)
    max_gain    = round(max_gain_t1 + max_gain_t2, 2)

    signal_time = datetime.now(IST).strftime("%H:%M:%S")

    return {
        # Identity
        "symbol":          symbol,
        "signal_time":     signal_time,
        "market_cap_cr":   round(market_cap_cr, 0),

        # Entry
        "entry":           round(ltp, 2),

        # Stop — FIXED at 1% below entry price, never changes
        "stop_loss":       round(stop_loss_level, 2),

        # Targets
        "R1":              round(R1, 2),
        "R2":              round(R2, 2),
        "PP":              round(PP, 2),

        # Position
        "shares":          shares,
        "t1_shares":       t1_shares,
        "t2_shares":       t2_shares,
        "trade_value":     round(trade_value, 2),

        # Risk metrics
        "risk_per_share":  round(risk_per_share, 2),
        "rr_ratio":        round(rr_ratio, 2),
        "r1_distance_pct": round(r1_distance_pct, 2),
        "max_loss":        max_loss,
        "max_gain":        max_gain,

        # Indicator snapshot (for display and audit trail)
        "rsi":             round(rsi, 2),
        "wma_rsi":         round(wma_rsi, 2),
        "vwap":            round(vwap, 2),
        
        # Live Candle Details
        "live_time":       live_time_str,
        "live_open":       round(live_open, 2),
        "live_high":       round(live_high, 2),
        "live_low":        round(live_low, 2),
        "live_close":      round(live_close, 2),
        "live_volume":     int(live_volume) if pd.notna(live_volume) else 0,

        # First Candle Details
        "first_time":      first_time_str,
        "first_open":      round(first_open, 2),
        "first_high":      round(first_high, 2),
        "first_low":       round(first_low, 2),
        "first_close":     round(first_close, 2),
        "first_volume":    int(first_volume) if pd.notna(first_volume) else 0,
    }


# ── Main Scanner Generator ────────────────────────────────────────────────

def run_scanner(instruments: pd.DataFrame):
    """
    Generator that scans the full instrument universe.

    Yields tuples of (current, total, phase, result) where:
        current — how many stocks processed so far
        total   — total stocks in this phase
        phase   — "prefilter" or "scan"
        result  — signal dict if found, None if not, "DONE" when finished

    Generator design allows the Streamlit UI to update incrementally
    instead of freezing until the scan completes.

    Usage:
        for current, total, phase, result in run_scanner(instruments):
            # update progress bar
            if result and result != "DONE":
                # new signal found
    """
    # ── Phase 1: Quote pre-filter ─────────────────────────────────────────
    total_instruments = len(instruments)
    yield (0, total_instruments, "prefilter", None)

    passed = prefilter_by_quotes(instruments)
    total_passed = len(passed)

    if total_passed == 0:
        yield (total_instruments, total_instruments, "prefilter", "DONE")
        return

    yield (total_instruments, total_instruments, "prefilter", None)

    # ── Phase 2: Full rules evaluation ────────────────────────────────────
    # Sequential (not threaded) to respect Upstox rate limits.
    # With pre-filtering reducing universe to ~50-100 stocks,
    # sequential is fast enough.

    for i, stock in enumerate(passed):

        result = evaluate_stock(
            symbol        = stock["symbol"],
            instrument_key= stock["instrument_key"],
            market_cap_cr = stock["market_cap_cr"],
        )

        yield (i + 1, total_passed, "scan", result)

    yield (total_passed, total_passed, "scan", "DONE")

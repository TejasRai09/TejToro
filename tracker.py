"""
tracker.py — Live position monitor.

What this does:
    - Stores all active trades in Streamlit session state
    - On each refresh: fetches live prices for all open positions
    - Checks exit conditions: T1, T2, stop loss, time stop
    - Fires Telegram alerts when action is needed
    - Tracks daily P&L and enforces daily loss limit
    - Does NOT place orders — you do that manually

Trade lifecycle:
    ACTIVE
      → T1_HIT    (price >= R1 — sell 60%, hold 40%)
      → T2_HIT    (price >= R2 — sell remaining 40%) ✅ complete
      → STOPPED   (price <= stop_loss — exit all) ❌ loss
      → TIME_EXIT (3:15 PM — exit all remaining)   ⏰ forced

Each trade only fires ONE alert per status change.
The 'alerted' flag prevents duplicate Telegram messages on each refresh.
"""

import pandas as pd
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

from data_fetcher import get_market_quotes
from notifier import (
    alert_t1_hit,
    alert_t2_hit,
    alert_stop_hit,
    alert_time_stop,
    alert_daily_loss_limit,
)
from config import (
    DAILY_LOSS_LIMIT,
    MARKET_CLOSE_TIME,
)

IST = ZoneInfo("Asia/Kolkata")


# ── Session State Initialisation ──────────────────────────────────────────

def init_tracker_state():
    """
    Initialises all tracker-related session state keys.
    Call this once at the top of app.py before anything else.
    """
    defaults = {
        "active_trades":      {},   # symbol → trade dict
        "daily_loss":         0.0,  # total realised loss today in ₹
        "daily_gain":         0.0,  # total realised gain today in ₹
        "trades_taken":       0,    # number of signals acted on today
        "signals_found":      0,    # number of signals scanner found today
        "system_halted":      False,# True when daily loss limit is hit
        "is_tracking":        False,# True when live tracker is running
        "is_scanning":        False,# True when scanner is running
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ── Add Trade ─────────────────────────────────────────────────────────────

def add_trade(signal: dict) -> bool:
    """
    Adds a new trade to the active tracker.

    Returns False if:
        - Symbol already being tracked
    """
    sym = signal["symbol"]

    if sym in st.session_state.active_trades:
        return False  # Already tracking this symbol

    st.session_state.active_trades[sym] = {
        # Identity
        "symbol":       sym,
        "entry_time":   signal["signal_time"],

        # Price levels — all fixed at signal time
        "entry":        signal["entry"],
        "stop_loss":    signal["stop_loss"],   # FIXED — never changes
        "R1":           signal["R1"],
        "R2":           signal["R2"],

        # Position
        "shares":       signal["shares"],
        "t1_shares":    signal["t1_shares"],
        "t2_shares":    signal["t2_shares"],

        # Live data (updated on each refresh)
        "live_price":   signal["entry"],

        # Status
        "status":       "ACTIVE",

        # Alert flags — prevents duplicate Telegram messages
        "alerted_t1":   False,
        "alerted_t2":   False,
        "alerted_stop": False,
        "alerted_time": False,

        # P&L tracking
        "realised_pnl": 0.0,
    }

    st.session_state.trades_taken += 1
    return True


# ── Remove Trade ──────────────────────────────────────────────────────────

def remove_trade(symbol: str):
    """Removes a completed or manually closed trade from the tracker."""
    if symbol in st.session_state.active_trades:
        del st.session_state.active_trades[symbol]


# ── Symbol to Instrument Key Cache ────────────────────────────────────────

_SYMBOL_KEY_CACHE: dict[str, str] = {}

def build_symbol_cache(instruments: pd.DataFrame):
    """
    Builds a symbol → instrument_key lookup.
    Called once when tracking starts.
    """
    global _SYMBOL_KEY_CACHE
    for _, row in instruments.iterrows():
        _SYMBOL_KEY_CACHE[row["symbol"]] = row["instrument_key"]


# ── Core Tracking Loop ────────────────────────────────────────────────────

def update_tracker(instruments: pd.DataFrame = None):
    """
    Main tracking function — called on every Streamlit refresh when
    is_tracking is True.

    For each active position:
        1. Fetches live price
        2. Checks exit conditions in priority order:
               Stop loss first (most urgent)
               Time stop second
               T2 third
               T1 last (least urgent since T2 hasn't been hit yet)
        3. Fires Telegram alert on first status change only
        4. Updates daily P&L

    Does NOT rerun or refresh the UI — app.py handles that.
    """
    if not st.session_state.active_trades:
        return

    # Build cache if needed
    if instruments is not None and not _SYMBOL_KEY_CACHE:
        build_symbol_cache(instruments)

    now_str  = datetime.now(IST).strftime("%H:%M")
    is_close = now_str >= MARKET_CLOSE_TIME

    # Get all symbols that still need price monitoring
    open_statuses = ["ACTIVE", "T1_HIT"]
    open_symbols  = [
        sym for sym, t in st.session_state.active_trades.items()
        if t["status"] in open_statuses
    ]

    if not open_symbols:
        return

    # Fetch live prices in one batch
    keys = [
        _SYMBOL_KEY_CACHE.get(sym)
        for sym in open_symbols
        if _SYMBOL_KEY_CACHE.get(sym)
    ]

    if not keys:
        return

    try:
        quotes = get_market_quotes(keys)
    except Exception:
        return

    # Build price map: instrument_key → last_price
    price_map = {}
    for _, data in quotes.items():
        token = data.get("instrument_token")
        ltp   = data.get("last_price")
        if token and ltp:
            price_map[token] = float(ltp)

    # ── Process Each Open Trade ───────────────────────────────────────────
    for sym in open_symbols:
        trade = st.session_state.active_trades.get(sym)
        if not trade:
            continue

        key        = _SYMBOL_KEY_CACHE.get(sym)
        live_price = price_map.get(key)

        if not live_price:
            continue

        trade["live_price"] = live_price

        stop  = trade["stop_loss"]
        r1    = trade["R1"]
        r2    = trade["R2"]
        entry = trade["entry"]

        # ── Priority 1: Stop Loss ─────────────────────────────────────────
        # Checked first — protecting capital is the highest priority
        if live_price <= stop and not trade["alerted_stop"]:
            remaining_shares = (
                trade["t2_shares"]
                if trade["status"] == "T1_HIT"
                else trade["shares"]
            )
            loss = round(remaining_shares * (entry - live_price), 2)

            trade["status"]       = "STOPPED"
            trade["alerted_stop"] = True
            trade["realised_pnl"] -= abs(loss)

            # Update daily loss
            st.session_state.daily_loss = round(
                st.session_state.daily_loss + abs(loss), 2
            )

            alert_stop_hit(sym, live_price, stop, remaining_shares, abs(loss))

            # Check if daily loss limit hit
            if st.session_state.daily_loss >= DAILY_LOSS_LIMIT:
                st.session_state.system_halted = True
                alert_daily_loss_limit(
                    st.session_state.daily_loss,
                    DAILY_LOSS_LIMIT
                )
            continue

        # ── Priority 2: Time Stop ─────────────────────────────────────────
        # 3:15 PM -- force close all open positions
        if is_close and not trade["alerted_time"]:
            remaining_shares = (
                trade["t2_shares"]
                if trade["status"] == "T1_HIT"
                else trade["shares"]
            )
            
            pnl = round(remaining_shares * (live_price - entry), 2)
            trade["status"]       = "TIME_EXIT"
            trade["alerted_time"] = True
            trade["realised_pnl"] += pnl
            
            if pnl >= 0:
                st.session_state.daily_gain = round(st.session_state.daily_gain + pnl, 2)
            else:
                st.session_state.daily_loss = round(st.session_state.daily_loss + abs(pnl), 2)

            alert_time_stop(sym, remaining_shares, live_price)
            continue

        # ── Priority 3: Target 2 ──────────────────────────────────────────
        if trade["status"] == "T1_HIT" and live_price >= r2 and not trade["alerted_t2"]:
            gain = round(trade["t2_shares"] * (live_price - entry), 2)

            trade["status"]       = "T2_HIT"
            trade["alerted_t2"]   = True
            trade["realised_pnl"] += gain

            st.session_state.daily_gain = round(
                st.session_state.daily_gain + gain, 2
            )

            alert_t2_hit(sym, live_price, r2, trade["t2_shares"])
            continue

        # ── Priority 4: Target 1 ──────────────────────────────────────────
        if trade["status"] == "ACTIVE" and live_price >= r1 and not trade["alerted_t1"]:
            gain = round(trade["t1_shares"] * (live_price - entry), 2)

            trade["status"]       = "T1_HIT"
            trade["alerted_t1"]   = True
            trade["realised_pnl"] += gain

            st.session_state.daily_gain = round(
                st.session_state.daily_gain + gain, 2
            )

            alert_t1_hit(
                sym, live_price, r1,
                trade["t1_shares"], trade["t2_shares"], r2
            )
            continue


# ── Daily Summary ─────────────────────────────────────────────────────────

def get_daily_summary() -> dict:
    """
    Returns today's trading summary for the dashboard.
    """
    net_pnl      = st.session_state.daily_gain - st.session_state.daily_loss
    loss_used_pct = (st.session_state.daily_loss / DAILY_LOSS_LIMIT) * 100

    return {
        "trades_taken":    st.session_state.trades_taken,
        "signals_found":   st.session_state.signals_found,
        "daily_gain":      st.session_state.daily_gain,
        "daily_loss":      st.session_state.daily_loss,
        "net_pnl":         round(net_pnl, 2),
        "loss_limit":      DAILY_LOSS_LIMIT,
        "loss_used_pct":   round(loss_used_pct, 1),
        "system_halted":   st.session_state.system_halted,
    }


# ── Tracker Table Data ────────────────────────────────────────────────────

def get_tracker_rows() -> list[dict]:
    """
    Returns formatted rows for the tracker table in app.py.
    Each row has display-ready strings, not raw numbers.
    """
    rows = []
    for sym, t in st.session_state.active_trades.items():
        live  = t.get("live_price", t["entry"])
        entry = t["entry"]
        pnl   = round((live - entry) / entry * 100, 2)

        # Unrealised P&L for active positions
        if t["status"] == "ACTIVE":
            shares     = t["shares"]
            pnl_val    = round(shares * (live - entry), 2)
        elif t["status"] == "T1_HIT":
            # T1 gain is already realized, but T2 shares are still floating
            shares     = t["t2_shares"]
            floating   = round(shares * (live - entry), 2)
            pnl_val    = round(t["realised_pnl"] + floating, 2)
        else:
            # For closed positions, show the final total profit/loss
            pnl_val    = round(t["realised_pnl"], 2)

        rows.append({
            "Symbol":        sym,
            "Status":        t["status"],
            "Entry":         f"Rs {entry:.2f}",
            "Live Price":    f"Rs {live:.2f}",
            "Change":        f"{pnl:+.2f}%",
            "Stop (Fixed)":  f"Rs {t['stop_loss']:.2f}",
            "T1 (R1)":       f"Rs {t['R1']:.2f}",
            "T2 (R2)":       f"Rs {t['R2']:.2f}",
            "Shares":        t["shares"],
            "Unrealised":    f"Rs {pnl_val:+,.0f}",
        })

    return rows

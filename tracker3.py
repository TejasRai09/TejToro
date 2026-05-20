"""
tracker3.py — Live position monitor for App3 (Multi-Strategy).
Mirrors tracker2.py with _3 suffixed session state keys.
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
from config import DAILY_LOSS_LIMIT, MARKET_CLOSE_TIME

IST = ZoneInfo("Asia/Kolkata")

_SYMBOL_KEY_CACHE_3: dict[str, str] = {}


def init_tracker_state_3():
    defaults = {
        "active_trades_3":  {},
        "daily_loss_3":     0.0,
        "daily_gain_3":     0.0,
        "trades_taken_3":   0,
        "signals_found_3":  0,
        "system_halted_3":  False,
        "is_tracking_3":    False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def build_symbol_cache_3(instruments: pd.DataFrame):
    global _SYMBOL_KEY_CACHE_3
    for _, row in instruments.iterrows():
        _SYMBOL_KEY_CACHE_3[row["symbol"]] = row["instrument_key"]


def add_trade_3(signal: dict) -> bool:
    sym = signal["symbol"]
    if sym in st.session_state.active_trades_3:
        return False

    st.session_state.active_trades_3[sym] = {
        "symbol":       sym,
        "entry_time":   signal["signal_time"],
        "entry":        signal["entry"],
        "stop_loss":    signal["stop_loss"],
        "R1":           signal["R1"],
        "R2":           signal["R2"],
        "shares":       signal["shares"],
        "t1_shares":    signal["t1_shares"],
        "t2_shares":    signal["t2_shares"],
        "strategy":     signal.get("strategy", ""),
        "live_price":   signal["entry"],
        "status":       "ACTIVE",
        "alerted_t1":   False,
        "alerted_t2":   False,
        "alerted_stop": False,
        "alerted_time": False,
        "realised_pnl": 0.0,
    }
    st.session_state.trades_taken_3 += 1
    return True


def update_tracker_3(instruments: pd.DataFrame = None):
    if not st.session_state.active_trades_3:
        return

    if instruments is not None and not _SYMBOL_KEY_CACHE_3:
        build_symbol_cache_3(instruments)

    now_str  = datetime.now(IST).strftime("%H:%M")
    is_close = now_str >= MARKET_CLOSE_TIME

    open_symbols = [
        sym for sym, t in st.session_state.active_trades_3.items()
        if t["status"] in ("ACTIVE", "T1_HIT")
    ]
    if not open_symbols:
        return

    keys = [
        _SYMBOL_KEY_CACHE_3.get(sym)
        for sym in open_symbols
        if _SYMBOL_KEY_CACHE_3.get(sym)
    ]
    if not keys:
        return

    try:
        quotes = get_market_quotes(keys)
    except Exception:
        return

    price_map = {}
    for _, data in quotes.items():
        token = data.get("instrument_token")
        ltp   = data.get("last_price")
        if token and ltp:
            price_map[token] = float(ltp)

    for sym in open_symbols:
        trade = st.session_state.active_trades_3.get(sym)
        if not trade:
            continue

        key        = _SYMBOL_KEY_CACHE_3.get(sym)
        live_price = price_map.get(key)
        if not live_price:
            continue

        trade["live_price"] = live_price
        stop  = trade["stop_loss"]
        r1    = trade["R1"]
        r2    = trade["R2"]
        entry = trade["entry"]

        # Priority 1: Stop Loss
        if live_price <= stop and not trade["alerted_stop"]:
            remaining = trade["t2_shares"] if trade["status"] == "T1_HIT" else trade["shares"]
            loss = round(remaining * (entry - live_price), 2)
            trade["status"]       = "STOPPED"
            trade["alerted_stop"] = True
            trade["realised_pnl"] -= abs(loss)
            st.session_state.daily_loss_3 = round(st.session_state.daily_loss_3 + abs(loss), 2)
            alert_stop_hit(sym, live_price, stop, remaining, abs(loss))
            if st.session_state.daily_loss_3 >= DAILY_LOSS_LIMIT:
                st.session_state.system_halted_3 = True
                alert_daily_loss_limit(st.session_state.daily_loss_3, DAILY_LOSS_LIMIT)
            continue

        # Priority 2: Time Stop
        if is_close and not trade["alerted_time"]:
            remaining = trade["t2_shares"] if trade["status"] == "T1_HIT" else trade["shares"]
            pnl = round(remaining * (live_price - entry), 2)
            trade["status"]       = "TIME_EXIT"
            trade["alerted_time"] = True
            trade["realised_pnl"] += pnl
            if pnl >= 0:
                st.session_state.daily_gain_3 = round(st.session_state.daily_gain_3 + pnl, 2)
            else:
                st.session_state.daily_loss_3 = round(st.session_state.daily_loss_3 + abs(pnl), 2)
            alert_time_stop(sym, remaining, live_price)
            continue

        # Priority 3: Target 2
        if trade["status"] == "T1_HIT" and live_price >= r2 and not trade["alerted_t2"]:
            gain = round(trade["t2_shares"] * (live_price - entry), 2)
            trade["status"]     = "T2_HIT"
            trade["alerted_t2"] = True
            trade["realised_pnl"] += gain
            st.session_state.daily_gain_3 = round(st.session_state.daily_gain_3 + gain, 2)
            alert_t2_hit(sym, live_price, r2, trade["t2_shares"])
            continue

        # Priority 4: Target 1
        if trade["status"] == "ACTIVE" and live_price >= r1 and not trade["alerted_t1"]:
            gain = round(trade["t1_shares"] * (live_price - entry), 2)
            trade["status"]     = "T1_HIT"
            trade["alerted_t1"] = True
            trade["realised_pnl"] += gain
            st.session_state.daily_gain_3 = round(st.session_state.daily_gain_3 + gain, 2)
            alert_t1_hit(sym, live_price, r1, trade["t1_shares"], trade["t2_shares"], r2)
            continue


def get_daily_summary_3() -> dict:
    net_pnl       = st.session_state.daily_gain_3 - st.session_state.daily_loss_3
    loss_used_pct = (st.session_state.daily_loss_3 / DAILY_LOSS_LIMIT) * 100
    return {
        "trades_taken":   st.session_state.trades_taken_3,
        "signals_found":  st.session_state.signals_found_3,
        "daily_gain":     st.session_state.daily_gain_3,
        "daily_loss":     st.session_state.daily_loss_3,
        "net_pnl":        round(net_pnl, 2),
        "loss_used_pct":  round(loss_used_pct, 1),
        "system_halted":  st.session_state.system_halted_3,
    }


def get_tracker_rows_3() -> list[dict]:
    rows = []
    for sym, t in st.session_state.active_trades_3.items():
        live  = t.get("live_price", t["entry"])
        entry = t["entry"]
        pnl   = round((live - entry) / entry * 100, 2)

        if t["status"] == "ACTIVE":
            pnl_val = round(t["shares"] * (live - entry), 2)
        elif t["status"] == "T1_HIT":
            floating = round(t["t2_shares"] * (live - entry), 2)
            pnl_val  = round(t["realised_pnl"] + floating, 2)
        else:
            pnl_val = round(t["realised_pnl"], 2)

        rows.append({
            "Symbol":     sym,
            "Strategy":   t.get("strategy", ""),
            "Status":     t["status"],
            "Entry":      f"Rs {entry:.2f}",
            "Live Price": f"Rs {live:.2f}",
            "Change":     f"{pnl:+.2f}%",
            "Stop":       f"Rs {t['stop_loss']:.2f}",
            "T1 (R1)":    f"Rs {t['R1']:.2f}",
            "T2 (R2)":    f"Rs {t['R2']:.2f}",
            "Shares":     t["shares"],
            "Unrealised": f"Rs {pnl_val:+,.0f}",
        })
    return rows

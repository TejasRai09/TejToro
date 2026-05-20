"""Intraday trading scanner implementing 4 strategies using 10-min candles."""

import math
import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from data_fetcher import get_10min_candles
from indicators import prepare_indicators
from config import (
    MIN_STOCK_PRICE,
    MAX_STOCK_PRICE,
    MIN_MARKET_CAP_CR,
    MAX_RISK_PER_TRADE,
    MAX_TRADE_VALUE,
    T1_EXIT_PCT,
    MIN_RR_RATIO,
)

IST = ZoneInfo("Asia/Kolkata")


def _size_position(close, stop_loss, R1, R2):
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
    max_loss = round(shares * stop_dist, 2)
    max_gain = round(t1_shares * (R1 - close) + t2_shares * (R2 - close), 2)
    if max_gain <= 0:
        return None

    rr_ratio = round(max_gain / max_loss, 2)
    if rr_ratio < MIN_RR_RATIO:
        return None

    return {
        "stop_loss": round(stop_loss, 2),
        "shares": shares,
        "t1_shares": t1_shares,
        "t2_shares": t2_shares,
        "trade_value": trade_value,
        "max_loss": max_loss,
        "max_gain": max_gain,
        "rr_ratio": rr_ratio,
    }


def _build_signal(symbol, instrument_key, market_cap_cr, close, pivots, pos, strategy, curr_candle, extra=None):
    signal = {
        "symbol": symbol,
        "instrument_key": instrument_key,
        "entry": round(close, 2),
        "pp": pivots["PP"],
        "R1": pivots["R1"],
        "R2": pivots["R2"],
        "vwap": round(curr_candle["vwap"], 2),
        "market_cap_cr": market_cap_cr,
        "signal_time": datetime.datetime.now(IST).strftime("%H:%M:%S"),
        "strategy": strategy,
    }
    signal.update(pos)
    if extra is not None:
        signal.update(extra)
    return signal


def _check_vwap_reclaim(today_df, close, R1, R2, symbol, instrument_key, market_cap_cr, pivots):
    if len(today_df) < 2:
        return None

    curr = today_df.iloc[-1]
    prev = today_df.iloc[-2]

    if not (prev["close"] < prev["vwap"] and curr["close"] > curr["vwap"]):
        return None

    prior_vols = today_df["volume"].iloc[:-1]
    if len(prior_vols) < 3:
        return None
    vol_avg = prior_vols.mean()
    if curr["volume"] < 1.5 * vol_avg:
        return None

    if close <= pivots["PP"]:
        return None

    stop_loss = round(curr["vwap"] * 0.995, 2)
    pos = _size_position(close, stop_loss, R1, R2)
    if pos is None:
        return None

    vol_ratio = round(curr["volume"] / vol_avg, 2)
    return _build_signal(symbol, instrument_key, market_cap_cr, close, pivots, pos, "VWAP Reclaim", curr, extra={"vol_ratio": vol_ratio})


def _check_ema_pullback(today_df, close, R1, R2, symbol, instrument_key, market_cap_cr, pivots):
    if len(today_df) < 5:
        return None
    if "ema9" not in today_df.columns or "ema21" not in today_df.columns:
        return None

    curr = today_df.iloc[-1]
    curr_ema9 = today_df["ema9"].iloc[-1]
    curr_ema21 = today_df["ema21"].iloc[-1]

    if pd.isna(curr_ema9) or pd.isna(curr_ema21):
        return None

    if curr_ema9 <= curr_ema21:
        return None

    if len(today_df) >= 4:
        if today_df["ema21"].iloc[-1] <= today_df["ema21"].iloc[-4]:
            return None

    pulled_back = False
    for low, ema9_val in zip(today_df["low"].iloc[-4:-1].values, today_df["ema9"].iloc[-4:-1].values):
        if low <= ema9_val * 1.015:
            pulled_back = True
            break
    if not pulled_back:
        return None

    if close <= curr_ema9:
        return None
    if close <= curr["vwap"]:
        return None

    stop_loss = round(today_df["low"].iloc[-4:].min() * 0.999, 2)
    pos = _size_position(close, stop_loss, R1, R2)
    if pos is None:
        return None

    return _build_signal(symbol, instrument_key, market_cap_cr, close, pivots, pos, "EMA Pullback", curr, extra={"ema9": round(curr_ema9, 2), "ema21": round(curr_ema21, 2)})


def _check_volume_breakout(today_df, close, R1, R2, symbol, instrument_key, market_cap_cr, pivots):
    if len(today_df) < 11:
        return None

    prev_10_high = today_df["high"].iloc[-11:-1].max()

    if close <= prev_10_high:
        return None

    prior_vols = today_df["volume"].iloc[:-1]
    if len(prior_vols) < 3:
        return None
    vol_avg = prior_vols.mean()

    curr = today_df.iloc[-1]
    if curr["volume"] < 2.0 * vol_avg:
        return None

    if close <= curr["vwap"]:
        return None

    stop_loss = round(prev_10_high * 0.998, 2)
    pos = _size_position(close, stop_loss, R1, R2)
    if pos is None:
        return None

    vol_ratio = round(curr["volume"] / vol_avg, 2)
    return _build_signal(symbol, instrument_key, market_cap_cr, close, pivots, pos, "Vol Breakout", curr, extra={"breakout_level": round(prev_10_high, 2), "vol_ratio": vol_ratio})


def _check_rsi_reversal(today_df, close, R1, R2, symbol, instrument_key, market_cap_cr, pivots):
    if len(today_df) < 3:
        return None

    rsi_now = today_df["rsi"].iloc[-1]
    rsi_prev = today_df["rsi"].iloc[-2]
    rsi_prev2 = today_df["rsi"].iloc[-3]

    if pd.isna(rsi_now) or pd.isna(rsi_prev) or pd.isna(rsi_prev2):
        return None

    if not (rsi_prev2 < 40 and rsi_prev < 40):
        return None
    if rsi_now < 40:
        return None
    if rsi_now <= rsi_prev:
        return None

    curr = today_df.iloc[-1]
    if close <= curr["vwap"]:
        return None

    stop_loss = round(today_df["low"].iloc[-3:].min() * 0.998, 2)
    pos = _size_position(close, stop_loss, R1, R2)
    if pos is None:
        return None

    return _build_signal(symbol, instrument_key, market_cap_cr, close, pivots, pos, "RSI Reversal", curr, extra={"rsi": round(rsi_now, 1), "rsi_prev": round(rsi_prev, 1)})


def evaluate_stock_v3(symbol, instrument_key, market_cap_cr):
    if market_cap_cr < MIN_MARKET_CAP_CR:
        return None

    try:
        df_raw = get_10min_candles(instrument_key, days_back=3)
    except Exception:
        return None

    if df_raw is None or len(df_raw) < 30:
        return None

    today_df, pivots = prepare_indicators(df_raw)

    if today_df is None or today_df.empty:
        return None
    for key in ("PP", "R1", "R2", "S1"):
        if key not in pivots:
            return None

    close = today_df["close"].iloc[-1]
    if not (MIN_STOCK_PRICE <= close <= MAX_STOCK_PRICE):
        return None

    R1 = pivots["R1"]
    R2 = pivots["R2"]

    if R1 <= close or R2 <= R1:
        return None

    ema9 = df_raw["close"].ewm(span=9, adjust=False).mean()
    ema21 = df_raw["close"].ewm(span=21, adjust=False).mean()

    current_date = df_raw.index[-1].date()
    today_df["ema9"] = ema9[df_raw.index.date == current_date]
    today_df["ema21"] = ema21[df_raw.index.date == current_date]

    result = _check_vwap_reclaim(today_df, close, R1, R2, symbol, instrument_key, market_cap_cr, pivots)
    if result is not None:
        return result

    result = _check_ema_pullback(today_df, close, R1, R2, symbol, instrument_key, market_cap_cr, pivots)
    if result is not None:
        return result

    result = _check_volume_breakout(today_df, close, R1, R2, symbol, instrument_key, market_cap_cr, pivots)
    if result is not None:
        return result

    result = _check_rsi_reversal(today_df, close, R1, R2, symbol, instrument_key, market_cap_cr, pivots)
    if result is not None:
        return result

    return None


def run_scanner_v3(instruments: pd.DataFrame):
    total = len(instruments)
    yield (0, total, "scan", None)

    for i, row in enumerate(instruments.itertuples(index=False)):
        result = evaluate_stock_v3(row.symbol, row.instrument_key, row.market_cap_cr)
        yield (i + 1, total, "scan", result)

    yield (total, total, "scan", "DONE")

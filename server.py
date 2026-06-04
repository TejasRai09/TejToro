"""
server.py — FastAPI backend for VWAP Convergence Scanner
Run: uvicorn server:app --reload --port 8000
"""
import csv
import time
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from instruments import load_instruments
from data_fetcher import get_10min_candles, get_market_quotes
from indicators import calculate_vwap, calculate_supertrend, calculate_pivots
IST              = ZoneInfo("Asia/Kolkata")
MIN_MCAP_CR      = 1000
TRADE_CAPITAL    = 200_000
LOG_DIR          = Path(__file__).parent / "logs"
SIGNAL_CUTOFF    = "10:15"  # only log signals within opening window

app = FastAPI(title="VWAP Scanner API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory state ───────────────────────────────────────────────────────────
state = {
    "results":        [],
    "scan_time":      None,
    "scanning":       False,
    "scan_progress":  0,
    "scan_total":     0,
    "alerted_syms":   set(),
    "target_alerted": set(),
    "sl_alerted":     set(),
    "last_sig_check": 0.0,
}

_instruments_df   = load_instruments()
_instruments_1000 = (
    _instruments_df[_instruments_df["market_cap_cr"] >= MIN_MCAP_CR]
    .reset_index(drop=True)
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _strip_tz(dt):
    return dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) else dt


def _is_market_open():
    now = datetime.now(IST)
    return (
        now.weekday() < 5
        and now.replace(hour=9, minute=15, second=0, microsecond=0)
        <= now
        <= now.replace(hour=15, minute=30, second=0, microsecond=0)
    )


_LOG_FIELDS = [
    "date", "signal_time", "symbol", "event", "pattern",
    "entry", "sl", "target", "risk", "reward",
    "confidence", "mcap", "touch_time", "entry_time",
    "candles_below", "retest_candles", "atr",
    "ltp_at_event", "st_vwap_gap_pct", "vwap_pp_gap_pct",
]

def _log_event(event: str, r: dict, ltp: float = None):
    """Write one row to logs/signals_YYYY-MM-DD.csv. Only during market hours, only opening-window signals."""
    if not _is_market_open():
        return
    sig = r.get("entry_signal")
    if not sig:
        return
    if sig.get("entry_time", "") > SIGNAL_CUTOFF:
        return
    LOG_DIR.mkdir(exist_ok=True)
    today    = datetime.now(IST).strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"signals_{today}.csv"
    row = {
        "date":           today,
        "signal_time":    datetime.now(IST).strftime("%H:%M:%S"),
        "symbol":         r.get("symbol", ""),
        "event":          event,
        "pattern":        sig.get("pattern", ""),
        "entry":          sig.get("entry", ""),
        "sl":             sig.get("sl", ""),
        "target":         sig.get("target", ""),
        "risk":           sig.get("risk", ""),
        "reward":         sig.get("reward", ""),
        "confidence":     r.get("confidence", ""),
        "mcap":           r.get("mcap", ""),
        "touch_time":     sig.get("touch_time", ""),
        "entry_time":     sig.get("entry_time", ""),
        "candles_below":  sig.get("candles_below", ""),
        "retest_candles": sig.get("retest_candles", ""),
        "atr":            sig.get("atr", ""),
        "ltp_at_event":   ltp if ltp is not None else sig.get("entry", ""),
        "st_vwap_gap_pct": r.get("st_vwap_gap_pct", ""),
        "vwap_pp_gap_pct": r.get("vwap_pp_gap_pct", ""),
    }
    write_header = not log_file.exists()
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_LOG_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def get_candles_for_chartink(instrument_key: str):
    try:
        df_raw = get_10min_candles(instrument_key, days_back=3)
    except Exception:
        return None, None

    if df_raw.empty or len(df_raw) < 12:
        return None, None
    if not isinstance(df_raw.index, pd.DatetimeIndex):
        df_raw.index = pd.to_datetime(df_raw.index)

    today    = df_raw.index[-1].date()
    today_df = df_raw[df_raw.index.date == today].copy()
    prev_df  = df_raw[df_raw.index.date < today].copy()
    if today_df.empty or prev_df.empty:
        return None, None

    now_naive  = _strip_tz(datetime.now(IST))
    last_label = _strip_tz(today_df.index[-1].to_pydatetime())
    if now_naive < last_label + timedelta(minutes=10):
        today_df = today_df.iloc[:-1]
    if len(today_df) < 3:
        return None, None

    pivots = calculate_pivots(prev_df)
    if pivots.get("PP") is None:
        return None, None

    vwap_s = calculate_vwap(df_raw)
    st_s   = calculate_supertrend(df_raw, period=6, multiplier=2)
    today_df["vwap"] = vwap_s[today_df.index]
    today_df["st"]   = st_s[today_df.index]
    today_df = today_df.dropna(subset=["vwap", "st"])
    if len(today_df) < 3:
        return None, None

    return today_df, pivots


def check_filters(today_df, pivots):
    c0, c1, c2 = today_df.iloc[-1], today_df.iloc[-2], today_df.iloc[-3]
    PP    = pivots["PP"]
    close = c0["close"]; vwap = c0["vwap"]; st = c0["st"]
    if abs(st - vwap)  >= close * 0.01: return None
    if abs(vwap - PP)  >= close * 0.01: return None
    if close < st or close < PP or close < vwap: return None
    if c1["close"] < c1["vwap"]: return None
    if c2["close"] < c2["vwap"]: return None
    return {
        "st_vwap_gap_pct": round(abs(st - vwap) / close * 100, 2),
        "vwap_pp_gap_pct": round(abs(vwap - PP)  / close * 100, 2),
        "c0_time":  c0.name.strftime("%H:%M"),
        "c0_close": round(close, 2),
        "c0_vwap":  round(vwap, 2),
        "c0_st":    round(st, 2),
        "c1_time":  c1.name.strftime("%H:%M"),
        "c1_close": round(c1["close"], 2),
        "c1_vwap":  round(c1["vwap"], 2),
        "c2_time":  c2.name.strftime("%H:%M"),
        "c2_close": round(c2["close"], 2),
        "c2_vwap":  round(c2["vwap"], 2),
        "pp":       round(PP, 2),
    }


def _calc_atr(today_df, n=10):
    if len(today_df) < 2:
        return today_df["close"].iloc[-1] * 0.005
    prev_close = today_df["close"].shift(1)
    tr = pd.concat([
        today_df["high"] - today_df["low"],
        (today_df["high"] - prev_close).abs(),
        (today_df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.iloc[-n:].mean())


def _avg_volume(df, n=20):
    """20-bar average volume, excluding the current (last) bar."""
    if "volume" not in df.columns or len(df) < 2:
        return 0.0
    vols = df["volume"].iloc[max(0, len(df) - n - 1):-1]
    vols = vols[vols > 0]
    return float(vols.mean()) if len(vols) > 0 else 0.0


def _calc_vwap_sigma(today_df):
    """Cumulative volume-weighted VWAP standard deviation (sigma) per bar in today's session."""
    if len(today_df) < 3 or "volume" not in today_df.columns:
        return None
    tp        = (today_df["high"] + today_df["low"] + today_df["close"]) / 3
    vol       = today_df["volume"].clip(lower=0)
    cum_vol   = vol.cumsum().replace(0, np.nan)
    vwap_cv   = (tp * vol).cumsum() / cum_vol
    var_cv    = (tp ** 2 * vol).cumsum() / cum_vol - vwap_cv ** 2
    sigma     = var_cv.clip(lower=0).apply(np.sqrt).fillna(0.0)
    return sigma


def _sig(pattern, ref_candle, entry_candle, extra=None):
    entry = entry_candle["close"]
    sl    = entry_candle["vwap"]
    risk  = entry - sl
    if risk <= 0: return None
    d = {
        "pattern":    pattern,
        "touch_time": ref_candle.name.strftime("%H:%M"),
        "touch_low":  round(ref_candle["low"],  2),
        "touch_high": round(ref_candle["high"], 2),
        "touch_vwap": round(ref_candle["vwap"], 2),
        "entry_time": entry_candle.name.strftime("%H:%M"),
        "entry":      round(entry, 2),
        "sl":         round(sl,    2),
        "target":     round(entry + 3 * risk, 2),
        "risk":       round(risk,       2),
        "reward":     round(3 * risk,   2),
    }
    if extra: d.update(extra)
    return d


def _pattern_b(today_df):
    """1–3 consecutive candles close below VWAP, then reclaim above VWAP."""
    if len(today_df) < 3: return None
    last = today_df.iloc[-1]
    if last["close"] <= last["vwap"]: return None
    if last["close"] <= last["open"]: return None  # reclaim candle must be green
    if (last["open"] + last["close"]) / 2 <= last["vwap"]: return None  # majority of body must be above VWAP

    n_below = 0; max_dip_pct = 0.0; first_breach_idx = None
    for i in range(len(today_df) - 2, max(len(today_df) - 5, -1), -1):
        c = today_df.iloc[i]
        if c["close"] < c["vwap"]:
            n_below += 1
            dip = (c["vwap"] - c["close"]) / c["vwap"]
            if dip > max_dip_pct: max_dip_pct = dip
            first_breach_idx = i  # walks back — ends at chronologically first breach candle
        else:
            break

    if not (1 <= n_below <= 3): return None
    if max_dip_pct < 0.0015: return None  # close must be >= 0.15% below VWAP (not noise)

    # First breach candle must have opened >= 0.15% above VWAP — stock was genuinely above it
    first_breach = today_df.iloc[first_breach_idx]
    if (first_breach["open"] - first_breach["vwap"]) / first_breach["vwap"] < 0.0015: return None

    before_idx = len(today_df) - 2 - n_below
    if before_idx < 0: return None
    if today_df.iloc[before_idx]["close"] <= today_df.iloc[before_idx]["vwap"]: return None

    breach_candle = today_df.iloc[len(today_df) - 1 - n_below]
    return _sig("B", breach_candle, last, {"candles_below": n_below})


def _pattern_c(today_df):
    """Breakout Retest — DISABLED: 13% WR, -₹5,045, 6/8 SL hits. Retest candles often fail, not bounce."""
    return None
    if len(today_df) < 4: return None
    atr  = _calc_atr(today_df)
    last = today_df.iloc[-1]

    if last["close"] - last["vwap"] <= atr: return None

    n_retest          = 0
    initial_break_idx = None
    for i in range(len(today_df) - 2, 0, -1):
        c    = today_df.iloc[i]
        dist = abs(c["close"] - c["vwap"])
        if dist <= atr:
            n_retest += 1
        else:
            prev = today_df.iloc[i - 1]
            if prev["close"] < prev["vwap"] and c["close"] > c["vwap"]:
                initial_break_idx = i
            break

    if n_retest < 1 or initial_break_idx is None: return None

    init_candle = today_df.iloc[initial_break_idx]
    return _sig("C", init_candle, last, {"retest_candles": n_retest, "atr": round(atr, 2)})


def _pattern_eng(today_df):
    """Bullish Engulfing at VWAP: red wick into VWAP, next green body engulfs red body, closes above VWAP. Vol ≥1.5×."""
    if len(today_df) < 3:
        return None
    last = today_df.iloc[-1]   # engulfing candle
    prev = today_df.iloc[-2]   # red dip candle

    if last["close"] <= last["open"]:  return None  # must be green
    if last["close"] <= last["vwap"]:  return None  # must close above VWAP
    if prev["close"] >= prev["open"]:  return None  # prev must be red
    if prev["low"]   >  prev["vwap"]:  return None  # prev wick must touch VWAP
    if prev["open"]  <  prev["vwap"]:  return None  # prev must have opened above VWAP

    # Engulfing condition: current body contains entire previous body
    if last["open"]  > prev["close"]: return None
    if last["close"] < prev["open"]:  return None

    # Stock must have been above VWAP before the dip
    if today_df.iloc[-3]["close"] <= today_df.iloc[-3]["vwap"]: return None

    avg_vol = _avg_volume(today_df)
    if avg_vol > 0 and today_df["volume"].iloc[-1] < 1.5 * avg_vol: return None

    dip_pct = round((prev["vwap"] - prev["low"]) / prev["vwap"] * 100, 3)
    return _sig("ENG", prev, last, {"dip_pct": dip_pct})


def _pattern_ham(today_df):
    """Hammer / Pin Bar at VWAP: lower wick ≥2× body pierces VWAP, closes above. Vol ≥ avg."""
    if len(today_df) < 3:
        return None
    last = today_df.iloc[-1]

    if last["close"] <= last["vwap"]: return None  # must close above VWAP

    body       = abs(last["close"] - last["open"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    upper_wick = last["high"] - max(last["open"], last["close"])

    if body < last["close"] * 0.0005: return None  # body must exist (not pure doji)
    if lower_wick < 2.0 * body:       return None  # lower wick ≥ 2× body
    if last["low"] > last["vwap"]:    return None  # wick must pierce VWAP
    if upper_wick > body:             return None  # small upper wick (genuine hammer shape)

    # Previous 2 candles must be above VWAP (stock was above before wick dip)
    if today_df.iloc[-2]["close"] <= today_df.iloc[-2]["vwap"]: return None
    if today_df.iloc[-3]["close"] <= today_df.iloc[-3]["vwap"]: return None

    avg_vol = _avg_volume(today_df)
    if avg_vol > 0 and today_df["volume"].iloc[-1] < avg_vol: return None

    dip_pct = round(lower_wick / last["vwap"] * 100, 3)
    return _sig("HAM", last, last, {"dip_pct": dip_pct})


def _pattern_mar(today_df):
    """Bullish Marubozu VWAP Reclaim: near-wickless candle opens below, closes well above VWAP. Vol ≥2×."""
    if len(today_df) < 2:
        return None
    last = today_df.iloc[-1]

    if last["close"] <= last["open"]: return None  # must be green
    if last["open"]  >= last["vwap"]: return None  # open must be below VWAP
    if last["close"] <= last["vwap"]: return None  # close must be above VWAP

    # Close must be well above VWAP (≥0.2%)
    if (last["close"] - last["vwap"]) / last["vwap"] < 0.002: return None

    body       = last["close"] - last["open"]
    upper_wick = last["high"]  - last["close"]
    lower_wick = last["open"]  - last["low"]
    if body <= 0: return None
    if upper_wick > 0.25 * body: return None  # near-wickless
    if lower_wick > 0.25 * body: return None

    # Previous candle must be below VWAP (genuine crossover, not continuation)
    if today_df.iloc[-2]["close"] >= today_df.iloc[-2]["vwap"]: return None

    avg_vol = _avg_volume(today_df)
    if avg_vol <= 0: return None  # volume data required
    if today_df["volume"].iloc[-1] < 3.0 * avg_vol: return None  # raised from 2× to 3×

    # Minimum risk 0.3% to avoid near-zero risk trades
    test_entry = last["close"]
    test_sl    = last["vwap"]
    if (test_entry - test_sl) / test_entry < 0.003: return None

    dip_pct = round((last["vwap"] - last["open"]) / last["vwap"] * 100, 3)
    return _sig("MAR", today_df.iloc[-2], last, {"dip_pct": dip_pct})


def _pattern_star(today_df):
    """Morning Star at VWAP — DISABLED: fires too frequently (80 signals/day, 13% WR). Needs redesign."""
    return None
    if len(today_df) < 4:
        return None
    c3 = today_df.iloc[-1]  # green confirmation candle
    c2 = today_df.iloc[-2]  # doji / spinning top at VWAP
    c1 = today_df.iloc[-3]  # red candle near VWAP
    c0 = today_df.iloc[-4]  # candle before star — must be above VWAP

    if c3["close"] <= c3["open"]: return None  # c3 must be green
    if c3["close"] <= c3["vwap"]: return None  # c3 must close above VWAP
    if c1["close"] >= c1["open"]: return None  # c1 must be red

    # c1 closes near VWAP (within 0.5%)
    if abs(c1["close"] - c1["vwap"]) / c1["vwap"] > 0.005: return None

    # c2 is a small-body indecision candle (≤50% of c1 body)
    c1_body = abs(c1["open"] - c1["close"])
    c2_body = abs(c2["open"] - c2["close"])
    if c1_body <= 0: return None
    if c2_body > 0.5 * c1_body: return None

    # c2 midpoint within 0.5% of VWAP
    if abs((c2["open"] + c2["close"]) / 2 - c2["vwap"]) / c2["vwap"] > 0.005: return None

    # c3 must close above midpoint of c1 (confirmation strength)
    if c3["close"] < (c1["open"] + c1["close"]) / 2: return None

    # Stock was above VWAP before the star pattern (pullback, not breakout)
    if c0["close"] <= c0["vwap"]: return None

    # Expanding volume: c3 > c1
    if "volume" in today_df.columns and c3["volume"] <= c1["volume"]: return None

    return _sig("STAR", c1, c3, {})


def _pattern_ham2s(today_df):
    """Hammer at −2σ VWAP band — mean reversion BUY on range days only."""
    if len(today_df) < 5:
        return None
    sigma = _calc_vwap_sigma(today_df)
    if sigma is None:
        return None

    last     = today_df.iloc[-1]
    vwap     = last["vwap"]
    sig_val  = float(sigma.iloc[-1])
    if sig_val <= 0:
        return None

    lower_2s = vwap - 2.0 * sig_val

    # Range day filter: VWAP must be flat (moved <0.15% over last 5 bars)
    vwap_slice = today_df["vwap"].iloc[-5:]
    if (vwap_slice.max() - vwap_slice.min()) / vwap > 0.0015:
        return None

    if last["low"] > lower_2s:         return None  # wick must pierce −2σ

    # EOD filter: no signals after 14:45 (market closes too soon for trade to resolve)
    if last.name.strftime("%H:%M") > "14:45":
        return None

    body       = abs(last["close"] - last["open"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    upper_wick = last["high"] - max(last["open"], last["close"])

    if body       < last["close"] * 0.0003: return None  # body must exist
    if lower_wick < 2.0 * body:             return None  # long lower wick
    if last["close"] < lower_2s:            return None  # must close above −2σ
    if upper_wick > body:                   return None  # small upper wick

    avg_vol = _avg_volume(today_df)
    if avg_vol > 0 and last["volume"] < 1.5 * avg_vol:
        return None

    entry  = round(last["close"], 2)
    sl     = round(last["low"] - 0.01, 2)
    risk   = round(entry - sl, 2)
    if risk <= 0 or risk / entry < 0.001:
        return None
    target  = round(entry + 3.0 * risk, 2)
    dip_pct = round((vwap - last["low"]) / vwap * 100, 3)

    return {
        "pattern":    "HAM2S",
        "touch_time": last.name.strftime("%H:%M"),
        "touch_low":  round(last["low"],  2),
        "touch_high": round(last["high"], 2),
        "touch_vwap": round(lower_2s,     2),
        "entry_time": last.name.strftime("%H:%M"),
        "entry":      entry,
        "sl":         sl,
        "target":     target,
        "risk":       risk,
        "reward":     round(3.0 * risk, 2),
        "dip_pct":    dip_pct,
    }


def _pattern_bw(today_df):
    """Band Walk at +1σ — DISABLED: 32 signals/day, 3% WR, -₹6,253. Fires on every rising stock. Needs redesign."""
    return None
    if len(today_df) < 7:
        return None
    sigma = _calc_vwap_sigma(today_df)
    if sigma is None:
        return None

    last     = today_df.iloc[-1]
    vwap     = last["vwap"]
    sig_val  = float(sigma.iloc[-1])
    if sig_val <= 0:
        return None

    upper_1s = vwap + sig_val

    # Trend day: VWAP must have risen ≥0.1% over last 6 bars
    vwap_6ago = today_df["vwap"].iloc[-7]
    if vwap < vwap_6ago * 1.001:
        return None

    # Band walk in progress: ≥2 of last 4 prior candles closed above +1σ
    walk_count = 0
    for i in range(-5, -1):
        c   = today_df.iloc[i]
        s_i = float(sigma.iloc[i])
        if c["close"] > c["vwap"] + s_i:
            walk_count += 1
    if walk_count < 2:
        return None

    # Current candle: low touches +1σ, closes above +1σ
    if last["low"]   > upper_1s: return None  # didn't touch +1σ
    if last["close"] < upper_1s: return None  # closed below (breakdown)

    body         = abs(last["close"] - last["open"])
    lower_wick   = min(last["open"], last["close"]) - last["low"]
    candle_range = last["high"] - last["low"]
    is_hammer    = body > 0 and lower_wick >= 2.0 * body
    is_doji      = candle_range > 0 and body <= 0.25 * candle_range
    if not (is_hammer or is_doji):
        return None

    avg_vol = _avg_volume(today_df)
    if avg_vol > 0 and last["volume"] < avg_vol:
        return None

    dip_pct = round((upper_1s - last["low"]) / upper_1s * 100, 3)
    return _sig("BW", last, last, {"dip_pct": dip_pct})


def _pattern_sqz(today_df):
    """Squeeze Breakout — DISABLED: 0% WR, 21 signals, -₹22,424. Sigma squeeze too loose, not detecting real squeezes."""
    return None
    if len(today_df) < 8:
        return None
    sigma = _calc_vwap_sigma(today_df)
    if sigma is None:
        return None

    last    = today_df.iloc[-1]
    vwap    = last["vwap"]
    sig_now = float(sigma.iloc[-1])
    if sig_now <= 0:
        return None

    upper_1s = vwap + sig_now

    # Breakout: current candle closes above +1σ and is green
    if last["close"] <= upper_1s:        return None
    if last["close"] <= last["open"]:    return None

    # Look back 4-7 bars: find prior squeeze (bands contracting and tight)
    lookback = min(7, len(today_df) - 1)
    sig_prev = [float(sigma.iloc[-i]) for i in range(2, lookback + 2)]
    if len(sig_prev) < 4:
        return None

    sig_min = min(sig_prev)

    # Bands must have been tight during squeeze: min sigma < 0.4% of VWAP
    if sig_min / vwap > 0.004:
        return None
    # Current expansion: sigma now ≥20% wider than squeeze minimum
    if sig_now < sig_min * 1.2:
        return None

    # Coiling: ≥60% of lookback bars had close within ±1σ of VWAP
    coil_count = 0
    for i in range(-lookback - 1, -1):
        c   = today_df.iloc[i]
        s_i = float(sigma.iloc[i])
        if abs(c["close"] - c["vwap"]) <= s_i:
            coil_count += 1
    if coil_count < int(lookback * 0.6):
        return None

    # Volume spike vs squeeze average
    squeeze_vol_avg = today_df["volume"].iloc[-lookback - 1:-1].mean()
    if squeeze_vol_avg > 0 and last["volume"] < 1.5 * squeeze_vol_avg:
        return None

    return _sig("SQZ", last, last, {"band_sigma": round(sig_now, 2)})


def find_entry(today_df):
    return (
        _pattern_b(today_df)     or
        _pattern_c(today_df)     or
        _pattern_eng(today_df)   or
        _pattern_ham(today_df)   or
        _pattern_mar(today_df)   or
        _pattern_star(today_df)  or
        _pattern_ham2s(today_df) or
        _pattern_bw(today_df)    or
        _pattern_sqz(today_df)
    )


def compute_confidence(r):
    sig = r.get("entry_signal")
    if not sig: return 0
    c1 = max(0.0, 30.0 * (1.0 - r["st_vwap_gap_pct"]))
    c2 = max(0.0, 30.0 * (1.0 - r["vwap_pp_gap_pct"]))
    sl = (sig["touch_vwap"] - sig["touch_low"]) / sig["touch_vwap"] * 100
    ts = max(0.0, 25.0 * (1.0 - sl))
    mc = r["mcap"]
    ms = 15 if mc >= 100_000 else 12 if mc >= 50_000 else 9 if mc >= 20_000 else 6 if mc >= 5_000 else 3
    return min(100, round(c1 + c2 + ts + ms))


def _evaluate(row):
    today_df, pivots = get_candles_for_chartink(row["instrument_key"])
    if today_df is None: return None
    result = check_filters(today_df, pivots)
    if result is None: return None
    entry_signal = find_entry(today_df)
    r = {
        "symbol":         row["symbol"],
        "instrument_key": row["instrument_key"],
        "mcap":           round(row["market_cap_cr"], 0),
        "entry_signal":   entry_signal,
        **result,
    }
    r["confidence"] = compute_confidence(r)
    return r


def _run_scan(merge=False):
    rows = [
        {"symbol": r.symbol, "instrument_key": r.instrument_key, "market_cap_cr": r.market_cap_cr}
        for r in _instruments_1000.itertuples(index=False)
    ]
    done = 0
    new_results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_evaluate, row): row["symbol"] for row in rows}
        for future in as_completed(futures):
            done += 1
            state["scan_progress"] = done
            res = future.result()
            if res:
                new_results.append(res)

    if merge:
        # Keep all existing stocks; add new ones; upgrade watching→signal if pattern now fires
        existing = {r["symbol"]: i for i, r in enumerate(state["results"])}
        for res in new_results:
            sym = res["symbol"]
            if sym not in existing:
                state["results"].append(res)
                existing[sym] = len(state["results"]) - 1
            else:
                idx = existing[sym]
                old = state["results"][idx]
                if not old.get("entry_signal") and res.get("entry_signal"):
                    state["results"][idx] = res  # upgrade to signal
        state["scan_time"] = datetime.now(IST).strftime("%H:%M:%S")
    else:
        state["results"]   = new_results
        state["scan_time"] = datetime.now(IST).strftime("%H:%M:%S")

    state["scanning"]       = False
    state["last_sig_check"] = time.time()


def _auto_scan_loop():
    """Runs every 10 minutes during market hours. Full chartink scan every cycle — new stocks added throughout the day."""
    time.sleep(3)  # let uvicorn fully start
    first = True
    while True:
        if _is_market_open() and not state["scanning"]:
            state["scanning"]      = True
            state["scan_progress"] = 0
            state["scan_total"]    = len(_instruments_1000)
            if first:
                state["results"]      = []
                state["alerted_syms"] = set()
                first = False
            _run_scan(merge=True)
            print(f"[AUTO] Scan done at {state['scan_time']} — {len(state['results'])} stocks in watchlist")

        time.sleep(600)  # 10 minutes


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    threading.Thread(target=_auto_scan_loop, daemon=True).start()


@app.get("/api/status")
def get_status():
    return {
        "universe":      len(_instruments_1000),
        "scan_time":     state["scan_time"],
        "result_count":  len(state["results"]),
        "signal_count":  sum(1 for r in state["results"] if r.get("entry_signal")),
        "scanning":      state["scanning"],
        "scan_progress": state["scan_progress"],
        "scan_total":    state["scan_total"],
        "market_open":   _is_market_open(),
        "server_time":   datetime.now(IST).strftime("%H:%M:%S"),
    }


@app.get("/api/results")
def get_results():
    return {"results": state["results"], "scan_time": state["scan_time"]}


@app.post("/api/scan/start")
async def start_scan():
    if state["scanning"]:
        return {"status": "already_scanning"}
    state["scanning"]      = True
    state["results"]       = []
    state["scan_progress"] = 0
    state["scan_total"]    = len(_instruments_1000)
    state["alerted_syms"]  = set()
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_scan, False)  # manual = fresh scan
    return {"status": "started", "total": state["scan_total"]}


@app.post("/api/clear")
def clear_results():
    state.update({
        "results": [], "scan_time": None,
        "alerted_syms": set(), "target_alerted": set(),
        "sl_alerted": set(), "last_sig_check": 0.0,
    })
    return {"status": "cleared"}


@app.get("/api/live")
def get_live():
    results     = state["results"]
    market_open = _is_market_open()
    price_map   = {}

    if market_open and results:
        keys = [r["instrument_key"] for r in results if r.get("instrument_key")]
        if keys:
            try:
                raw = get_market_quotes(keys)
                for qd in (raw or {}).values():
                    token = qd.get("instrument_token")
                    ltp   = qd.get("last_price")
                    if token and ltp is not None:
                        price_map[token] = float(ltp)
            except Exception as e:
                print(f"[WARN] quotes: {e}")

    now_ts = time.time()
    if (now_ts - state["last_sig_check"]) >= 600 and results and not state["scanning"]:
        updated = []
        for r in results:
            r = r.copy()
            ikey = r.get("instrument_key")
            if ikey:
                try:
                    td, _ = get_candles_for_chartink(ikey)
                    if td is not None and not r.get("entry_signal"):
                        new_sig = find_entry(td)
                        if new_sig:
                            r["entry_signal"] = new_sig
                            r["confidence"]   = compute_confidence(r)
                except Exception:
                    pass
            updated.append(r)
        state["results"]        = updated
        state["last_sig_check"] = now_ts

    # BUY entry alerts — fire once per symbol when entry_signal first appears
    for r in state["results"]:
        if not r.get("entry_signal"): continue
        sym = r["symbol"]
        if sym not in state["alerted_syms"]:
            _log_event("SIGNAL", r)
            print(f"[SIGNAL] {sym} — Pattern {r['entry_signal'].get('pattern','?')} — entry Rs{r['entry_signal'].get('entry')}")
            state["alerted_syms"].add(sym)

    if market_open:
        for r in state["results"]:
            sig = r.get("entry_signal")
            ltp = price_map.get(r.get("instrument_key", ""))
            if not sig or ltp is None: continue
            sym = r["symbol"]
            if ltp >= sig["target"] and sym not in state["target_alerted"]:
                _log_event("TARGET_HIT", r, ltp)
                print(f"[TARGET HIT] {sym} @ Rs{ltp}")
                state["target_alerted"].add(sym)
            elif ltp <= sig["sl"] and sym not in state["sl_alerted"]:
                _log_event("SL_HIT", r, ltp)
                print(f"[SL HIT] {sym} @ Rs{ltp}")
                state["sl_alerted"].add(sym)

    return {
        "prices":      price_map,
        "market_open": market_open,
        "server_time": datetime.now(IST).strftime("%H:%M:%S"),
    }


IST_OFFSET = 5 * 3600 + 30 * 60  # +19800 s — shifts display to IST in Lightweight Charts


@app.get("/api/chart/{instrument_key:path}")
def get_chart(instrument_key: str):
    try:
        df = get_10min_candles(instrument_key, days_back=1)
        if df.empty:
            return {"candles": [], "vwap": []}
        today = df.index[-1].date()
        df    = df[df.index.date == today].copy()
        df["vwap"] = calculate_vwap(df)
        candles, vwap = [], []
        for ts, row in df.iterrows():
            # Add IST offset so Lightweight Charts (UTC display) shows IST times correctly
            t = int(ts.timestamp()) + IST_OFFSET
            candles.append({
                "time": t, "open": float(row["open"]),
                "high": float(row["high"]), "low": float(row["low"]),
                "close": float(row["close"]),
            })
            if not pd.isna(row["vwap"]):
                vwap.append({"time": t, "value": round(float(row["vwap"]), 2)})
        return {"candles": candles, "vwap": vwap}
    except Exception as e:
        return {"candles": [], "vwap": [], "error": str(e)}

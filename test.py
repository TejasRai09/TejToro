"""
test.py — Pattern-only test mode.
Scans all stocks for all 9 VWAP patterns today (B, C, ENG, HAM, MAR, STAR, HAM2S, BW, SQZ),
skips every production filter. Shows simulated P&L per pattern based on what happened after each signal.

Run:  python test.py
Open: http://localhost:5174
"""
import os, sys, time, asyncio, subprocess, threading, webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from instruments import load_instruments
from data_fetcher import get_10min_candles, get_market_quotes
from indicators import calculate_vwap

IST           = ZoneInfo("Asia/Kolkata")
TRADE_CAPITAL = 200_000
MIN_MCAP_CR   = 1000
IST_OFFSET    = 5 * 3600 + 30 * 60
ROOT          = os.path.dirname(os.path.abspath(__file__))
FRONTEND      = os.path.join(ROOT, "frontend")

app = FastAPI(title="TejToro Test Mode")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

state = {
    "results":       [],
    "scan_time":     None,
    "scanning":      False,
    "scan_progress": 0,
    "scan_total":    0,
}

_inst_df  = load_instruments()
_universe = _inst_df[_inst_df["market_cap_cr"] >= MIN_MCAP_CR].reset_index(drop=True)


def _is_market_open():
    now = datetime.now(IST)
    if now.weekday() >= 5: return False
    t = now.hour * 60 + now.minute
    return 555 <= t <= 930  # 9:15 to 15:30


# ── Pattern helpers (identical to server.py + dip_depth_pct) ─────────────────
def _calc_atr(df, n=10):
    if len(df) < 2: return df["close"].iloc[-1] * 0.005
    pc = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"]  - pc).abs(),
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


def _pattern_b(df):
    if len(df) < 3: return None
    last = df.iloc[-1]
    if last["close"] <= last["vwap"]: return None
    if last["close"] <= last["open"]: return None  # reclaim candle must be green
    if (last["open"] + last["close"]) / 2 <= last["vwap"]: return None  # majority of body must be above VWAP

    n_below = 0; max_dip_pct = 0.0; first_breach_idx = None
    for i in range(len(df) - 2, max(len(df) - 5, -1), -1):
        c = df.iloc[i]
        if c["close"] < c["vwap"]:
            n_below += 1
            dip = (c["vwap"] - c["close"]) / c["vwap"]
            if dip > max_dip_pct: max_dip_pct = dip
            first_breach_idx = i  # walks back — ends at chronologically first breach candle
        else:
            break

    if not (1 <= n_below <= 3): return None
    if max_dip_pct < 0.0015: return None  # close must be >= 0.15% below VWAP

    # First breach candle must have opened >= 0.15% above VWAP — stock was genuinely above it
    first_breach = df.iloc[first_breach_idx]
    if (first_breach["open"] - first_breach["vwap"]) / first_breach["vwap"] < 0.0015: return None

    entry = last["close"]; sl = last["vwap"]; risk = entry - sl
    if risk / entry < 0.003: return None  # need >= 0.3% risk

    before_idx = len(df) - 2 - n_below
    if before_idx < 0: return None
    if df.iloc[before_idx]["close"] <= df.iloc[before_idx]["vwap"]: return None

    breach = df.iloc[len(df) - 1 - n_below]
    return _sig("B", breach, last, {"candles_below": n_below, "dip_pct": round(max_dip_pct * 100, 3)})


def _pattern_c(df):
    """Breakout Retest — DISABLED: 13% WR, -₹5,045, 6/8 SL hits. Retest candles often fail, not bounce."""
    return None
    if len(df) < 4: return None
    atr  = _calc_atr(df)
    last = df.iloc[-1]
    if last["close"] - last["vwap"] <= atr: return None

    n_retest = 0; ib_idx = None
    for i in range(len(df) - 2, 0, -1):
        c = df.iloc[i]; dist = abs(c["close"] - c["vwap"])
        if dist <= atr:
            n_retest += 1
        else:
            prev = df.iloc[i - 1]
            if prev["close"] < prev["vwap"] and c["close"] > c["vwap"]:
                ib_idx = i
            break

    if n_retest < 1 or ib_idx is None: return None
    ic = df.iloc[ib_idx]
    return _sig("C", ic, last, {"retest_candles": n_retest, "atr": round(atr, 2)})


def _pattern_eng(df):
    """Bullish Engulfing at VWAP: rising-VWAP uptrend context, ≥3 of 4 pre-dip candles above VWAP,
    red dip touches VWAP, green engulf closes above, ≥1.5× volume, ≥0.3% risk."""
    if len(df) < 6: return None
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if last["close"] <= last["open"]:  return None  # must be green
    if last["close"] <= last["vwap"]:  return None  # must close above VWAP
    if prev["close"] >= prev["open"]:  return None  # prev must be red
    if prev["low"]   >  prev["vwap"]:  return None  # prev wick must touch VWAP
    if prev["open"]  <  prev["vwap"]:  return None  # prev opened above VWAP
    if last["open"]  >  prev["close"]: return None  # engulfing condition
    if last["close"] <  prev["open"]:  return None  # engulfing condition

    # Prior uptrend: ≥3 of 4 candles before the red dip were above VWAP
    pre_dip = df.iloc[-6:-2]
    if len(pre_dip) < 3: return None
    if (pre_dip["close"] > pre_dip["vwap"]).sum() < 3: return None

    # VWAP must be rising — proxy for daily uptrend bias
    if float(last["vwap"]) < float(df.iloc[-5]["vwap"]) * 1.001: return None

    avg_vol = _avg_volume(df)
    if avg_vol > 0 and df["volume"].iloc[-1] < 1.5 * avg_vol: return None

    # Minimum risk 0.3%
    entry = last["close"]; sl = last["vwap"]
    if (entry - sl) / entry < 0.003: return None

    dip_pct = round((prev["vwap"] - prev["low"]) / prev["vwap"] * 100, 3)
    return _sig("ENG", prev, last, {"dip_pct": dip_pct})


def _pattern_ham(df):
    """Hammer at VWAP: rising-VWAP uptrend context, lower wick ≥2× body (≥0.3% of price) pierces VWAP,
    closes above, ≥0.3% risk (rejects 3-paise phantom hammers), ≥avg volume."""
    if len(df) < 5: return None
    last = df.iloc[-1]

    if last["close"] <= last["vwap"]: return None

    body       = abs(last["close"] - last["open"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    upper_wick = last["high"] - max(last["open"], last["close"])

    if body < last["close"] * 0.0005:     return None  # body must exist
    if lower_wick < 2.0 * body:           return None  # wick ≥ 2× body
    if last["low"] > last["vwap"]:        return None  # wick must pierce VWAP
    if upper_wick > body:                 return None  # small upper wick
    if lower_wick / last["vwap"] < 0.003: return None  # wick ≥ 0.3% of price

    if df.iloc[-2]["close"] <= df.iloc[-2]["vwap"]: return None
    if df.iloc[-3]["close"] <= df.iloc[-3]["vwap"]: return None

    # VWAP must be rising (uptrend context)
    if float(last["vwap"]) < float(df.iloc[-5]["vwap"]) * 1.001: return None

    # Minimum risk 0.3% (SL = VWAP)
    if (last["close"] - last["vwap"]) / last["close"] < 0.003: return None

    avg_vol = _avg_volume(df)
    if avg_vol > 0 and df["volume"].iloc[-1] < avg_vol: return None

    dip_pct = round(lower_wick / last["vwap"] * 100, 3)
    return _sig("HAM", last, last, {"dip_pct": dip_pct})


def _pattern_mar(df):
    """Bullish Marubozu VWAP Reclaim: near-wickless, opens below, closes well above VWAP. Vol ≥2×."""
    if len(df) < 2: return None
    last = df.iloc[-1]

    if last["close"] <= last["open"]: return None
    if last["open"]  >= last["vwap"]: return None
    if last["close"] <= last["vwap"]: return None
    if (last["close"] - last["vwap"]) / last["vwap"] < 0.002: return None

    body       = last["close"] - last["open"]
    upper_wick = last["high"]  - last["close"]
    lower_wick = last["open"]  - last["low"]
    if body <= 0: return None
    if upper_wick > 0.25 * body: return None
    if lower_wick > 0.25 * body: return None
    if df.iloc[-2]["close"] >= df.iloc[-2]["vwap"]: return None

    avg_vol = _avg_volume(df)
    if avg_vol <= 0: return None
    if df["volume"].iloc[-1] < 3.0 * avg_vol: return None  # raised from 2× to 3×

    # Minimum risk 0.3% to avoid near-zero risk trades
    if (last["close"] - last["vwap"]) / last["close"] < 0.003: return None

    dip_pct = round((last["vwap"] - last["open"]) / last["vwap"] * 100, 3)
    return _sig("MAR", df.iloc[-2], last, {"dip_pct": dip_pct})


def _pattern_star(df):
    """Morning Star at VWAP — DISABLED: fires too frequently (80 signals/day, 13% WR). Needs redesign."""
    return None
    if len(df) < 4: return None
    c3 = df.iloc[-1]
    c2 = df.iloc[-2]
    c1 = df.iloc[-3]
    c0 = df.iloc[-4]

    if c3["close"] <= c3["open"]: return None
    if c3["close"] <= c3["vwap"]: return None
    if c1["close"] >= c1["open"]: return None
    if abs(c1["close"] - c1["vwap"]) / c1["vwap"] > 0.005: return None

    c1_body = abs(c1["open"] - c1["close"])
    c2_body = abs(c2["open"] - c2["close"])
    if c1_body <= 0: return None
    if c2_body > 0.5 * c1_body: return None
    if abs((c2["open"] + c2["close"]) / 2 - c2["vwap"]) / c2["vwap"] > 0.005: return None
    if c3["close"] < (c1["open"] + c1["close"]) / 2: return None
    if c0["close"] <= c0["vwap"]: return None
    if "volume" in df.columns and c3["volume"] <= c1["volume"]: return None

    return _sig("STAR", c1, c3, {})


def _pattern_ham2s(df):
    """Hammer at −2σ VWAP band — mean reversion BUY on range days only."""
    if len(df) < 5:
        return None
    sigma = _calc_vwap_sigma(df)
    if sigma is None:
        return None

    last     = df.iloc[-1]
    vwap     = last["vwap"]
    sig_val  = float(sigma.iloc[-1])
    if sig_val <= 0:
        return None

    lower_2s = vwap - 2.0 * sig_val

    vwap_slice = df["vwap"].iloc[-5:]
    if (vwap_slice.max() - vwap_slice.min()) / vwap > 0.0015:
        return None

    if last["low"] > lower_2s:         return None

    # EOD filter: no signals after 14:45 (market closes too soon for trade to resolve)
    if last.name.strftime("%H:%M") > "14:45":
        return None

    body       = abs(last["close"] - last["open"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    upper_wick = last["high"] - max(last["open"], last["close"])

    if body       < last["close"] * 0.0003: return None
    if lower_wick < 2.0 * body:             return None
    if last["close"] < lower_2s:            return None
    if upper_wick > body:                   return None

    avg_vol = _avg_volume(df)
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


def _pattern_bw(df):
    """Band Walk at +1σ — DISABLED: 32 signals/day, 3% WR, -₹6,253. Fires on every rising stock. Needs redesign."""
    return None
    if len(df) < 7:
        return None
    sigma = _calc_vwap_sigma(df)
    if sigma is None:
        return None

    last     = df.iloc[-1]
    vwap     = last["vwap"]
    sig_val  = float(sigma.iloc[-1])
    if sig_val <= 0:
        return None

    upper_1s = vwap + sig_val

    vwap_6ago = df["vwap"].iloc[-7]
    if vwap < vwap_6ago * 1.001:
        return None

    walk_count = 0
    for i in range(-5, -1):
        c   = df.iloc[i]
        s_i = float(sigma.iloc[i])
        if c["close"] > c["vwap"] + s_i:
            walk_count += 1
    if walk_count < 2:
        return None

    if df.iloc[-1]["low"]   > upper_1s: return None
    if df.iloc[-1]["close"] < upper_1s: return None

    body         = abs(last["close"] - last["open"])
    lower_wick   = min(last["open"], last["close"]) - last["low"]
    candle_range = last["high"] - last["low"]
    is_hammer    = body > 0 and lower_wick >= 2.0 * body
    is_doji      = candle_range > 0 and body <= 0.25 * candle_range
    if not (is_hammer or is_doji):
        return None

    avg_vol = _avg_volume(df)
    if avg_vol > 0 and last["volume"] < avg_vol:
        return None

    dip_pct = round((upper_1s - last["low"]) / upper_1s * 100, 3)
    return _sig("BW", last, last, {"dip_pct": dip_pct})


def _pattern_sqz(df):
    """Squeeze Breakout — DISABLED: 0% WR, 21 signals, -₹22,424. Sigma squeeze too loose, not detecting real squeezes."""
    return None
    if len(df) < 8:
        return None
    sigma = _calc_vwap_sigma(df)
    if sigma is None:
        return None

    last    = df.iloc[-1]
    vwap    = last["vwap"]
    sig_now = float(sigma.iloc[-1])
    if sig_now <= 0:
        return None

    upper_1s = vwap + sig_now

    if last["close"] <= upper_1s:     return None
    if last["close"] <= last["open"]: return None

    lookback = min(7, len(df) - 1)
    sig_prev = [float(sigma.iloc[-i]) for i in range(2, lookback + 2)]
    if len(sig_prev) < 4:
        return None

    sig_min = min(sig_prev)

    if sig_min / vwap > 0.004:      return None
    if sig_now < sig_min * 1.2:     return None

    coil_count = 0
    for i in range(-lookback - 1, -1):
        c   = df.iloc[i]
        s_i = float(sigma.iloc[i])
        if abs(c["close"] - c["vwap"]) <= s_i:
            coil_count += 1
    if coil_count < int(lookback * 0.6):
        return None

    squeeze_vol_avg = df["volume"].iloc[-lookback - 1:-1].mean()
    if squeeze_vol_avg > 0 and last["volume"] < 1.5 * squeeze_vol_avg:
        return None

    return _sig("SQZ", last, last, {"band_sigma": round(sig_now, 2)})


def _pattern_open_rcl(df):
    """Opening VWAP Reclaim: yesterday closed in TOP 40% of range (strong close), today opens
    weak, then a STRONG green bar at 09:25/09:35 reclaims VWAP with 1.5× vol and body in top 50%.
    Target 2:1 (achievable intraday). Requires prev_bullish attr set by _scan_one."""
    if len(df) < 3: return None
    last = df.iloc[-1]
    t    = last.name.strftime("%H:%M")
    if t < "09:25" or t > "09:35": return None

    # Previous day must have closed in top 40% of its range
    prev_info = df.attrs.get("prev_day_info")
    if prev_info is None: return None
    if not prev_info.get("strong_close", False): return None

    # Reclaim candle: green, closes above VWAP, body mostly above VWAP
    if last["close"] <= last["open"]: return None
    if last["close"] <= last["vwap"]: return None
    if (last["open"] + last["close"]) / 2 <= last["vwap"]: return None

    # Reclaim bar close in top 50% of bar range (strong buyers, not a doji)
    bar_range = float(last["high"]) - float(last["low"])
    if bar_range > 0 and (float(last["close"]) - float(last["low"])) / bar_range < 0.50:
        return None

    # Prior 1-3 bars closed at or below VWAP (the weak open)
    n_below     = 0
    min_low     = float("inf")
    max_dip_pct = 0.0
    for i in range(len(df) - 2, max(len(df) - 5, -1), -1):
        c = df.iloc[i]
        if float(c["close"]) <= float(c["vwap"]):
            n_below     += 1
            min_low      = min(min_low, float(c["low"]))
            dip          = (float(c["vwap"]) - float(c["close"])) / float(c["vwap"])
            max_dip_pct  = max(max_dip_pct, dip)
        else:
            break

    if n_below < 1: return None
    if max_dip_pct < 0.001: return None

    # Volume ≥ 1.5× avg — genuine buying, not a drift
    avg_vol = _avg_volume(df)
    if avg_vol > 0 and last["volume"] < 1.5 * avg_vol: return None

    entry = float(last["close"])
    sl    = round(min_low * 0.998, 2)
    risk  = entry - sl
    if risk <= 0 or risk / entry < 0.002: return None
    if risk / entry > 0.012: return None
    target = round(entry + 2.0 * risk, 2)  # 2:1 — more achievable intraday

    return {
        "pattern":    "OPEN_RCL",
        "touch_time": last.name.strftime("%H:%M"),
        "touch_low":  round(min_low, 2),
        "touch_high": round(float(last["high"]), 2),
        "touch_vwap": round(float(last["vwap"]), 2),
        "entry_time": last.name.strftime("%H:%M"),
        "entry":      round(entry, 2),
        "sl":         round(sl, 2),
        "target":     target,
        "risk":       round(risk, 2),
        "reward":     round(3.0 * risk, 2),
        "dip_pct":    round(max_dip_pct * 100, 3),
    }


def _pattern_flag(df):
    """High-tight Bull Flag: sharp pole (≥1%) + tight 3-6 bar flag + breakout above VWAP + vol."""
    if len(df) < 9: return None
    last = df.iloc[-1]
    if last.name.strftime("%H:%M") > "14:00": return None
    if last["close"] <= last["open"]: return None
    if last["close"] <= last["vwap"]: return None
    for flag_len in range(3, 7):
        f0 = len(df) - 1 - flag_len
        if f0 < 2: continue
        flag_bars = df.iloc[f0: len(df) - 1]
        pole_bars = df.iloc[max(0, f0 - 3): f0]
        if len(flag_bars) < 3 or len(pole_bars) < 2: continue
        if flag_bars.iloc[0]["high"] <= flag_bars.iloc[-1]["high"]: continue
        flag_high  = float(flag_bars["high"].max())
        flag_low   = float(flag_bars["low"].min())
        flag_range = flag_high - flag_low
        if last["close"] <= flag_high: continue
        if not (pole_bars["close"] > pole_bars["open"]).all(): continue
        pole_clean = True
        for _, pc in pole_bars.iterrows():
            cr = float(pc["high"]) - float(pc["low"])
            if cr > 0 and (float(pc["close"]) - float(pc["low"])) / cr < 0.55:
                pole_clean = False; break
        if not pole_clean: continue
        pole_base = float(pole_bars.iloc[0]["open"])
        pole_top  = float(pole_bars.iloc[-1]["close"])
        pole_h    = pole_top - pole_base
        if pole_h <= 0 or pole_h / pole_base < 0.010: continue
        if flag_range > pole_h * 0.50: continue
        if flag_low < pole_top - pole_h * 0.55: continue
        avg_vol = _avg_volume(df)
        if avg_vol > 0 and last["volume"] < 1.2 * avg_vol: continue
        entry = float(last["close"])
        sl    = round(flag_low - 0.01, 2)
        risk  = entry - sl
        if risk <= 0 or risk / entry < 0.001: continue
        if risk / entry > 0.010: continue
        target = round(entry + min(pole_h, 5 * risk), 2)
        return {
            "pattern":    "FLAG",
            "touch_time": last.name.strftime("%H:%M"),
            "touch_low":  round(float(last["low"]), 2),
            "touch_high": round(flag_high, 2),
            "touch_vwap": round(float(last["vwap"]), 2),
            "entry_time": last.name.strftime("%H:%M"),
            "entry":      round(entry, 2),
            "sl":         round(sl, 2),
            "target":     target,
            "risk":       round(risk, 2),
            "reward":     round(target - entry, 2),
            "pole_pct":   round(pole_h / pole_base * 100, 2),
        }
    return None


def _pattern_tri(df):
    """Ascending Triangle: flat resistance ≥3 touches + rising inter-touch troughs + vol breakout."""
    if len(df) < 13: return None
    last = df.iloc[-1]; prev = df.iloc[-2]
    if last.name.strftime("%H:%M") > "14:00": return None
    if last["close"] <= last["open"]: return None
    if last["close"] <= last["vwap"]: return None
    for lookback in range(10, min(31, len(df))):
        tri = df.iloc[-(lookback + 1):-1]
        if len(tri) < 8: continue
        highs = tri["high"].values; lows = tri["low"].values
        res_lvl = float(np.median(sorted(highs, reverse=True)[:3]))
        if res_lvl <= 0: continue
        touch_idx = [i for i, h in enumerate(highs) if abs(h - res_lvl) / res_lvl <= 0.002]
        if len(touch_idx) < 3: continue
        if touch_idx[-1] - touch_idx[0] < len(tri) // 2: continue
        inter_troughs = []
        for k in range(len(touch_idx) - 1):
            seg_lows = lows[touch_idx[k]: touch_idx[k + 1] + 1]
            inter_troughs.append(float(seg_lows.min()))
        if len(inter_troughs) < 2: continue
        if not all(inter_troughs[i + 1] > inter_troughs[i] * 1.002
                   for i in range(len(inter_troughs) - 1)):
            continue
        if float(prev["close"]) > res_lvl * 1.002: continue
        if float(last["close"]) <= res_lvl * 1.002: continue
        avg_vol = _avg_volume(df)
        if avg_vol > 0 and last["volume"] < 1.5 * avg_vol: continue
        tri_height = res_lvl - inter_troughs[0]
        if tri_height <= 0 or tri_height / res_lvl < 0.005: continue
        entry = float(last["close"])
        sl    = round(inter_troughs[-1] - 0.01, 2)
        risk  = entry - sl
        if risk <= 0 or risk / entry < 0.001: continue
        if risk / entry > 0.012: continue
        target = round(entry + min(tri_height, 5 * risk), 2)
        return {
            "pattern":    "TRI",
            "touch_time": last.name.strftime("%H:%M"),
            "touch_low":  round(float(last["low"]), 2),
            "touch_high": round(res_lvl, 2),
            "touch_vwap": round(float(last["vwap"]), 2),
            "entry_time": last.name.strftime("%H:%M"),
            "entry":      round(entry, 2),
            "sl":         round(sl, 2),
            "target":     target,
            "risk":       round(risk, 2),
            "reward":     round(target - entry, 2),
            "tri_h_pct":  round(tri_height / res_lvl * 100, 2),
            "touches":    len(touch_idx),
        }
    return None


def _pattern_dtri(df):
    """Descending Triangle (bullish): flat support ≥3 touches + descending inter-touch peaks + vol breakout."""
    if len(df) < 13: return None
    last = df.iloc[-1]; prev = df.iloc[-2]
    if last.name.strftime("%H:%M") > "14:00": return None
    if last["close"] <= last["open"]: return None
    if last["close"] <= last["vwap"]: return None
    for lookback in range(10, min(31, len(df))):
        tri = df.iloc[-(lookback + 1):-1]
        if len(tri) < 8: continue
        highs = tri["high"].values; lows = tri["low"].values
        sup_lvl = float(np.median(sorted(lows)[:3]))
        if sup_lvl <= 0: continue
        touch_idx = [i for i, l in enumerate(lows) if abs(l - sup_lvl) / sup_lvl <= 0.002]
        if len(touch_idx) < 3: continue
        if touch_idx[-1] - touch_idx[0] < len(tri) // 2: continue
        inter_peaks = []
        for k in range(len(touch_idx) - 1):
            seg = highs[touch_idx[k]: touch_idx[k + 1] + 1]
            inter_peaks.append(float(seg.max()))
        if len(inter_peaks) < 2: continue
        if not all(inter_peaks[i + 1] < inter_peaks[i] * 0.998
                   for i in range(len(inter_peaks) - 1)):
            continue
        res_line = inter_peaks[-1]
        if float(prev["close"]) > res_line * 1.002: continue
        if float(last["close"]) <= res_line * 1.002: continue
        avg_vol = _avg_volume(df)
        if avg_vol > 0 and last["volume"] < 1.5 * avg_vol: continue
        tri_height = inter_peaks[0] - sup_lvl
        if tri_height <= 0 or tri_height / sup_lvl < 0.005: continue
        entry = float(last["close"])
        sl    = round(sup_lvl * 0.998 - 0.01, 2)
        risk  = entry - sl
        if risk <= 0 or risk / entry < 0.001: continue
        if risk / entry > 0.015: continue
        target = round(entry + min(tri_height, 5 * risk), 2)
        return {
            "pattern":    "DTRI",
            "touch_time": last.name.strftime("%H:%M"),
            "touch_low":  round(sup_lvl, 2),
            "touch_high": round(float(last["high"]), 2),
            "touch_vwap": round(float(last["vwap"]), 2),
            "entry_time": last.name.strftime("%H:%M"),
            "entry":      round(entry, 2),
            "sl":         round(sl, 2),
            "target":     target,
            "risk":       round(risk, 2),
            "reward":     round(target - entry, 2),
            "tri_h_pct":  round(tri_height / sup_lvl * 100, 2),
            "touches":    len(touch_idx),
        }
    return None


def _pattern_vcnb(df):
    """VWAP Consolidation Breakout: uptrend above VWAP + 3-bar tight base + 5-bar high break + vol surge."""
    if len(df) < 8: return None
    last = df.iloc[-1]
    t    = last.name.strftime("%H:%M")
    if t < "10:00" or t > "13:00": return None
    if last["close"] <= last["open"]: return None
    if last["close"] <= last["vwap"]: return None
    prior5 = df.iloc[-6:-1]
    if len(prior5) < 5: return None
    if float(last["high"]) <= float(prior5["high"].max()): return None
    prior3 = df.iloc[-4:-1]
    if len(prior3) < 3: return None
    above_count = sum(
        float(b["close"]) > float(b["vwap"])
        for _, b in prior3.iterrows()
        if not pd.isna(b["vwap"])
    )
    if above_count < 2: return None
    sess_range = (float(df["high"].max()) - float(df["low"].min())) / max(1, len(df))
    p3_range   = float(prior3["high"].max()) - float(prior3["low"].min())
    if sess_range <= 0 or p3_range > sess_range * 4: return None
    avg_vol = _avg_volume(df)
    if avg_vol > 0 and last["volume"] < 1.3 * avg_vol: return None
    entry = float(last["close"])
    sl    = round(float(prior3["low"].min()) * 0.998, 2)
    risk  = entry - sl
    if risk <= 0 or risk / entry < 0.001: return None
    if risk / entry > 0.012: return None
    target = round(entry + 2.0 * risk, 2)
    return {
        "pattern":    "VCNB",
        "touch_time": last.name.strftime("%H:%M"),
        "touch_low":  round(float(last["low"]), 2),
        "touch_high": round(float(last["high"]), 2),
        "touch_vwap": round(float(last["vwap"]), 2),
        "entry_time": last.name.strftime("%H:%M"),
        "entry":      round(entry, 2),
        "sl":         round(sl, 2),
        "target":     target,
        "risk":       round(risk, 2),
        "reward":     round(target - entry, 2),
        "consol_pct": round(p3_range / entry * 100, 2),
    }


def _find_signal(today_df):
    """Scan 9:25–14:00 for all patterns. Each pattern has its own internal time guards.
    OPEN_RCL checked first — it fires 09:25–09:35 only (prev-day bullish stocks only)."""
    times = today_df.index.strftime("%H:%M")
    avail = today_df[(times >= "09:25") & (times <= "14:00")]
    for ts in avail.index:
        sl = today_df[today_df.index <= ts]
        if len(sl) < 3: continue
        sig = (_pattern_open_rcl(sl) or
               _pattern_b(sl)     or _pattern_c(sl)     or
               _pattern_eng(sl)   or _pattern_ham(sl)   or
               _pattern_mar(sl)   or _pattern_star(sl)  or
               _pattern_ham2s(sl) or _pattern_bw(sl)    or
               _pattern_sqz(sl)   or _pattern_flag(sl)  or
               _pattern_tri(sl)   or _pattern_dtri(sl)  or
               _pattern_vcnb(sl))
        if sig: return sig
    return None


def _simulate(sig, today_df):
    """Simulate the trade from signal entry to SL/target/EOD."""
    entry = sig["entry"]; sl = sig["sl"]; target = sig["target"]
    future = today_df[today_df.index.strftime("%H:%M") > sig["entry_time"]]

    outcome    = "IN_TRADE"
    exit_price = float(today_df.iloc[-1]["close"])
    exit_time  = today_df.index[-1].strftime("%H:%M")

    for ts, row in future.iterrows():
        if row["low"] <= sl:
            outcome = "SL_HIT"; exit_price = sl
            exit_time = ts.strftime("%H:%M"); break
        if row["high"] >= target:
            outcome = "TARGET_HIT"; exit_price = target
            exit_time = ts.strftime("%H:%M"); break

    shares = int(TRADE_CAPITAL / entry) if entry > 0 else 0
    pnl    = round((exit_price - entry) * shares, 2)
    return {
        "outcome":    outcome,
        "exit_price": round(exit_price, 2),
        "exit_time":  exit_time,
        "shares":     shares,
        "pnl":        pnl,
        "pnl_pct":    round((exit_price - entry) / entry * 100, 2),
    }


# ── Single-stock scan ─────────────────────────────────────────────────────────
def _scan_one(row):
    sym  = row["symbol"]
    ikey = row["instrument_key"]
    mcap = float(row.get("market_cap_cr") or 0)

    try:
        df = get_10min_candles(ikey, days_back=2)
        if df.empty: return None
        today_date = df.index[-1].date()
        day_df     = df[df.index.date == today_date].copy()
        if day_df.empty or len(day_df) < 3: return None
        day_df["vwap"] = calculate_vwap(day_df)
        day_df = day_df.dropna(subset=["vwap"])
        if len(day_df) < 3: return None

        # Compute previous day info for OPEN_RCL filter
        prev_df = df[df.index.date < today_date]
        prev_day_info = None
        if not prev_df.empty:
            prev_day_date = sorted(set(prev_df.index.date))[-1]
            pd_df = prev_df[prev_df.index.date == prev_day_date].copy()
            pd_df["vwap"] = calculate_vwap(pd_df)
            pd_df = pd_df.dropna(subset=["vwap"])
            if not pd_df.empty:
                pd_high  = float(pd_df["high"].max())
                pd_low   = float(pd_df["low"].min())
                pd_close = float(pd_df.iloc[-1]["close"])
                pd_range = pd_high - pd_low
                strong_close = (pd_range > 0 and
                                (pd_close - pd_low) / pd_range >= 0.60)
                prev_day_info = {"strong_close": strong_close}
        day_df.attrs["prev_day_info"] = prev_day_info

        sig = _find_signal(day_df)
        if not sig: return None  # test mode: only return signal stocks

        sim = _simulate(sig, day_df)

        return {
            "symbol":          sym,
            "instrument_key":  ikey,
            "mcap":            mcap,
            "confidence":      50,
            "st_vwap_gap_pct": 0,
            "vwap_pp_gap_pct": 0,
            "entry_signal":    sig,
            "sim":             sim,
            # Dummy fields so SummaryTable doesn't crash if ever rendered
            "c0_time": "—", "c0_close": sig["entry"], "c0_vwap": sig["sl"],
            "c0_st": 0, "pp": 0,
        }
    except Exception as e:
        print(f"  [skip] {sym}: {e}")
        return None


# ── Full scan ─────────────────────────────────────────────────────────────────
def _run_test_scan():
    rows = _universe.to_dict("records")
    state["scanning"]      = True
    state["scan_progress"] = 0
    state["scan_total"]    = len(rows)
    state["results"]       = []
    state["scan_time"]     = datetime.now(IST).strftime("%H:%M:%S")

    print(f"\n[TEST] Scanning {len(rows)} stocks for all VWAP patterns today...")
    results = []

    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(_scan_one, r): r["symbol"] for r in rows}
        for i, f in enumerate(as_completed(futs), 1):
            state["scan_progress"] = i
            res = f.result()
            if res:
                results.append(res)
                print(f"  SIGNAL  {res['symbol']:<16}  Pattern {res['entry_signal']['pattern']}"
                      f"  entry@{res['entry_signal']['entry_time']}"
                      f"  -> {res['sim']['outcome']}  P&L Rs{res['sim']['pnl']:+,.0f}")

    # Sort: TARGET_HIT first, then IN_TRADE, then SL_HIT
    order = {"TARGET_HIT": 0, "IN_TRADE": 1, "SL_HIT": 2}
    state["results"] = sorted(results, key=lambda r: order.get(r["sim"]["outcome"], 9))
    state["scanning"] = False

    sigs   = len(results)
    wins   = sum(1 for r in results if r["sim"]["outcome"] == "TARGET_HIT")
    losses = sum(1 for r in results if r["sim"]["outcome"] == "SL_HIT")
    open_  = sum(1 for r in results if r["sim"]["outcome"] == "IN_TRADE")
    total  = sum(r["sim"]["pnl"] for r in results)
    print(f"\n[TEST] Done — {sigs} signals  |  {wins} target  {losses} SL  {open_} in-trade"
          f"  |  Total Rs{total:+,.0f}")


# ── Re-simulation loop — updates IN TRADE outcomes every 10 minutes ───────────
def _resim_loop():
    """Re-runs _simulate() for every IN TRADE stock with fresh candle data."""
    while True:
        time.sleep(600)  # wait 10 minutes before first re-sim
        results = state["results"]
        if not results or state["scanning"]:
            continue

        updated = 0
        for r in results:
            if r.get("sim", {}).get("outcome") != "IN_TRADE":
                continue
            ikey = r.get("instrument_key")
            sig  = r.get("entry_signal")
            if not ikey or not sig:
                continue
            try:
                df = get_10min_candles(ikey, days_back=1)
                if df.empty:
                    continue
                today = df.index[-1].date()
                day_df = df[df.index.date == today].copy()
                if day_df.empty:
                    continue
                day_df["vwap"] = calculate_vwap(day_df)
                day_df = day_df.dropna(subset=["vwap"])
                new_sim = _simulate(sig, day_df)
                r["sim"] = new_sim
                updated += 1
            except Exception:
                pass

        if updated:
            # Re-sort by outcome
            order = {"TARGET_HIT": 0, "IN_TRADE": 1, "SL_HIT": 2}
            state["results"] = sorted(results, key=lambda r: order.get(r["sim"]["outcome"], 9))
            print(f"[TEST] Re-sim done — {updated} IN TRADE stocks updated")


# ── API endpoints ─────────────────────────────────────────────────────────────
@app.get("/api/status")
def get_status():
    return {
        "universe":      len(_universe),
        "scan_time":     state["scan_time"],
        "result_count":  len(state["results"]),
        "signal_count":  sum(1 for r in state["results"] if r.get("entry_signal")),
        "scanning":      state["scanning"],
        "scan_progress": state["scan_progress"],
        "scan_total":    state["scan_total"],
        "market_open":   _is_market_open(),
        "server_time":   datetime.now(IST).strftime("%H:%M:%S"),
        "test_mode":     True,
    }


@app.get("/api/results")
def get_results():
    return {"results": state["results"], "scan_time": state["scan_time"]}


@app.post("/api/scan/start")
async def start_scan():
    if state["scanning"]: return {"status": "already_scanning"}
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_test_scan)
    return {"status": "started"}


@app.post("/api/clear")
def clear_results():
    state.update({"results": [], "scan_time": None})
    return {"status": "cleared"}


@app.get("/api/live")
def get_live():
    market_open = _is_market_open()
    price_map   = {}
    results     = state["results"]

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

    return {
        "prices":      price_map,
        "market_open": market_open,
        "server_time": datetime.now(IST).strftime("%H:%M:%S"),
    }


@app.get("/api/chart/{instrument_key:path}")
def get_chart(instrument_key: str):
    try:
        df = get_10min_candles(instrument_key, days_back=1)
        if df.empty: return {"candles": [], "vwap": []}
        today = df.index[-1].date()
        df    = df[df.index.date == today].copy()
        df["vwap"] = calculate_vwap(df)
        candles, vwap = [], []
        for ts, row in df.iterrows():
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


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    NPM = "npm.cmd" if os.name == "nt" else "npm"

    print("\n  [TEST MODE] TejToro — No-filter Pattern B/C/ENG/HAM/MAR/STAR scan")
    print("  Starting Vite frontend...")
    frontend_proc = subprocess.Popen(
        [NPM, "run", "dev", "--", "--config", "vite.test.config.js"],
        cwd=FRONTEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # Start scan in background — runs while uvicorn is serving
    def _auto_scan():
        time.sleep(1)
        _run_test_scan()

    threading.Thread(target=_auto_scan, daemon=True).start()
    threading.Thread(target=_resim_loop, daemon=True).start()

    time.sleep(3)
    webbrowser.open("http://localhost:5174")

    print("  Backend  -> http://localhost:8001")
    print("  Frontend -> http://localhost:5174")
    print("  Scan running in background — refresh browser in ~2 min")
    print("  Press Ctrl+C to stop.\n")

    try:
        uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")
    finally:
        frontend_proc.terminate()

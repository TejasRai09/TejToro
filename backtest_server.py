"""
backtest_server.py — Backtest Lab API (port 8002)
Reads data/10min/*.parquet, computes daily VWAP, runs pattern strategies.

Run: uvicorn backtest_server:app --port 8002 --reload

NOTE: token.txt must NEVER be committed to GitHub.
"""
import os, glob
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

ROOT     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data", "10min")

_EPOCH = pd.Timestamp('1970-01-01')   # naive epoch for timezone-safe chart timestamps

def _ts(dt: pd.Timestamp) -> int:
    """Convert naive IST timestamp → seconds-since-naive-epoch for lightweight-charts.
    Avoids datetime.timestamp() which depends on the OS/process timezone."""
    return int((dt - _EPOCH).total_seconds())

app = FastAPI(title="TejToro Backtest Lab")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Data helpers ───────────────────────────────────────────────────────────────

def _load(symbol: str) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"{symbol}.parquet")
    if not os.path.exists(path):
        raise HTTPException(404, f"No data for {symbol}")
    df = pd.read_parquet(path)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def _add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Compute cumulative daily VWAP and attach as a column."""
    df = df.copy()
    df["tp"] = (df["high"] + df["low"] + df["close"]) / 3
    groups = []
    for _, g in df.groupby(df.index.date):
        g = g.copy()
        cum_vol  = g["volume"].cumsum().replace(0, np.nan)
        g["vwap"] = (g["tp"] * g["volume"]).cumsum() / cum_vol
        g["vwap"] = g["vwap"].fillna(g["close"])
        groups.append(g)
    out = pd.concat(groups).sort_index()
    out.drop(columns=["tp"], inplace=True)
    return out


def _calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI. Returns NaN for the first period-1 bars (not yet warmed up)."""
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_g = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    denom = avg_g + avg_l
    return pd.Series(
        np.where(denom == 0, 50.0, avg_g / denom * 100),
        index=close.index,
    )


# ── Pattern helpers (identical logic to test.py) ───────────────────────────────

def _avg_volume(df, n=20):
    if "volume" not in df.columns or len(df) < 2:
        return 0.0
    vols = df["volume"].iloc[max(0, len(df) - n - 1):-1]
    vols = vols[vols > 0]
    return float(vols.mean()) if len(vols) > 0 else 0.0


def _calc_vwap_sigma(today_df):
    if len(today_df) < 3 or "volume" not in today_df.columns:
        return None
    tp      = (today_df["high"] + today_df["low"] + today_df["close"]) / 3
    vol     = today_df["volume"].clip(lower=0)
    cum_vol = vol.cumsum().replace(0, np.nan)
    vwap_cv = (tp * vol).cumsum() / cum_vol
    var_cv  = (tp ** 2 * vol).cumsum() / cum_vol - vwap_cv ** 2
    return var_cv.clip(lower=0).apply(np.sqrt).fillna(0.0)


def _sig(pattern, entry_candle, extra=None, sl_price=None):
    entry = float(entry_candle["close"])
    sl    = sl_price if sl_price is not None else float(entry_candle["vwap"])
    risk  = entry - sl
    if risk <= 0:
        return None
    d = {
        "pattern":    pattern,
        "entry_time": entry_candle.name.strftime("%H:%M"),
        "entry":      round(entry, 2),
        "sl":         round(sl, 2),
        "target":     round(entry + 3 * risk, 2),
        "bar_ts":     _ts(entry_candle.name),
    }
    if extra:
        d.update(extra)
    return d


def _pattern_b(df):
    if len(df) < 3: return None
    last = df.iloc[-1]
    if last["close"] <= last["vwap"]: return None
    if last["close"] <= last["open"]: return None

    n_below = 0; max_dip_pct = 0.0
    for i in range(len(df) - 2, max(len(df) - 5, -1), -1):
        c = df.iloc[i]
        if c["close"] < c["vwap"]:
            n_below += 1
            dip = (c["vwap"] - c["close"]) / c["vwap"]
            if dip > max_dip_pct: max_dip_pct = dip
        else:
            break

    if not (1 <= n_below <= 3): return None
    if max_dip_pct < 0.001: return None

    entry = last["close"]; sl = last["vwap"]; risk = entry - sl
    if risk / entry < 0.002: return None

    before_idx = len(df) - 2 - n_below
    if before_idx < 0: return None
    if df.iloc[before_idx]["close"] <= df.iloc[before_idx]["vwap"]: return None

    return _sig("B", last, {"candles_below": n_below, "dip_pct": round(max_dip_pct * 100, 3)})


def _pattern_eng(df):
    if len(df) < 6: return None
    last = df.iloc[-1]; prev = df.iloc[-2]
    if last["close"] <= last["open"]: return None
    if last["close"] <= last["vwap"]: return None
    if prev["close"] >= prev["open"]: return None
    if prev["low"]   >  prev["vwap"]: return None
    if prev["open"]  <  prev["vwap"]: return None
    if last["open"]  >  prev["close"]: return None
    if last["close"] <  prev["open"]: return None

    pre_dip = df.iloc[-6:-2]
    if len(pre_dip) < 3: return None
    if (pre_dip["close"] > pre_dip["vwap"]).sum() < 3: return None
    if float(last["vwap"]) < float(df.iloc[-5]["vwap"]) * 1.001: return None

    avg_vol = _avg_volume(df)
    if avg_vol > 0 and df["volume"].iloc[-1] < 1.5 * avg_vol: return None

    entry = last["close"]; sl = last["vwap"]
    if (entry - sl) / entry < 0.003: return None

    dip_pct = round((prev["vwap"] - prev["low"]) / prev["vwap"] * 100, 3)
    return _sig("ENG", last, {"dip_pct": dip_pct})


def _pattern_ham(df):
    if len(df) < 5: return None
    last = df.iloc[-1]
    if last["close"] <= last["vwap"]: return None

    body       = abs(last["close"] - last["open"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    upper_wick = last["high"] - max(last["open"], last["close"])

    if body        < last["close"] * 0.0005: return None
    if lower_wick  < 2.0 * body:             return None
    if last["low"] > last["vwap"]:           return None
    if upper_wick  > body:                   return None
    if lower_wick / last["vwap"] < 0.003:    return None
    if df.iloc[-2]["close"] <= df.iloc[-2]["vwap"]: return None
    if df.iloc[-3]["close"] <= df.iloc[-3]["vwap"]: return None
    if float(last["vwap"]) < float(df.iloc[-5]["vwap"]) * 1.001: return None
    if (last["close"] - last["vwap"]) / last["close"] < 0.003: return None

    avg_vol = _avg_volume(df)
    if avg_vol > 0 and df["volume"].iloc[-1] < avg_vol: return None

    dip_pct = round(lower_wick / last["vwap"] * 100, 3)
    return _sig("HAM", last, {"dip_pct": dip_pct})


def _pattern_mar(df):
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
    if df["volume"].iloc[-1] < 3.0 * avg_vol: return None
    if (last["close"] - last["vwap"]) / last["close"] < 0.003: return None

    dip_pct = round((last["vwap"] - last["open"]) / last["vwap"] * 100, 3)
    return _sig("MAR", last, {"dip_pct": dip_pct})


def _pattern_ham2s(df):
    if len(df) < 5: return None
    sigma = _calc_vwap_sigma(df)
    if sigma is None: return None

    last    = df.iloc[-1]
    vwap    = float(last["vwap"])
    sig_val = float(sigma.iloc[-1])
    if sig_val <= 0: return None

    lower_2s   = vwap - 2.0 * sig_val
    vwap_slice = df["vwap"].iloc[-5:]
    if (vwap_slice.max() - vwap_slice.min()) / vwap > 0.0015: return None
    if last["low"]  > lower_2s: return None
    if last.name.strftime("%H:%M") > "14:45": return None

    body       = abs(last["close"] - last["open"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    upper_wick = last["high"] - max(last["open"], last["close"])

    if body       < last["close"] * 0.0003: return None
    if lower_wick < 2.0 * body:             return None
    if last["close"] < lower_2s:            return None
    if upper_wick > body:                   return None

    avg_vol = _avg_volume(df)
    if avg_vol > 0 and last["volume"] < 1.5 * avg_vol: return None

    entry  = round(float(last["close"]), 2)
    sl     = round(float(last["low"]) - 0.01, 2)
    risk   = round(entry - sl, 2)
    if risk <= 0 or risk / entry < 0.001: return None

    return {
        "pattern":    "HAM2S",
        "entry_time": last.name.strftime("%H:%M"),
        "entry":      entry,
        "sl":         sl,
        "target":     round(entry + 3.0 * risk, 2),
        "bar_ts":     _ts(last.name),
        "dip_pct":    round((vwap - last["low"]) / vwap * 100, 3),
    }


def _pattern_flag(df):
    """
    High-tight Bull Flag (strict):
    - Pole : 2-3 candles, spike ≥ 1.2%, ALL bullish, each closes in top 60% of its range
    - Flag : 3-6 candles, lower highs (drifting down), range ≤ 40% of pole
    - Break: close above flag high, above VWAP, volume ≥ 1.2× avg, only before 13:30
    - SL   : just below flag low (max 0.8% below entry)
    - Target: pole height from entry, capped at 5R
    """
    if len(df) < 9: return None

    last = df.iloc[-1]
    if last.name.strftime("%H:%M") > "14:00": return None  # needs time to reach target
    if last["close"] <= last["open"]: return None           # breakout must be bullish
    if last["close"] <= last["vwap"]: return None           # must be above VWAP

    for flag_len in range(3, 7):
        f0 = len(df) - 1 - flag_len
        if f0 < 2: continue

        flag_bars = df.iloc[f0 : len(df) - 1]       # consolidation candles
        pole_bars = df.iloc[max(0, f0 - 3) : f0]    # max 3 bars — sharp spike only

        if len(flag_bars) < 3 or len(pole_bars) < 2: continue

        # Flag: lower highs (downward drift)
        if flag_bars.iloc[0]["high"] <= flag_bars.iloc[-1]["high"]: continue

        flag_high  = float(flag_bars["high"].max())
        flag_low   = float(flag_bars["low"].min())
        flag_range = flag_high - flag_low

        # Breakout: close clears the flag high
        if last["close"] <= flag_high: continue

        # Pole: ALL candles bullish, each closes in top 55% of its range (no grinding)
        if not (pole_bars["close"] > pole_bars["open"]).all(): continue

        pole_clean = True
        for _, pc in pole_bars.iterrows():
            cr = float(pc["high"]) - float(pc["low"])
            if cr > 0 and (float(pc["close"]) - float(pc["low"])) / cr < 0.55:
                pole_clean = False
                break
        if not pole_clean: continue

        pole_base = float(pole_bars.iloc[0]["open"])
        pole_top  = float(pole_bars.iloc[-1]["close"])
        pole_h    = pole_top - pole_base
        if pole_h <= 0 or pole_h / pole_base < 0.010: continue  # sharp move ≥ 1.0%

        # Flag tight: range ≤ 50% of pole, retracement ≤ 55% of pole
        if flag_range > pole_h * 0.50: continue
        if flag_low < pole_top - pole_h * 0.55: continue

        # Volume expansion on breakout
        avg_vol = _avg_volume(df)
        if avg_vol > 0 and last["volume"] < 1.2 * avg_vol: continue

        entry = float(last["close"])
        sl    = round(flag_low - 0.01, 2)
        risk  = entry - sl
        if risk <= 0 or risk / entry < 0.001: continue
        if risk / entry > 0.010: continue  # SL too wide → flag not tight enough

        target = round(entry + min(pole_h, 5 * risk), 2)

        return {
            "pattern":    "FLAG",
            "entry_time": last.name.strftime("%H:%M"),
            "entry":      round(entry, 2),
            "sl":         round(sl, 2),
            "target":     target,
            "bar_ts":     _ts(last.name),
            "pole_pct":   round(pole_h / pole_base * 100, 2),
        }

    return None


def _pattern_tri(df):
    """
    Ascending Triangle (textbook definition):
    - Find flat resistance: ≥3 highs within 0.2% of the same level, spread across triangle
    - Between each pair of consecutive resistance tests, the trough (lowest low) must be
      higher than the previous trough — this IS the ascending triangle (buyers more aggressive)
    - Breakout: close > resistance + above VWAP + volume ≥ 1.5× avg
    - SL  : just below the last inter-touch trough (most recent higher low)
    - Target: triangle height (resistance − first trough) projected from entry
    """
    if len(df) < 13: return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    if last.name.strftime("%H:%M") > "14:00": return None
    if last["close"] <= last["open"]: return None
    if last["close"] <= last["vwap"]: return None

    for lookback in range(10, min(31, len(df))):
        tri = df.iloc[-(lookback + 1):-1]
        if len(tri) < 8: continue

        highs = tri["high"].values
        lows  = tri["low"].values

        # ── Step 1: Flat resistance ──────────────────────────────────────────────
        res_lvl = float(np.median(sorted(highs, reverse=True)[:3]))
        if res_lvl <= 0: continue

        # Collect indices of every bar that touches/tests resistance
        touch_idx = [i for i, h in enumerate(highs) if abs(h - res_lvl) / res_lvl <= 0.002]
        if len(touch_idx) < 3: continue

        # Touches must be spread across the triangle, not all bunched at one end
        if touch_idx[-1] - touch_idx[0] < len(tri) // 2: continue

        # ── Step 2: Rising inter-touch troughs (the real ascending triangle check) ──
        # Between each pair of consecutive resistance tests find the lowest low (trough).
        # Every trough must be higher than the previous one — buyers stepping in higher.
        inter_troughs = []
        for k in range(len(touch_idx) - 1):
            seg_lows = lows[touch_idx[k]: touch_idx[k + 1] + 1]
            inter_troughs.append(float(seg_lows.min()))

        if len(inter_troughs) < 2: continue

        # Every consecutive trough must rise by at least 0.2%
        if not all(inter_troughs[i + 1] > inter_troughs[i] * 1.002
                   for i in range(len(inter_troughs) - 1)):
            continue

        # ── Step 3: Late-entry guard & breakout ─────────────────────────────────
        if float(prev["close"]) > res_lvl * 1.002: continue
        if float(last["close"]) <= res_lvl * 1.002: continue

        # ── Step 4: Volume expansion on breakout ────────────────────────────────
        avg_vol = _avg_volume(df)
        if avg_vol > 0 and last["volume"] < 1.5 * avg_vol: continue

        # ── Step 5: Triangle metrics ─────────────────────────────────────────────
        tri_height = res_lvl - inter_troughs[0]   # height from first trough to resistance
        if tri_height <= 0 or tri_height / res_lvl < 0.005: continue

        entry = float(last["close"])
        sl    = round(inter_troughs[-1] - 0.01, 2)  # below the most recent higher low
        risk  = entry - sl
        if risk <= 0 or risk / entry < 0.001: continue
        if risk / entry > 0.012: continue

        target = round(entry + min(tri_height, 5 * risk), 2)

        return {
            "pattern":    "TRI",
            "entry_time": last.name.strftime("%H:%M"),
            "entry":      round(entry, 2),
            "sl":         round(sl, 2),
            "target":     target,
            "bar_ts":     _ts(last.name),
            "tri_h_pct":  round(tri_height / res_lvl * 100, 2),
            "touches":    len(touch_idx),
        }

    return None


def _pattern_vcnb(df):
    """
    VWAP Consolidation Breakout (VCNB):
    - Prior uptrend : at least 2 of the last 3 bars closed above VWAP
    - Tight base    : 3-bar consolidation range < 4× avg bar range of TODAY's session
    - Breakout bar  : green + closes above VWAP + closes above the 5-bar high
    - Volume        : breakout bar volume >= 1.3× 20-bar average (institutional push)
    - Time          : 10:00–13:00 only (after 13:00 not enough runway for 2× target)
    - SL            : below consolidation low (0.2% buffer)
    - Target        : entry + 2× risk (2:1 RR, validated at 36.7% WR out-of-sample)
    """
    if len(df) < 8: return None

    last = df.iloc[-1]
    t    = last.name.strftime("%H:%M")
    if t < "10:00" or t > "13:00": return None    # 13:00 cutoff — need runway for 2× target
    if last["close"] <= last["open"]: return None
    if last["close"] <= last["vwap"]: return None

    # Breaks above the prior-5-bar high (new local push)
    prior5 = df.iloc[-6:-1]
    if len(prior5) < 5: return None
    if float(last["high"]) <= float(prior5["high"].max()): return None

    # Prior 3 bars: at least 2 of 3 closed above VWAP (uptrend context)
    prior3 = df.iloc[-4:-1]
    if len(prior3) < 3: return None
    above_count = sum(
        float(b["close"]) > float(b["vwap"])
        for _, b in prior3.iterrows()
        if not pd.isna(b["vwap"])
    )
    if above_count < 2: return None

    # Tight consolidation: use TODAY's bars only for range baseline
    # (avoids cross-day window inflating the range reference)
    last_date  = last.name.date()
    today_df   = df[[d == last_date for d in df.index.date]]
    if len(today_df) < 3:
        return None
    sess_range = (float(today_df["high"].max()) - float(today_df["low"].min())) / max(1, len(today_df))
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
        "entry_time": last.name.strftime("%H:%M"),
        "entry":      round(entry, 2),
        "sl":         round(sl, 2),
        "target":     target,
        "bar_ts":     _ts(last.name),
        "consol_pct": round(p3_range / entry * 100, 2),
    }


def _pattern_open_rcl(df):
    """
    Opening VWAP Reclaim (OPEN_RCL):
    - Previous day closed in TOP 40% of its day range (genuinely strong close, not mediocre)
    - Stock opens weak: 1-3 early same-day bars close at or below VWAP
    - Dip genuine: at least one bar closes ≥ 0.1% below VWAP
    - Reclaim bar: green + majority of body above VWAP + close in top 50% of bar range
    - Volume: reclaim bar ≥ 1.5× 20-bar average (strong buying conviction)
    - Time: 09:25–09:35 ONLY (2nd or 3rd bar)
    - SL: below dip low (0.2% buffer)  |  Target: 2× risk (more achievable intraday)
    """
    if len(df) < 3: return None
    last = df.iloc[-1]
    t    = last.name.strftime("%H:%M")
    if t < "09:25" or t > "09:35": return None

    if last["close"] <= last["open"]: return None
    if last["close"] <= last["vwap"]: return None
    if (last["open"] + last["close"]) / 2 <= last["vwap"]: return None

    # Reclaim bar close must be in top 50% of its range (strong buyers, not a doji)
    bar_range = float(last["high"]) - float(last["low"])
    if bar_range > 0 and (float(last["close"]) - float(last["low"])) / bar_range < 0.50:
        return None

    # Previous day must have closed in top 40% of day's range (genuinely strong, not mediocre)
    last_date  = last.name.date()
    prev_bars  = df[[d < last_date for d in df.index.date]]
    if prev_bars.empty: return None
    prev_day_date = prev_bars.index[-1].date()
    prev_day = prev_bars[[d == prev_day_date for d in prev_bars.index.date]]
    if prev_day.empty: return None
    pd_high = float(prev_day["high"].max())
    pd_low  = float(prev_day["low"].min())
    pd_close = float(prev_day.iloc[-1]["close"])
    pd_range = pd_high - pd_low
    if pd_range <= 0: return None
    if (pd_close - pd_low) / pd_range < 0.60: return None  # top 40% of yesterday's range

    n_below     = 0
    min_low     = float("inf")
    max_dip_pct = 0.0
    for i in range(len(df) - 2, max(len(df) - 5, -1), -1):
        c = df.iloc[i]
        if c.name.date() != last_date: break
        if float(c["close"]) <= float(c["vwap"]):
            n_below     += 1
            min_low      = min(min_low, float(c["low"]))
            dip          = (float(c["vwap"]) - float(c["close"])) / float(c["vwap"])
            max_dip_pct  = max(max_dip_pct, dip)
        else:
            break

    if n_below < 1: return None
    if max_dip_pct < 0.001: return None

    # Volume must be 1.5× avg — genuine institutional reclaim, not a drift back
    avg_vol = _avg_volume(df)
    if avg_vol > 0 and last["volume"] < 1.5 * avg_vol: return None

    entry = float(last["close"])
    sl    = round(min_low * 0.998, 2)
    risk  = entry - sl
    if risk <= 0 or risk / entry < 0.002: return None
    if risk / entry > 0.012: return None   # tighter max risk
    target = round(entry + 2.0 * risk, 2)  # 2:1 — more achievable intraday

    return {
        "pattern":    "OPEN_RCL",
        "entry_time": last.name.strftime("%H:%M"),
        "entry":      round(entry, 2),
        "sl":         round(sl, 2),
        "target":     target,
        "bar_ts":     _ts(last.name),
        "dip_pct":    round(max_dip_pct * 100, 3),
    }


def _pattern_dtri(df):
    """
    Descending Triangle — bullish upward breakout (87% success rate):
    - Support   : flat bottom — ≥3 lows within 0.2% of same level, spread across triangle
    - Resistance: descending — between each pair of support tests, the rally peak must be
                  LOWER than the previous peak (sellers losing steam, buyers holding firm)
    - Breakout  : close above last (lowest) peak + above VWAP + volume ≥ 1.5× avg
    - SL        : just below flat support level (0.2% buffer)
    - Target    : triangle height (first peak − support) projected from entry, capped at 5R
    """
    if len(df) < 13: return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    if last.name.strftime("%H:%M") > "14:00": return None
    if last["close"] <= last["open"]: return None
    if last["close"] <= last["vwap"]: return None

    for lookback in range(10, min(31, len(df))):
        tri = df.iloc[-(lookback + 1):-1]
        if len(tri) < 8: continue

        highs = tri["high"].values
        lows  = tri["low"].values

        # ── Step 1: Flat support ─────────────────────────────────────────────
        # Median of bottom-3 lows as candidate support level
        sup_lvl = float(np.median(sorted(lows)[:3]))
        if sup_lvl <= 0: continue

        # Find all bars whose low tests the support level (within 0.2%)
        touch_idx = [i for i, l in enumerate(lows) if abs(l - sup_lvl) / sup_lvl <= 0.002]
        if len(touch_idx) < 3: continue

        # Touches must be spread across the triangle (not bunched at one end)
        if touch_idx[-1] - touch_idx[0] < len(tri) // 2: continue

        # ── Step 2: Descending inter-touch peaks ─────────────────────────────
        # Between each pair of consecutive support tests, find the highest high (rally peak).
        # Each peak must be LOWER than the previous — sellers are making lower highs.
        inter_peaks = []
        for k in range(len(touch_idx) - 1):
            seg = highs[touch_idx[k]: touch_idx[k + 1] + 1]
            inter_peaks.append(float(seg.max()))

        if len(inter_peaks) < 2: continue

        # Every peak must decline by at least 0.2% from the previous
        if not all(inter_peaks[i + 1] < inter_peaks[i] * 0.998
                   for i in range(len(inter_peaks) - 1)):
            continue

        # ── Step 3: Late-entry guard & breakout ─────────────────────────────
        res_line = inter_peaks[-1]  # most recent (lowest) peak = current resistance
        if float(prev["close"]) > res_line * 1.002: continue     # already broken out
        if float(last["close"]) <= res_line * 1.002: continue    # hasn't broken yet

        # ── Step 4: Volume expansion on breakout ────────────────────────────
        avg_vol = _avg_volume(df)
        if avg_vol > 0 and last["volume"] < 1.5 * avg_vol: continue

        # ── Step 5: Triangle metrics ─────────────────────────────────────────
        tri_height = inter_peaks[0] - sup_lvl   # widest point: first peak − support
        if tri_height <= 0 or tri_height / sup_lvl < 0.005: continue

        entry = float(last["close"])
        sl    = round(sup_lvl * 0.998 - 0.01, 2)   # just below flat support
        risk  = entry - sl
        if risk <= 0 or risk / entry < 0.001: continue
        if risk / entry > 0.015: continue

        target = round(entry + min(tri_height, 5 * risk), 2)

        return {
            "pattern":    "DTRI",
            "entry_time": last.name.strftime("%H:%M"),
            "entry":      round(entry, 2),
            "sl":         round(sl, 2),
            "target":     target,
            "bar_ts":     _ts(last.name),
            "tri_h_pct":  round(tri_height / sup_lvl * 100, 2),
            "touches":    len(touch_idx),
        }

    return None


_PATTERN_FNS = {
    "B":        _pattern_b,
    "ENG":      _pattern_eng,
    "HAM":      _pattern_ham,
    "MAR":      _pattern_mar,
    "HAM2S":    _pattern_ham2s,
    "FLAG":     _pattern_flag,
    "TRI":      _pattern_tri,
    "DTRI":     _pattern_dtri,
    "VCNB":     _pattern_vcnb,
    "OPEN_RCL": _pattern_open_rcl,
}


def _detect_first(df_slice, patterns):
    for name in patterns:
        fn = _PATTERN_FNS.get(name)
        if fn is None:
            continue
        result = fn(df_slice)
        if result is not None:
            return result
    return None


def _scan_day(day_df: pd.DataFrame, patterns: list, capital: float) -> list:
    """Return list with at most one trade per day (first pattern that fires)."""
    for i in range(2, len(day_df)):
        df_slice = day_df.iloc[:i + 1]
        result   = _detect_first(df_slice, patterns)
        if result is None:
            continue

        entry  = result["entry"]
        sl     = result["sl"]
        target = result["target"]

        future     = day_df.iloc[i + 1:]
        outcome    = "OPEN"
        exit_price = float(day_df.iloc[-1]["close"])
        exit_time  = day_df.index[-1].strftime("%H:%M")
        exit_ts    = _ts(day_df.index[-1])

        for ts, row in future.iterrows():
            if row["low"] <= sl:
                outcome = "SL"
                exit_price = sl
                exit_time  = ts.strftime("%H:%M")
                exit_ts    = _ts(ts)
                break
            if row["high"] >= target:
                outcome = "WIN"
                exit_price = target
                exit_time  = ts.strftime("%H:%M")
                exit_ts    = _ts(ts)
                break

        shares = int(capital / entry) if entry > 0 else 0
        pnl    = round((exit_price - entry) * shares, 2)

        result["date"]        = str(day_df.index[0].date())
        result["outcome"]     = outcome
        result["exit_time"]   = exit_time
        result["exit_price"]  = round(exit_price, 2)
        result["exit_ts"]     = exit_ts
        result["shares"]      = shares
        result["pnl"]         = pnl
        return [result]

    return []


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/api/bt/stocks")
def get_stocks():
    files   = glob.glob(os.path.join(DATA_DIR, "*.parquet"))
    symbols = sorted(os.path.basename(f).replace(".parquet", "") for f in files)
    return {"symbols": symbols}


@app.get("/api/bt/dates/{symbol}")
def get_dates(symbol: str):
    df    = _load(symbol)
    dates = sorted(str(d) for d in set(df.index.date))
    return {"dates": dates}


@app.get("/api/bt/candles/{symbol}")
def get_candles(symbol: str):
    """Return all candles + VWAP + RSI(14) for the full date range."""
    df = _add_vwap(_load(symbol))
    df["rsi"] = _calc_rsi(df["close"])
    if df.empty:
        return {"candles": [], "vwap": [], "rsi": []}

    candles  = []
    vwap_pts = []
    rsi_pts  = []
    prev_date = None

    for ts, r in df.iterrows():
        t = _ts(ts)
        candles.append({
            "time":  t,
            "open":  float(r["open"]),
            "high":  float(r["high"]),
            "low":   float(r["low"]),
            "close": float(r["close"]),
        })
        cur_date = ts.date()
        if prev_date is not None and cur_date != prev_date:
            vwap_pts.append({"time": t - 1})
            rsi_pts.append({"time": t - 1})
        vwap_pts.append({"time": t, "value": float(r["vwap"])})
        rsi_val = r["rsi"]
        if not pd.isna(rsi_val):
            rsi_pts.append({"time": t, "value": round(float(rsi_val), 1)})
        prev_date = cur_date

    return {"candles": candles, "vwap": vwap_pts, "rsi": rsi_pts}


class BacktestPayload(BaseModel):
    symbols:   list      = []          # list of symbols to backtest
    patterns:  list      = ["B", "ENG", "HAM", "MAR", "HAM2S", "FLAG", "TRI", "DTRI", "VCNB", "OPEN_RCL"]
    capital:   float     = 200_000
    date_from: Optional[str] = None
    date_to:   Optional[str] = None


def _run_one(symbol: str, patterns: list, capital: float,
             date_from=None, date_to=None) -> list:
    """Scan full symbol df with a cross-day sliding window.
    Lookback of 50 bars (~2 sessions) lets TRI detect triangles that span 2 days.
    Intraday patterns (B, ENG, etc.) are unaffected — their internal VWAP checks
    still use each bar's own daily VWAP value from _add_vwap.
    Exit is always intraday (rest of the entry day, same as before)."""
    try:
        df = _add_vwap(_load(symbol))
    except HTTPException:
        return []
    if date_from:
        df = df[df.index.date >= pd.Timestamp(date_from).date()]
    if date_to:
        df = df[df.index.date <= pd.Timestamp(date_to).date()]

    df_sess = df.between_time("09:15", "15:20")
    if len(df_sess) < 3:
        return []

    trades      = []
    trade_dates = set()
    LOOKBACK    = 50  # ~2 sessions of 10-min bars

    for i in range(2, len(df_sess)):
        bar        = df_sess.iloc[i]
        entry_date = str(bar.name.date())

        if entry_date in trade_dates:
            continue

        df_slice = df_sess.iloc[max(0, i - LOOKBACK): i + 1]
        result   = _detect_first(df_slice, patterns)
        if result is None:
            continue

        entry  = result["entry"]
        sl     = result["sl"]
        target = result["target"]

        # Exit: intraday only — rest of bars in the entry day
        day_bars = df_sess[df_sess.index.date == bar.name.date()]
        future   = day_bars[day_bars.index > bar.name]

        outcome    = "OPEN"
        exit_price = float(day_bars.iloc[-1]["close"])
        exit_time  = day_bars.index[-1].strftime("%H:%M")
        exit_ts_v  = _ts(day_bars.index[-1])

        for ts_row, row in future.iterrows():
            if row["low"] <= sl:
                outcome    = "SL"
                exit_price = sl
                exit_time  = ts_row.strftime("%H:%M")
                exit_ts_v  = _ts(ts_row)
                break
            if row["high"] >= target:
                outcome    = "WIN"
                exit_price = target
                exit_time  = ts_row.strftime("%H:%M")
                exit_ts_v  = _ts(ts_row)
                break

        shares = int(capital / entry) if entry > 0 else 0
        pnl    = round((exit_price - entry) * shares, 2)

        result.update({
            "date":       entry_date,
            "outcome":    outcome,
            "exit_time":  exit_time,
            "exit_price": round(exit_price, 2),
            "exit_ts":    exit_ts_v,
            "shares":     shares,
            "pnl":        pnl,
            "symbol":     symbol,
        })

        trades.append(result)
        trade_dates.add(entry_date)

    return trades


def _build_summary(all_trades: list) -> dict:
    wins      = sum(1 for t in all_trades if t["outcome"] == "WIN")
    losses    = sum(1 for t in all_trades if t["outcome"] == "SL")
    total     = len(all_trades)
    total_pnl = round(sum(t["pnl"] for t in all_trades), 2)
    win_rate  = round(wins / total * 100, 1) if total else 0

    by_pat: dict = {}
    by_sym: dict = {}

    for t in all_trades:
        for key, bucket in [("pattern", by_pat), ("symbol", by_sym)]:
            k = t[key]
            if k not in bucket:
                bucket[k] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
            bucket[k]["trades"]  += 1
            bucket[k]["wins"]    += 1 if t["outcome"] == "WIN" else 0
            bucket[k]["losses"]  += 1 if t["outcome"] == "SL"  else 0
            bucket[k]["pnl"]     += t["pnl"]

    for d in (by_pat, by_sym):
        for k in d:
            d[k]["pnl"] = round(d[k]["pnl"], 2)
            d[k]["wr"]  = round(d[k]["wins"] / d[k]["trades"] * 100, 1) if d[k]["trades"] else 0

    return {
        "total":      total,
        "wins":       wins,
        "losses":     losses,
        "open":       total - wins - losses,
        "win_rate":   win_rate,
        "total_pnl":  total_pnl,
        "by_pattern": by_pat,
        "by_symbol":  by_sym,
    }


@app.post("/api/bt/run")
def run_backtest(payload: BacktestPayload):
    all_trades: list = []
    for sym in payload.symbols:
        all_trades.extend(_run_one(sym, payload.patterns, payload.capital,
                                   payload.date_from, payload.date_to))

    return {
        "symbols": payload.symbols,
        "trades":  all_trades,
        "summary": _build_summary(all_trades),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backtest_server:app", host="0.0.0.0", port=8002, reload=False)

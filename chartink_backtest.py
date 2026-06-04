"""
chartink_backtest.py — Backtest ChartInk Supertrend+VWAP Convergence scanner results.

Strategy:
  For each stock that first appeared in the ChartInk scanner on a given day,
  fetches Upstox 10-min OHLCV + VWAP data and simulates a 1:3 R:R trade:
    Entry  = Close of the signal candle (price when ChartInk fired)
    SL     = VWAP at that candle
    Target = Entry + 3 × (Entry - SL)
  Checks subsequent candles until SL hit, target hit, or EOD close.

Usage:
  python chartink_backtest.py
  python chartink_backtest.py --file "Backtest supertrend and convergence.csv"
  python chartink_backtest.py --cutoff 13:00   # only signals fired before 1 PM
  python chartink_backtest.py --capital 200000  # trade capital per position
  python chartink_backtest.py --workers 8
"""

import os
import sys
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from instruments import load_instruments
from data_fetcher import _fetch_historical
from indicators import calculate_vwap

import numpy as np

ROOT          = os.path.dirname(os.path.abspath(__file__))
CHUNK_DAYS    = 1  # fetch one day at a time for precision


# ── Pattern helpers (copied from test.py) ──────────────────────────────────────

def _avg_volume(df, n=20):
    if "volume" not in df.columns or len(df) < 2:
        return 0.0
    vols = df["volume"].iloc[max(0, len(df) - n - 1):-1]
    vols = vols[vols > 0]
    return float(vols.mean()) if len(vols) > 0 else 0.0

def _calc_vwap_sigma(df):
    if len(df) < 3 or "volume" not in df.columns:
        return None
    tp      = (df["high"] + df["low"] + df["close"]) / 3
    vol     = df["volume"].clip(lower=0)
    cum_vol = vol.cumsum().replace(0, np.nan)
    vwap_cv = (tp * vol).cumsum() / cum_vol
    var_cv  = (tp ** 2 * vol).cumsum() / cum_vol - vwap_cv ** 2
    return var_cv.clip(lower=0).apply(np.sqrt).fillna(0.0)

def _sig(pattern, ref_candle, entry_candle, extra=None):
    entry = entry_candle["close"]; sl = entry_candle["vwap"]; risk = entry - sl
    if risk <= 0: return None
    d = {
        "pattern":    pattern,
        "entry_time": entry_candle.name.strftime("%H:%M"),
        "entry": round(entry, 2), "sl": round(sl, 2),
        "target": round(entry + 3 * risk, 2),
        "risk": round(risk, 2), "reward": round(3 * risk, 2),
    }
    if extra: d.update(extra)
    return d

def _pattern_b(df):
    if len(df) < 3: return None
    last = df.iloc[-1]
    if last["close"] <= last["vwap"]: return None
    if last["close"] <= last["open"]: return None
    if (last["open"] + last["close"]) / 2 <= last["vwap"]: return None
    n_below = 0; max_dip_pct = 0.0; first_breach_idx = None
    for i in range(len(df) - 2, max(len(df) - 5, -1), -1):
        c = df.iloc[i]
        if c["close"] < c["vwap"]:
            n_below += 1
            dip = (c["vwap"] - c["close"]) / c["vwap"]
            if dip > max_dip_pct: max_dip_pct = dip
            first_breach_idx = i
        else:
            break
    if not (1 <= n_below <= 3): return None
    if max_dip_pct < 0.0015: return None
    if first_breach_idx is None: return None
    first_breach = df.iloc[first_breach_idx]
    if (first_breach["open"] - first_breach["vwap"]) / first_breach["vwap"] < 0.0015: return None
    entry = last["close"]; sl = last["vwap"]; risk = entry - sl
    if risk / entry < 0.003: return None
    before_idx = len(df) - 2 - n_below
    if before_idx < 0: return None
    if df.iloc[before_idx]["close"] <= df.iloc[before_idx]["vwap"]: return None
    breach = df.iloc[len(df) - 1 - n_below]
    return _sig("B", breach, last, {"candles_below": n_below})

def _pattern_eng(df):
    if len(df) < 6: return None
    last = df.iloc[-1]; prev = df.iloc[-2]
    if last["close"] <= last["open"]: return None
    if last["close"] <= last["vwap"]: return None
    if prev["close"] >= prev["open"]: return None
    if prev["low"]   >  prev["vwap"]: return None
    if prev["open"]  <  prev["vwap"]: return None
    if last["open"]  >  prev["close"]: return None
    if last["close"] <  prev["open"]:  return None
    pre_dip = df.iloc[-6:-2]
    if len(pre_dip) < 3: return None
    if (pre_dip["close"] > pre_dip["vwap"]).sum() < 3: return None
    if float(last["vwap"]) < float(df.iloc[-5]["vwap"]) * 1.001: return None
    avg_vol = _avg_volume(df)
    if avg_vol > 0 and df["volume"].iloc[-1] < 1.5 * avg_vol: return None
    if (last["close"] - last["vwap"]) / last["close"] < 0.003: return None
    return _sig("ENG", prev, last, {})

def _pattern_ham(df):
    if len(df) < 5: return None
    last = df.iloc[-1]
    if last["close"] <= last["vwap"]: return None
    body       = abs(last["close"] - last["open"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    upper_wick = last["high"] - max(last["open"], last["close"])
    if body < last["close"] * 0.0005:     return None
    if lower_wick < 2.0 * body:           return None
    if last["low"] > last["vwap"]:        return None
    if upper_wick > body:                 return None
    if lower_wick / last["vwap"] < 0.003: return None
    if df.iloc[-2]["close"] <= df.iloc[-2]["vwap"]: return None
    if df.iloc[-3]["close"] <= df.iloc[-3]["vwap"]: return None
    if float(last["vwap"]) < float(df.iloc[-5]["vwap"]) * 1.001: return None
    if (last["close"] - last["vwap"]) / last["close"] < 0.003: return None
    avg_vol = _avg_volume(df)
    if avg_vol > 0 and df["volume"].iloc[-1] < avg_vol: return None
    return _sig("HAM", last, last, {})

def _pattern_mar(df):
    if len(df) < 2: return None
    last = df.iloc[-1]
    if last["close"] <= last["open"]: return None
    if last["open"]  >= last["vwap"]: return None
    if last["close"] <= last["vwap"]: return None
    if (last["close"] - last["vwap"]) / last["vwap"] < 0.002: return None
    body = last["close"] - last["open"]
    if body <= 0: return None
    if (last["high"] - last["close"]) > 0.25 * body: return None
    if (last["open"] - last["low"])   > 0.25 * body: return None
    if df.iloc[-2]["close"] >= df.iloc[-2]["vwap"]: return None
    avg_vol = _avg_volume(df)
    if avg_vol <= 0: return None
    if df["volume"].iloc[-1] < 3.0 * avg_vol: return None
    if (last["close"] - last["vwap"]) / last["close"] < 0.003: return None
    return _sig("MAR", df.iloc[-2], last, {})

def _pattern_ham2s(df):
    if len(df) < 5: return None
    sigma = _calc_vwap_sigma(df)
    if sigma is None: return None
    last = df.iloc[-1]; vwap = last["vwap"]
    sig_val = float(sigma.iloc[-1])
    if sig_val <= 0: return None
    lower_2s = vwap - 2.0 * sig_val
    if (df["vwap"].iloc[-5:].max() - df["vwap"].iloc[-5:].min()) / vwap > 0.0015: return None
    if last["low"] > lower_2s: return None
    if last.name.strftime("%H:%M") > "14:45": return None
    body       = abs(last["close"] - last["open"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    upper_wick = last["high"] - max(last["open"], last["close"])
    if body < last["close"] * 0.0003: return None
    if lower_wick < 2.0 * body:       return None
    if last["close"] < lower_2s:      return None
    if upper_wick > body:             return None
    avg_vol = _avg_volume(df)
    if avg_vol > 0 and last["volume"] < 1.5 * avg_vol: return None
    entry = round(last["close"], 2); sl = round(last["low"] - 0.01, 2)
    risk = round(entry - sl, 2)
    if risk <= 0 or risk / entry < 0.001: return None
    return {"pattern": "HAM2S", "entry": entry, "sl": sl,
            "target": round(entry + 3 * risk, 2), "risk": risk}

def _detect_pattern(df_slice):
    """Run all active patterns on the slice, return the first that fires (or None)."""
    return (
        _pattern_b(df_slice)    or
        _pattern_eng(df_slice)  or
        _pattern_ham(df_slice)  or
        _pattern_mar(df_slice)  or
        _pattern_ham2s(df_slice)
    )


# ── Candle helpers ─────────────────────────────────────────────────────────────

def _resample_10min(df_1min: pd.DataFrame) -> pd.DataFrame:
    """Resample 1-min candles to 10-min with same alignment as main app."""
    if df_1min.empty:
        return pd.DataFrame()
    df = df_1min.resample(
        "10min", offset="5min", closed="left", label="left"
    ).agg(
        open=("open",   "first"),
        high=("high",   "max"),
        low=("low",    "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["close"])
    return df.between_time("09:15", "15:20")


def _fetch_day(instrument_key: str, trade_date: date) -> pd.DataFrame:
    """Fetch 10-min candles for one trading day, with VWAP column."""
    ds = trade_date.strftime("%Y-%m-%d")
    df_1m = _fetch_historical(instrument_key, "1minute", ds, ds)
    if df_1m.empty:
        return pd.DataFrame()
    df = _resample_10min(df_1m)
    if df.empty:
        return pd.DataFrame()
    # Filter to the requested day (timezone-aware timestamps from Upstox)
    day_mask = [idx.date() == trade_date for idx in df.index]
    df = df[day_mask].copy()
    if df.empty:
        return pd.DataFrame()
    df["vwap"] = calculate_vwap(df)
    return df.dropna(subset=["vwap"])


# ── Trade simulation ───────────────────────────────────────────────────────────

def _simulate(entry_candle_label: str, day_df: pd.DataFrame, capital: float):
    """
    Find the signal candle by its label time, derive entry/SL/target,
    then walk forward candle by candle to determine outcome.

    ChartInk fires at candle CLOSE — e.g. "10:55" means the 10:45–10:55
    candle just closed.  Our 10-min labels are the LEFT edge, so the candle
    that just closed is the last one whose label is STRICTLY before the
    ChartInk time.
    """
    # Find the signal candle: last candle with label < chartink_time
    mask  = day_df.index.strftime("%H:%M") < entry_candle_label
    avail = day_df[mask]
    if avail.empty:
        return None

    sig_bar  = avail.iloc[-1]
    entry    = sig_bar["close"]
    sl       = sig_bar["vwap"]
    risk     = entry - sl

    if risk <= 0 or risk / entry < 0.001:   # skip if VWAP is above or too close
        return None

    target     = round(entry + 3.0 * risk, 2)
    sig_label  = sig_bar.name.strftime("%H:%M")

    # Walk forward from the next candle
    future     = day_df[day_df.index > sig_bar.name]
    outcome    = "IN_TRADE"
    exit_price = float(day_df.iloc[-1]["close"])
    exit_label = day_df.index[-1].strftime("%H:%M")

    for ts, row in future.iterrows():
        if row["low"] <= sl:
            outcome    = "SL_HIT"
            exit_price = sl
            exit_label = ts.strftime("%H:%M")
            break
        if row["high"] >= target:
            outcome    = "TARGET_HIT"
            exit_price = target
            exit_label = ts.strftime("%H:%M")
            break

    shares = int(capital / entry) if entry > 0 else 0
    pnl    = round((exit_price - entry) * shares, 2)

    return {
        "signal_label": sig_label,
        "entry":        round(entry,    2),
        "sl":           round(sl,       2),
        "target":       round(target,   2),
        "risk_pct":     round(risk / entry * 100, 3),
        "outcome":      outcome,
        "exit_label":   exit_label,
        "exit_price":   round(exit_price, 2),
        "shares":       shares,
        "pnl":          pnl,
        "pnl_pct":      round((exit_price - entry) / entry * 100, 2),
    }


# ── Full-day VWAP pattern scan ─────────────────────────────────────────────────

def _scan_day_patterns(day_df: pd.DataFrame, capital: float, from_time: str = None) -> dict | None:
    """
    Walk every candle of the day. At each bar, check if any VWAP pattern fires
    using all candles up to and including that bar. Return the FIRST match with
    its simulated 1:3 R:R outcome, or None if no pattern fires all day.

    from_time: if given (e.g. "10:55"), only start looking at candles at or
               after that time — models "ChartInk fires, then we watch for pattern".
               Full candle history is still used for VWAP/volume calculations.
    """
    for i in range(2, len(day_df)):          # need at least 3 bars for any pattern
        if from_time and day_df.index[i].strftime("%H:%M") < from_time:
            continue                          # too early — ChartInk hasn't fired yet
        df_slice = day_df.iloc[:i + 1]
        pat = _detect_pattern(df_slice)
        if pat is None:
            continue

        entry  = pat["entry"]
        sl     = pat["sl"]
        target = pat["target"]
        risk   = entry - sl
        if risk <= 0 or risk / entry < 0.001:
            continue                          # invalid signal, keep scanning

        signal_bar   = day_df.iloc[i]
        signal_label = signal_bar.name.strftime("%H:%M")

        # Walk forward from the NEXT candle
        future     = day_df.iloc[i + 1:]
        outcome    = "IN_TRADE"
        exit_price = float(day_df.iloc[-1]["close"])
        exit_label = day_df.index[-1].strftime("%H:%M")

        for ts, row in future.iterrows():
            if row["low"] <= sl:
                outcome    = "SL_HIT"
                exit_price = sl
                exit_label = ts.strftime("%H:%M")
                break
            if row["high"] >= target:
                outcome    = "TARGET_HIT"
                exit_price = target
                exit_label = ts.strftime("%H:%M")
                break

        shares = int(capital / entry) if entry > 0 else 0
        pnl    = round((exit_price - entry) * shares, 2)

        return {
            "pat_pattern":      pat["pattern"],
            "pat_signal_label": signal_label,
            "pat_entry":        round(entry,      2),
            "pat_sl":           round(sl,         2),
            "pat_target":       round(target,     2),
            "pat_risk_pct":     round(risk / entry * 100, 3),
            "pat_outcome":      outcome,
            "pat_exit_label":   exit_label,
            "pat_exit_price":   round(exit_price, 2),
            "pat_shares":       shares,
            "pat_pnl":          pnl,
        }
    return None


# ── Per-position worker ────────────────────────────────────────────────────────

def _process(task: dict, capital: float) -> dict:
    """Fetch + simulate one (date, symbol, signal_time) task."""
    sym      = task["symbol"]
    ikey     = task["instrument_key"]
    tdate    = task["date"]
    sig_time = task["signal_time"]   # "10:55" string

    try:
        day_df = _fetch_day(ikey, tdate)
        if day_df.empty:
            return {**task, "status": "NO_DATA", "pnl": 0, "outcome": "NO_DATA"}

        sim = _simulate(sig_time, day_df, capital)
        if sim is None:
            return {**task, "status": "SKIP", "pnl": 0, "outcome": "SKIP",
                    "reason": "risk<=0 or VWAP above close"}

        # VWAP pattern scan — full trading day (ChartInk = universe, pattern = entry)
        pat_result = _scan_day_patterns(day_df, capital, from_time=None)

        base = {
            **task,
            "status":       "OK",
            "signal_label": sim["signal_label"],
            "entry":        sim["entry"],
            "sl":           sim["sl"],
            "target":       sim["target"],
            "risk_pct":     sim["risk_pct"],
            "outcome":      sim["outcome"],
            "exit_label":   sim["exit_label"],
            "exit_price":   sim["exit_price"],
            "shares":       sim["shares"],
            "pnl":          sim["pnl"],
            "pnl_pct":      sim["pnl_pct"],
        }
        if pat_result:
            base.update(pat_result)
        else:
            base["pat_pattern"] = "NONE"
        return base
    except Exception as e:
        return {**task, "status": "ERROR", "pnl": 0, "outcome": "ERROR", "reason": str(e)}


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest ChartInk VWAP+Supertrend signals")
    parser.add_argument(
        "--file",    default="Backtest supertrend and convergence (1).csv",
        help="ChartInk export CSV (default: the (1) file)"
    )
    parser.add_argument(
        "--file2",   default=None,
        help="Optional second CSV to merge (e.g. the other ChartInk export)"
    )
    parser.add_argument(
        "--cutoff",  default=None,
        help="Only include signals fired at or before this time, e.g. 13:00"
    )
    parser.add_argument("--capital",  type=float, default=200_000,
                        help="Capital per trade in INR (default: 200000)")
    parser.add_argument("--workers",  type=int,   default=6,
                        help="Parallel API workers (default: 6)")
    parser.add_argument("--no-csv",   action="store_true",
                        help="Skip saving output CSV")
    args = parser.parse_args()

    # ── Load ChartInk CSV(s) ───────────────────────────────────────────────────
    csv_path = os.path.join(ROOT, args.file)
    if not os.path.exists(csv_path):
        print(f"  ERROR: file not found — {csv_path}")
        sys.exit(1)

    raw = pd.read_csv(csv_path)
    if args.file2:
        csv2 = os.path.join(ROOT, args.file2)
        if os.path.exists(csv2):
            raw = pd.concat([raw, pd.read_csv(csv2)], ignore_index=True)
            print(f"  Merged two CSV files.")

    raw["dt"] = pd.to_datetime(raw["date"], format="%d-%m-%Y %I:%M %p")
    raw["trade_date"]  = raw["dt"].dt.date
    raw["signal_time"] = raw["dt"].dt.strftime("%H:%M")

    # Take FIRST signal per (date, symbol) pair
    first = (
        raw.sort_values("dt")
           .groupby(["trade_date", "symbol"], as_index=False)
           .first()
    )

    # Optional time cutoff
    if args.cutoff:
        before = len(first)
        first  = first[first["signal_time"] <= args.cutoff]
        print(f"  Cutoff {args.cutoff}: {before} -> {len(first)} signals kept")

    # ── Match to Upstox instruments ────────────────────────────────────────────
    inst_df  = load_instruments()
    inst_map = dict(zip(inst_df["symbol"], inst_df["instrument_key"]))

    tasks = []
    skipped_syms = []
    for _, row in first.iterrows():
        sym = row["symbol"]
        if sym not in inst_map:
            skipped_syms.append(sym)
            continue
        tasks.append({
            "symbol":         sym,
            "instrument_key": inst_map[sym],
            "date":           row["trade_date"],
            "signal_time":    row["signal_time"],
            "sector":         row.get("sector", ""),
        })

    unique_syms_missing = sorted(set(skipped_syms))
    print(f"\n  TejToro — ChartInk Backtest")
    print(f"  File      : {args.file}")
    print(f"  Signals   : {len(tasks)}  (skipped {len(set(skipped_syms))} unmatched: "
          f"{unique_syms_missing[:5]}{'...' if len(unique_syms_missing) > 5 else ''})")
    dates = sorted(set(t["date"] for t in tasks))
    print(f"  Days      : {len(dates)} ({dates[0]} to {dates[-1]})")
    print(f"  Capital   : INR {args.capital:,.0f} per trade")
    print(f"  Workers   : {args.workers}")
    print()

    # ── Parallel fetch + simulate ──────────────────────────────────────────────
    results = []
    done    = 0
    total   = len(tasks)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_process, t, args.capital): t for t in tasks}
        for fut in as_completed(futs):
            done += 1
            res = fut.result()
            results.append(res)
            sym  = res["symbol"]
            dt   = res["date"]
            st   = res.get("status", "?")
            oc   = res.get("outcome", "?")
            pnl  = res.get("pnl", 0)
            rt   = res.get("risk_pct", 0)
            sign = "+" if pnl >= 0 else ""
            tag  = f"[{done:4d}/{total}] {str(dt)} {sym:<16}"
            if st == "OK":
                print(f"  {tag} {oc:<12} risk={rt:.2f}%  P&L={sign}{pnl:>8,.0f}")
            elif st in ("NO_DATA", "ERROR"):
                print(f"  {tag} {st}  {res.get('reason','')}")
            time.sleep(0.1)   # courtesy delay between completions

    # ── Build results DataFrame ────────────────────────────────────────────────
    df = pd.DataFrame(results)
    ok = df[df["status"] == "OK"].copy()

    if ok.empty:
        print("  No valid trades simulated.")
        return

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — VWAP PATTERN TRADES  (ChartInk = universe, pattern = entry)
    # ══════════════════════════════════════════════════════════════════════════
    pat_ok = ok[ok["pat_pattern"] != "NONE"].copy() if "pat_pattern" in ok.columns else pd.DataFrame()

    print("\n" + "=" * 72)
    print("  SECTION 1 — VWAP PATTERN TRADES")
    print("  (ChartInk defines the universe; patterns decide when to enter)")
    print("=" * 72)

    if pat_ok.empty:
        print("  No VWAP patterns fired on any ChartInk stock today.")
    else:
        # Overall pattern stats
        pn  = len(pat_ok)
        ptg = (pat_ok["pat_outcome"] == "TARGET_HIT").sum()
        psl = (pat_ok["pat_outcome"] == "SL_HIT").sum()
        peo = (pat_ok["pat_outcome"] == "IN_TRADE").sum()
        pwr = ptg / (ptg + psl) * 100 if (ptg + psl) > 0 else 0
        ptp = pat_ok["pat_pnl"].sum()
        pap = pat_ok["pat_pnl"].mean()

        print(f"\n  Stocks with pattern     : {pn}  of {len(ok)} ChartInk stocks")
        print(f"  TARGET_HIT              : {ptg}  ({ptg/pn*100:.1f}%)")
        print(f"  SL_HIT                  : {psl}  ({psl/pn*100:.1f}%)")
        print(f"  EOD exit (open)         : {peo}  ({peo/pn*100:.1f}%)")
        print(f"  Win rate (excl EOD)     : {pwr:.1f}%  (breakeven = 25.0%)")
        print(f"  Net P&L                 : INR {ptp:+,.0f}")
        print(f"  Avg P&L / trade         : INR {pap:+,.0f}")

        # By pattern
        print("\n" + "-" * 72)
        print("  BY PATTERN")
        print("-" * 72)
        print(f"  {'Pattern':<10} {'Stocks':>7} {'Target':>7} {'SL':>5} {'EOD':>5} {'WR%':>6} {'Avg P&L':>10} {'Total P&L':>12}")
        print("-" * 72)
        for pat in ["B", "ENG", "HAM", "MAR", "HAM2S"]:
            g = pat_ok[pat_ok["pat_pattern"] == pat]
            if g.empty: continue
            nt  = len(g)
            tg  = (g["pat_outcome"] == "TARGET_HIT").sum()
            sl_ = (g["pat_outcome"] == "SL_HIT").sum()
            eo  = (g["pat_outcome"] == "IN_TRADE").sum()
            wr  = tg / (tg + sl_) * 100 if (tg + sl_) > 0 else 0
            ap  = g["pat_pnl"].mean()
            tp  = g["pat_pnl"].sum()
            sa  = "+" if ap >= 0 else ""
            st  = "+" if tp >= 0 else ""
            print(f"  {pat:<10} {nt:>7} {tg:>7} {sl_:>5} {eo:>5} {wr:>5.1f}%  {sa}{ap:>8,.0f}  {st}{tp:>10,.0f}")
        print("-" * 72)
        sa = "+" if pap >= 0 else ""
        st = "+" if ptp >= 0 else ""
        print(f"  {'TOTAL':<10} {pn:>7} {ptg:>7} {psl:>5} {peo:>5} {pwr:>5.1f}%  {sa}{pap:>8,.0f}  {st}{ptp:>10,.0f}")

        # By day for pattern trades
        print("\n" + "-" * 72)
        print("  BY DAY (pattern trades)")
        print("-" * 72)
        print(f"  {'Date':<12} {'Stocks':>7} {'Target':>7} {'SL':>5} {'EOD':>5} {'WR%':>6} {'P&L':>12}")
        print("-" * 72)
        for d in sorted(pat_ok["date"].unique()):
            day = pat_ok[pat_ok["date"] == d]
            nt  = len(day)
            tg  = (day["pat_outcome"] == "TARGET_HIT").sum()
            sl_ = (day["pat_outcome"] == "SL_HIT").sum()
            eo  = (day["pat_outcome"] == "IN_TRADE").sum()
            wr  = tg / (tg + sl_) * 100 if (tg + sl_) > 0 else 0
            pnl = day["pat_pnl"].sum()
            sign = "+" if pnl >= 0 else ""
            print(f"  {str(d):<12} {nt:>7} {tg:>7} {sl_:>5} {eo:>5} {wr:>5.1f}% {sign}{pnl:>10,.0f}")

        # Top/bottom pattern trades
        print("\n" + "-" * 72)
        print("  TOP 5 PATTERN WINNERS")
        print("-" * 72)
        cols = ["date","symbol","pat_pattern","pat_signal_label","pat_entry","pat_sl","pat_risk_pct","pat_outcome","pat_exit_price","pat_pnl"]
        cols = [c for c in cols if c in pat_ok.columns]
        print(pat_ok.nlargest(5, "pat_pnl")[cols].to_string(index=False))

        print("\n" + "-" * 72)
        print("  TOP 5 PATTERN LOSERS")
        print("-" * 72)
        print(pat_ok.nsmallest(5, "pat_pnl")[cols].to_string(index=False))

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — CHARTINK DIRECT ENTRY  (baseline comparison)
    # ══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 72)
    print("  SECTION 2 — CHARTINK DIRECT ENTRY  (baseline, no pattern filter)")
    print("=" * 72)

    n_total   = len(ok)
    n_target  = (ok["outcome"] == "TARGET_HIT").sum()
    n_sl      = (ok["outcome"] == "SL_HIT").sum()
    n_eod     = (ok["outcome"] == "IN_TRADE").sum()
    win_rate  = n_target / (n_target + n_sl) * 100 if (n_target + n_sl) > 0 else 0
    total_pnl = ok["pnl"].sum()
    avg_pnl   = ok["pnl"].mean()
    avg_risk  = ok["risk_pct"].mean()

    print(f"\n  Trades simulated   : {n_total}")
    print(f"  TARGET_HIT         : {n_target}  ({n_target/n_total*100:.1f}%)")
    print(f"  SL_HIT             : {n_sl}  ({n_sl/n_total*100:.1f}%)")
    print(f"  EOD exit (open)    : {n_eod}  ({n_eod/n_total*100:.1f}%)")
    print(f"  Win rate (excl EOD): {win_rate:.1f}%  (breakeven = 25.0%)")
    print(f"  Net P&L            : INR {total_pnl:+,.0f}")
    print(f"  Avg P&L/trade      : INR {avg_pnl:+,.0f}")
    print(f"  Avg risk %         : {avg_risk:.3f}%")

    print("\n" + "-" * 72)
    print("  BY DAY")
    print("-" * 72)
    print(f"  {'Date':<12} {'Trades':>6} {'Target':>7} {'SL':>5} {'EOD':>5} {'WR%':>6} {'P&L':>12}")
    print("-" * 72)
    for d in sorted(ok["date"].unique()):
        day = ok[ok["date"] == d]
        nt  = len(day)
        tg  = (day["outcome"] == "TARGET_HIT").sum()
        sl  = (day["outcome"] == "SL_HIT").sum()
        eo  = (day["outcome"] == "IN_TRADE").sum()
        wr  = tg / (tg + sl) * 100 if (tg + sl) > 0 else 0
        pnl = day["pnl"].sum()
        sign = "+" if pnl >= 0 else ""
        print(f"  {str(d):<12} {nt:>6} {tg:>7} {sl:>5} {eo:>5} {wr:>5.1f}% {sign}{pnl:>10,.0f}")

    # ── Sector breakdown ───────────────────────────────────────────────────────
    if "sector" in ok.columns and ok["sector"].notna().any():
        print("\n" + "-" * 72)
        print("  BY SECTOR (top 10)")
        print("-" * 72)
        print(f"  {'Sector':<28} {'Trades':>6} {'WR%':>6} {'P&L':>12}")
        print("-" * 72)
        sec_grp = ok.groupby("sector").apply(
            lambda g: pd.Series({
                "n":   len(g),
                "tg":  (g["outcome"] == "TARGET_HIT").sum(),
                "sl_": (g["outcome"] == "SL_HIT").sum(),
                "pnl": g["pnl"].sum(),
            })
        ).sort_values("n", ascending=False).head(10)
        for sec, row2 in sec_grp.iterrows():
            wr2  = row2["tg"] / (row2["tg"] + row2["sl_"]) * 100 if (row2["tg"] + row2["sl_"]) > 0 else 0
            sign = "+" if row2["pnl"] >= 0 else ""
            print(f"  {str(sec):<28} {int(row2['n']):>6} {wr2:>5.1f}% {sign}{row2['pnl']:>10,.0f}")

    # ── Risk distribution ──────────────────────────────────────────────────────
    print("\n" + "-" * 72)
    print("  RISK DISTRIBUTION")
    print("-" * 72)
    bins   = [0, 0.1, 0.3, 0.5, 1.0, 99]
    labels = ["<0.1% (phantom)", "0.1-0.3%", "0.3-0.5%", "0.5-1.0%", ">1.0%"]
    ok["risk_bucket"] = pd.cut(ok["risk_pct"], bins=bins, labels=labels)
    for lbl in labels:
        bucket = ok[ok["risk_bucket"] == lbl]
        if len(bucket) == 0: continue
        tg  = (bucket["outcome"] == "TARGET_HIT").sum()
        sl_ = (bucket["outcome"] == "SL_HIT").sum()
        wr2 = tg / (tg + sl_) * 100 if (tg + sl_) > 0 else 0
        sign = "+" if bucket["pnl"].sum() >= 0 else ""
        print(f"  {lbl:<20} {len(bucket):>5} signals  WR={wr2:.1f}%  P&L={sign}{bucket['pnl'].sum():>10,.0f}")

    # ── Save output ────────────────────────────────────────────────────────────
    if not args.no_csv:
        file_tag  = args.file.replace(".csv","").replace(" ","_").replace("(","").replace(")","")
        out_path  = os.path.join(ROOT, f"chartink_bt_{dates[0]}_{dates[-1]}.csv")
        save_cols = [
            "date","symbol","sector","signal_time","signal_label",
            "entry","sl","target","risk_pct","outcome","exit_label","exit_price","shares","pnl","pnl_pct",
            "pat_pattern","pat_signal_label","pat_entry","pat_sl","pat_target",
            "pat_risk_pct","pat_outcome","pat_exit_label","pat_exit_price","pat_shares","pat_pnl",
            "status"
        ]
        save_cols = [c for c in save_cols if c in df.columns]
        df[save_cols].to_csv(out_path, index=False)
        print(f"\n  Saved: {out_path}")

    print()


if __name__ == "__main__":
    main()

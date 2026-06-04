"""
backtest.py — Multi-day pattern backtest using local 10-min parquet data.

Loads pre-collected data from data/10min/{SYMBOL}.parquet and runs all active
patterns (B, ENG, HAM, MAR, HAM2S) against each trading day in the specified
range. Prints per-pattern and per-day P&L summaries and saves a CSV.

Run collect_nifty200_data.py first to build the parquet dataset.

Usage:
  python backtest.py --from 2025-01-01 --to 2025-03-31
  python backtest.py --from 2025-01-01             # to = today
  python backtest.py --from 2025-01-01 --no-csv    # skip CSV output
"""

import os
import sys
import argparse
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from instruments import load_instruments
from indicators import calculate_vwap

ROOT          = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(ROOT, "data", "10min")
NIFTY200      = 200
TRADE_CAPITAL = 200_000


# ── Pattern helpers (copied from test.py — do NOT modify test.py) ─────────────

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


def _sig(pattern, ref_candle, entry_candle, extra=None):
    entry = entry_candle["close"]
    sl    = entry_candle["vwap"]
    risk  = entry - sl
    if risk <= 0: return None
    d = {
        "pattern":    pattern,
        "touch_time": ref_candle.name.strftime("%H:%M"),
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

    first_breach = df.iloc[first_breach_idx]
    if (first_breach["open"] - first_breach["vwap"]) / first_breach["vwap"] < 0.0015: return None

    entry = last["close"]; sl = last["vwap"]; risk = entry - sl
    if risk / entry < 0.003: return None

    before_idx = len(df) - 2 - n_below
    if before_idx < 0: return None
    if df.iloc[before_idx]["close"] <= df.iloc[before_idx]["vwap"]: return None

    breach = df.iloc[len(df) - 1 - n_below]
    return _sig("B", breach, last, {"candles_below": n_below, "dip_pct": round(max_dip_pct * 100, 3)})


def _pattern_c(df):
    return None  # DISABLED: 13% WR


def _pattern_eng(df):
    if len(df) < 3: return None
    last = df.iloc[-1]; prev = df.iloc[-2]
    if last["close"] <= last["open"]: return None
    if last["close"] <= last["vwap"]: return None
    if prev["close"] >= prev["open"]: return None
    if prev["low"]   >  prev["vwap"]: return None
    if prev["open"]  <  prev["vwap"]: return None
    if last["open"]  >  prev["close"]: return None
    if last["close"] <  prev["open"]:  return None
    if df.iloc[-3]["close"] <= df.iloc[-3]["vwap"]: return None
    avg_vol = _avg_volume(df)
    if avg_vol > 0 and df["volume"].iloc[-1] < 1.5 * avg_vol: return None
    return _sig("ENG", prev, last, {"dip_pct": round((prev["vwap"] - prev["low"]) / prev["vwap"] * 100, 3)})


def _pattern_ham(df):
    if len(df) < 3: return None
    last = df.iloc[-1]
    if last["close"] <= last["vwap"]: return None
    body       = abs(last["close"] - last["open"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    upper_wick = last["high"] - max(last["open"], last["close"])
    if body < last["close"] * 0.0005: return None
    if lower_wick < 2.0 * body:       return None
    if last["low"] > last["vwap"]:    return None
    if upper_wick > body:             return None
    if df.iloc[-2]["close"] <= df.iloc[-2]["vwap"]: return None
    if df.iloc[-3]["close"] <= df.iloc[-3]["vwap"]: return None
    avg_vol = _avg_volume(df)
    if avg_vol > 0 and df["volume"].iloc[-1] < avg_vol: return None
    return _sig("HAM", last, last, {"dip_pct": round(lower_wick / last["vwap"] * 100, 3)})


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
    return _sig("MAR", df.iloc[-2], last, {"dip_pct": round((last["vwap"] - last["open"]) / last["vwap"] * 100, 3)})


def _pattern_star(df):
    return None  # DISABLED: 13% WR


def _pattern_ham2s(df):
    if len(df) < 5: return None
    sigma = _calc_vwap_sigma(df)
    if sigma is None: return None
    last    = df.iloc[-1]
    vwap    = last["vwap"]
    sig_val = float(sigma.iloc[-1])
    if sig_val <= 0: return None
    lower_2s = vwap - 2.0 * sig_val
    if (df["vwap"].iloc[-5:].max() - df["vwap"].iloc[-5:].min()) / vwap > 0.0015: return None
    if last["low"] > lower_2s: return None
    if last.name.strftime("%H:%M") > "14:45": return None  # EOD cutoff
    body       = abs(last["close"] - last["open"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    upper_wick = last["high"] - max(last["open"], last["close"])
    if body < last["close"] * 0.0003:  return None
    if lower_wick < 2.0 * body:        return None
    if last["close"] < lower_2s:       return None
    if upper_wick > body:              return None
    avg_vol = _avg_volume(df)
    if avg_vol > 0 and last["volume"] < 1.5 * avg_vol: return None
    entry = round(last["close"], 2); sl = round(last["low"] - 0.01, 2)
    risk  = round(entry - sl, 2)
    if risk <= 0 or risk / entry < 0.001: return None
    return {
        "pattern":    "HAM2S",
        "touch_time": last.name.strftime("%H:%M"),
        "entry_time": last.name.strftime("%H:%M"),
        "entry":      entry,
        "sl":         sl,
        "target":     round(entry + 3.0 * risk, 2),
        "risk":       risk,
        "reward":     round(3.0 * risk, 2),
        "dip_pct":    round((vwap - last["low"]) / vwap * 100, 3),
    }


def _pattern_bw(df):
    return None  # DISABLED: 3% WR


def _pattern_sqz(df):
    return None  # DISABLED: 0% WR


def _find_signal(today_df):
    """Scan 9:35–11:00 only — no buy calls after 11:00."""
    times = today_df.index.strftime("%H:%M")
    avail = today_df[(times >= "09:35") & (times <= "11:00")]
    for ts in avail.index:
        sl = today_df[today_df.index <= ts]
        if len(sl) < 3: continue
        sig = (_pattern_b(sl)     or _pattern_c(sl)     or
               _pattern_eng(sl)   or _pattern_ham(sl)   or
               _pattern_mar(sl)   or _pattern_star(sl)  or
               _pattern_ham2s(sl) or _pattern_bw(sl)    or
               _pattern_sqz(sl))
        if sig: return sig
    return None


def _simulate(sig, today_df):
    """Simulate trade from entry candle to SL / target / EOD."""
    entry = sig["entry"]; sl = sig["sl"]; target = sig["target"]
    future = today_df[today_df.index.strftime("%H:%M") > sig["entry_time"]]
    outcome = "IN_TRADE"; exit_price = float(today_df.iloc[-1]["close"])
    exit_time = today_df.index[-1].strftime("%H:%M")
    for ts, row in future.iterrows():
        if row["low"] <= sl:
            outcome = "SL_HIT"; exit_price = sl
            exit_time = ts.strftime("%H:%M"); break
        if row["high"] >= target:
            outcome = "TARGET_HIT"; exit_price = target
            exit_time = ts.strftime("%H:%M"); break
    shares = int(TRADE_CAPITAL / entry) if entry > 0 else 0
    pnl    = round((exit_price - entry) * shares, 2)
    return {"outcome": outcome, "exit_price": round(exit_price, 2),
            "exit_time": exit_time, "shares": shares, "pnl": pnl}


# ── Per-symbol backtest ───────────────────────────────────────────────────────

def _backtest_stock(row: dict, from_d: date, to_d: date) -> list[dict]:
    sym  = row["symbol"]
    path = os.path.join(DATA_DIR, f"{sym}.parquet")
    if not os.path.exists(path):
        return []
    try:
        df = pd.read_parquet(path)
        if df.empty:
            return []
        mask = (df.index.date >= from_d) & (df.index.date <= to_d)
        df   = df[mask].copy()
        if df.empty:
            return []

        df["vwap"] = calculate_vwap(df)   # resets each calendar day automatically
        df = df.dropna(subset=["vwap"])

        results = []
        for day in sorted(set(df.index.date)):
            day_df = df[df.index.date == day].copy()
            if len(day_df) < 3:
                continue
            sig = _find_signal(day_df)
            if not sig:
                continue
            sim = _simulate(sig, day_df)
            results.append({
                "date":       day,
                "symbol":     sym,
                "pattern":    sig["pattern"],
                "entry_time": sig["entry_time"],
                "entry":      sig["entry"],
                "sl":         sig["sl"],
                "target":     sig["target"],
                "risk_pct":   round(sig["risk"] / sig["entry"] * 100, 3),
                "outcome":    sim["outcome"],
                "exit_time":  sim["exit_time"],
                "exit_price": sim["exit_price"],
                "shares":     sim["shares"],
                "pnl":        sim["pnl"],
            })
        return results
    except Exception as e:
        print(f"  [WARN] {sym}: {e}")
        return []


# ── Summary output ────────────────────────────────────────────────────────────

def _print_pattern_summary(df: pd.DataFrame):
    W = 72
    print("\n" + "=" * W)
    print("  PATTERN SUMMARY")
    print("=" * W)
    print(f"  {'Pattern':<10} {'Signals':>7} {'Wins':>6} {'Loss':>6} {'EOD':>5}  {'WR%':>6}  {'Total P&L':>13}  {'Per Signal':>11}")
    print("  " + "-" * (W - 2))

    for pat in sorted(df["pattern"].unique()):
        g = df[df["pattern"] == pat]
        n = len(g)
        w = (g["outcome"] == "TARGET_HIT").sum()
        l = (g["outcome"] == "SL_HIT").sum()
        e = (g["outcome"] == "IN_TRADE").sum()
        wr      = w / n * 100 if n else 0
        pnl     = g["pnl"].sum()
        per_sig = pnl / n if n else 0
        sp = "+" if pnl >= 0 else ""
        ss = "+" if per_sig >= 0 else ""
        print(f"  {pat:<10} {n:>7} {w:>6} {l:>6} {e:>5}  {wr:>5.1f}%  "
              f"₹{sp}{pnl:>11,.0f}  ₹{ss}{per_sig:>9,.0f}")

    print("  " + "-" * (W - 2))
    n = len(df)
    w = (df["outcome"] == "TARGET_HIT").sum()
    l = (df["outcome"] == "SL_HIT").sum()
    e = (df["outcome"] == "IN_TRADE").sum()
    wr      = w / n * 100 if n else 0
    pnl     = df["pnl"].sum()
    per_sig = pnl / n if n else 0
    sp = "+" if pnl >= 0 else ""
    ss = "+" if per_sig >= 0 else ""
    print(f"  {'ALL':<10} {n:>7} {w:>6} {l:>6} {e:>5}  {wr:>5.1f}%  "
          f"₹{sp}{pnl:>11,.0f}  ₹{ss}{per_sig:>9,.0f}")


def _print_daily_summary(df: pd.DataFrame):
    W = 58
    print("\n" + "=" * W)
    print("  DAILY BREAKDOWN")
    print("=" * W)
    print(f"  {'Date':<12} {'Sigs':>6} {'Wins':>6} {'Loss':>6}  {'WR%':>6}  {'P&L':>12}")
    print("  " + "-" * (W - 2))
    for day, g in df.groupby("date"):
        n = len(g)
        w = (g["outcome"] == "TARGET_HIT").sum()
        l = (g["outcome"] == "SL_HIT").sum()
        wr  = w / n * 100 if n else 0
        pnl = g["pnl"].sum()
        s   = "+" if pnl >= 0 else ""
        print(f"  {str(day):<12} {n:>6} {w:>6} {l:>6}  {wr:>5.1f}%  ₹{s}{pnl:>10,.0f}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TejToro multi-day pattern backtest")
    parser.add_argument("--from",    dest="from_date", required=True,
                        help="Start date YYYY-MM-DD")
    parser.add_argument("--to",      dest="to_date",   default=None,
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--workers", type=int, default=12,
                        help="Parallel workers (default: 12)")
    parser.add_argument("--no-csv",  action="store_true",
                        help="Skip saving CSV output")
    args = parser.parse_args()

    to_d   = date.fromisoformat(args.to_date) if args.to_date else date.today()
    from_d = date.fromisoformat(args.from_date)

    print(f"\n  TejToro — Pattern Backtest")
    print(f"  Range   : {from_d} → {to_d}")
    print(f"  Patterns: B, ENG, HAM, MAR, HAM2S  (C / STAR / BW / SQZ disabled)")
    print(f"  Capital : ₹{TRADE_CAPITAL:,} per trade  |  R:R 1:3")
    print(f"  Data    : {DATA_DIR}\n")

    df_inst  = load_instruments()
    universe = df_inst.head(NIFTY200).reset_index(drop=True)
    rows     = universe.to_dict("records")

    # Count available parquet files up front
    n_files = sum(
        1 for r in rows
        if os.path.exists(os.path.join(DATA_DIR, f"{r['symbol']}.parquet"))
    )
    if n_files == 0:
        print(f"  No parquet files found in {DATA_DIR}")
        print(f"  Run first: python collect_nifty200_data.py --from {from_d} --to {to_d}")
        return

    print(f"  {n_files}/{len(rows)} parquet files found — scanning...\n")

    all_results = []

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_backtest_stock, r, from_d, to_d): r["symbol"] for r in rows}
        done = 0
        for f in as_completed(futs):
            sym       = futs[f]
            stock_res = f.result()
            all_results.extend(stock_res)
            done += 1
            if stock_res:
                n   = len(stock_res)
                w   = sum(1 for r in stock_res if r["outcome"] == "TARGET_HIT")
                pnl = sum(r["pnl"] for r in stock_res)
                s   = "+" if pnl >= 0 else ""
                print(f"  [{done:3d}/{n_files}] {sym:<16} {n} signals  "
                      f"{w}W/{n - w}L  ₹{s}{pnl:,.0f}")

    if not all_results:
        print("\n  No signals found in the specified date range.")
        print(f"  Check that data covers this period:")
        print(f"  python collect_nifty200_data.py --from {from_d} --to {to_d}")
        return

    df_res = pd.DataFrame(all_results)
    df_res["date"] = pd.to_datetime(df_res["date"])

    _print_pattern_summary(df_res)
    _print_daily_summary(df_res)

    total_pnl = df_res["pnl"].sum()
    n_days    = df_res["date"].nunique()
    s = "+" if total_pnl >= 0 else ""
    print(f"\n  {len(df_res)} signals across {n_days} trading days  |  "
          f"Net P&L: ₹{s}{total_pnl:,.0f}")

    if not args.no_csv:
        csv_path = os.path.join(ROOT, f"backtest_{from_d}_{to_d}.csv")
        df_res.to_csv(csv_path, index=False)
        print(f"  Saved : {csv_path}")

    print()


if __name__ == "__main__":
    main()

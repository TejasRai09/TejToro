"""
find_new_pattern.py  — Refined analysis based on Round 1 results.

Round 1 showed VWAP_WR at 11:xx → 45.8% WR. Now testing refined variants:
  VWAP_WR_R  — VWAP Wick Rejection with prior-uptrend filter + time 10:30+
  VWAP_RCL   — VWAP Reclaim: price spent 2+ bars BELOW VWAP, then strong cross back above
  VWAP_RCL2  — VWAP Reclaim with trend (price was ABOVE VWAP before the dip)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("data/10min")
SYMBOLS = [
    "ICICIBANK","BHARTIARTL","INFY","RELIANCE","BAJFINANCE",
    "TCS","HINDUNILVR","SUNPHARMA","ETERNAL","COALINDIA",
    "ASIANPAINT","BAJAJHLDNG","ADANIENT","ADANIPOWER","CGPOWER",
    "HCLTECH","TITAN","KOTAKBANK","SBIN","HDFCBANK",
]

TGT_MULT = 2.0
CAPITAL  = 10000

# ─────────────────────────────────────────────────────────
def load_vwap(sym):
    f = DATA_DIR / f"{sym}.parquet"
    if not f.exists(): return None
    df = pd.read_parquet(f)
    df.index = pd.to_datetime(df.index)
    df.columns = [c.lower() for c in df.columns]
    df = df.between_time("09:15", "15:20")
    df["vwap"] = np.nan
    for d, g in df.groupby(df.index.date):
        tp = (g["high"] + g["low"] + g["close"]) / 3
        df.loc[g.index, "vwap"] = (tp * g["volume"]).cumsum() / g["volume"].cumsum().replace(0, np.nan)
    return df

def sess_vol_median(sess):
    v = sess["volume"].iloc[1:]   # skip opening bar spike
    return float(v.median()) if len(v) > 1 else 0.0

def simulate_trade(entry_pos, sess, sl, target):
    future = sess.iloc[entry_pos + 1:]
    for _, bar in future.iterrows():
        if bar["low"]  <= sl:     return "SL",   sl
        if bar["high"] >= target: return "WIN",  target
    return "OPEN", float(sess.iloc[-1]["close"])

def record(pat, d, t, entry, sl, target, outcome, xp):
    risk   = entry - sl
    shares = max(1, int(CAPITAL / entry))
    pnl    = round((xp - entry) * shares, 2)
    return {"pattern": pat, "date": d, "time": t,
            "entry": entry, "sl": sl, "target": target,
            "risk_pct": round(risk / entry * 100, 2),
            "outcome": outcome, "pnl": pnl}

# ─────────────────────────────────────────────────────────
# A: Refined VWAP Wick Rejection
# Improvements over raw VWAP_WR:
#   1. Only after 10:30 (VWAP has 75+ mins of history)
#   2. Prior uptrend: at least 3 of the last 5 bars closed above VWAP
#   3. Meaningful wick: low went at least 0.1% below VWAP
#   4. Strong close: close > 60% of bar's range (close near the top)
def scan_vwap_wr_r(sess):
    trades = []
    used = set()
    med_vol = sess_vol_median(sess)
    for i in range(5, len(sess) - 1):
        bar  = sess.iloc[i]
        d    = str(bar.name.date())
        t    = bar.name.strftime("%H:%M")
        if d in used or t < "10:30" or t > "14:00": continue
        if pd.isna(bar["vwap"]): continue
        vwap = float(bar["vwap"])
        lo, hi, cl, op = float(bar["low"]), float(bar["high"]), float(bar["close"]), float(bar["open"])
        # wick must dip below VWAP and close must be clearly back above
        if not (lo < vwap * 0.999 and cl > vwap * 1.001): continue
        # must be green
        if cl <= op: continue
        # close must be in top 60% of bar's range
        bar_range = hi - lo
        if bar_range <= 0: continue
        if (cl - lo) / bar_range < 0.60: continue
        # prior uptrend: at least 3 of last 5 bars closed above VWAP
        prior = sess.iloc[i - 5: i]
        above_count = sum(float(b["close"]) > float(b["vwap"]) for _, b in prior.iterrows() if not pd.isna(b["vwap"]))
        if above_count < 3: continue
        # volume not dead
        if med_vol > 0 and float(bar["volume"]) < 0.7 * med_vol: continue
        entry  = cl
        sl     = round(lo * 0.998, 2)
        risk   = entry - sl
        if risk <= 0 or risk / entry > 0.012: continue
        target = round(entry + TGT_MULT * risk, 2)
        outcome, xp = simulate_trade(i, sess, sl, target)
        trades.append(record("VWAP_WR_R", d, t, entry, sl, target, outcome, xp))
        used.add(d)
    return trades

# ─────────────────────────────────────────────────────────
# B: VWAP Reclaim (Cold)
# Price spent >= 2 consecutive bars BELOW VWAP
# Then a strong green bar crosses back above VWAP and closes clearly above
# No prior trend requirement — works on any direction
def scan_vwap_rcl(sess):
    trades = []
    used = set()
    med_vol = sess_vol_median(sess)
    for i in range(3, len(sess) - 1):
        bar   = sess.iloc[i]
        prev  = sess.iloc[i - 1]
        pp    = sess.iloc[i - 2]
        d     = str(bar.name.date())
        t     = bar.name.strftime("%H:%M")
        if d in used or t < "09:45" or t > "14:00": continue
        if pd.isna(bar["vwap"]) or pd.isna(prev["vwap"]) or pd.isna(pp["vwap"]): continue
        # at least 2 prior bars were below VWAP
        if not (float(prev["close"]) < float(prev["vwap"]) and
                float(pp["close"])   < float(pp["vwap"])): continue
        # current bar crosses back above VWAP — strong green close
        vwap = float(bar["vwap"])
        cl, op, lo = float(bar["close"]), float(bar["open"]), float(bar["low"])
        if cl <= vwap * 1.001: continue   # must close clearly above VWAP
        if cl <= op: continue             # green
        # bar low should be near/at VWAP (the rejection came from VWAP area)
        if lo > vwap * 1.005: continue   # if low is already above VWAP, it didn't test it
        if med_vol > 0 and float(bar["volume"]) < 1.0 * med_vol: continue
        entry  = cl
        sl     = round(float(prev["low"]) * 0.998, 2)
        risk   = entry - sl
        if risk <= 0 or risk / entry > 0.015: continue
        target = round(entry + TGT_MULT * risk, 2)
        outcome, xp = simulate_trade(i, sess, sl, target)
        trades.append(record("VWAP_RCL", d, t, entry, sl, target, outcome, xp))
        used.add(d)
    return trades

# ─────────────────────────────────────────────────────────
# C: VWAP Reclaim after pullback in an uptrend
# Prior context: 4+ bars above VWAP (established uptrend)
# Then 1-3 bars below VWAP (pullback/shakeout)
# Then reclaim bar: green, closes above VWAP, volume above median
# This is "buying the dip on an intraday uptrend"
def scan_vwap_rcl2(sess):
    trades = []
    used = set()
    med_vol = sess_vol_median(sess)
    for i in range(6, len(sess) - 1):
        bar  = sess.iloc[i]
        d    = str(bar.name.date())
        t    = bar.name.strftime("%H:%M")
        if d in used or t < "10:00" or t > "14:00": continue
        if pd.isna(bar["vwap"]): continue
        vwap = float(bar["vwap"])
        cl, op, lo = float(bar["close"]), float(bar["open"]), float(bar["low"])
        # reclaim bar: green, close above VWAP
        if cl <= vwap * 1.001 or cl <= op: continue
        # bar low dipped to VWAP area (test of VWAP as support)
        if lo > vwap * 1.003: continue
        # prior: at least 1 bar below VWAP (the pullback)
        prev = sess.iloc[i - 1]
        if pd.isna(prev["vwap"]): continue
        if float(prev["close"]) >= float(prev["vwap"]): continue  # must have been below
        # prior uptrend: at least 4 of bars i-6..i-2 closed above VWAP
        context = sess.iloc[max(0, i - 6): i - 1]
        above_count = sum(
            float(b["close"]) > float(b["vwap"])
            for _, b in context.iterrows() if not pd.isna(b["vwap"])
        )
        if above_count < 3: continue
        if med_vol > 0 and float(bar["volume"]) < 1.0 * med_vol: continue
        entry  = cl
        sl     = round(float(prev["low"]) * 0.997, 2)
        risk   = entry - sl
        if risk <= 0 or risk / entry > 0.015: continue
        target = round(entry + TGT_MULT * risk, 2)
        outcome, xp = simulate_trade(i, sess, sl, target)
        trades.append(record("VWAP_RCL2", d, t, entry, sl, target, outcome, xp))
        used.add(d)
    return trades

# ─────────────────────────────────────────────────────────
# D: VWAP Trend Continuation
# Price is in an established uptrend above VWAP
# After a 2-3 bar sideways/pullback pause, closes above the pause's high with volume
# "Pocket Pivot" concept — base near VWAP then launch
def scan_vwap_cont(sess):
    trades = []
    used = set()
    med_vol = sess_vol_median(sess)
    for i in range(5, len(sess) - 1):
        bar  = sess.iloc[i]
        d    = str(bar.name.date())
        t    = bar.name.strftime("%H:%M")
        if d in used or t < "10:00" or t > "14:00": continue
        if pd.isna(bar["vwap"]): continue
        vwap = float(bar["vwap"])
        cl, op, hi = float(bar["close"]), float(bar["open"]), float(bar["high"])
        # current bar: green, above VWAP
        if cl <= vwap or cl <= op: continue
        # high of current bar is the highest of last 5 bars (breakout of consolidation)
        prior5 = sess.iloc[i - 5: i]
        max_prior_high = prior5["high"].max()
        if hi <= max_prior_high: continue
        # prior 3 bars were ranging tight (low range relative to ATR)
        prior3 = sess.iloc[i - 3: i]
        p3_range = prior3["high"].max() - prior3["low"].min()
        p3_close_range = prior3["close"].max() - prior3["close"].min()
        if p3_close_range == 0: continue
        # prior 3 bars were above VWAP (we're in an uptrend)
        above_count = sum(float(b["close"]) > float(b["vwap"])
                         for _, b in prior3.iterrows() if not pd.isna(b["vwap"]))
        if above_count < 2: continue
        # the prior bars were "flat" — not already running (high close range vs bar range)
        sess_range = (sess["high"].max() - sess["low"].min()) / len(sess)
        if p3_range > sess_range * 4: continue   # too volatile, not consolidating
        if med_vol > 0 and float(bar["volume"]) < 1.3 * med_vol: continue
        entry  = cl
        prior3_lo = float(prior3["low"].min())
        sl     = round(prior3_lo * 0.998, 2)
        risk   = entry - sl
        if risk <= 0 or risk / entry > 0.012: continue
        target = round(entry + TGT_MULT * risk, 2)
        outcome, xp = simulate_trade(i, sess, sl, target)
        trades.append(record("VWAP_CNT", d, t, entry, sl, target, outcome, xp))
        used.add(d)
    return trades

# ─────────────────────────────────────────────────────────
def print_stats(trades_list, label, verbose=False):
    df = pd.DataFrame(trades_list) if trades_list else pd.DataFrame()
    if len(df) == 0:
        print(f"  {label:12s}: 0 trades")
        return {"name": label, "total": 0, "wr": 0, "pnl": 0, "closed": 0}
    cl   = df[df["outcome"] != "OPEN"]
    w    = (cl["outcome"] == "WIN").sum()
    l    = (cl["outcome"] == "SL").sum()
    wr   = w / len(cl) * 100 if len(cl) > 0 else 0
    pnl  = df["pnl"].sum()
    avg  = df["pnl"].mean()
    flag = "  <-- PROFITABLE!" if wr > 40 and len(cl) >= 15 else ""
    print(f"  {label:12s}: {len(df):3d} trades | closed {len(cl):3d} | "
          f"WR {wr:5.1f}% | W:{w:3d} L:{l:3d} | "
          f"PnL ₹{pnl:8,.0f} | avg ₹{avg:+7.0f}{flag}")
    return {"name": label, "total": len(df), "wr": round(wr, 1),
            "pnl": round(pnl, 2), "closed": len(cl), "wins": int(w), "losses": int(l)}

# ─────────────────────────────────────────────────────────
print(f"\n  Scanning {len(SYMBOLS)} stocks ...\n")

PATTERNS = ["VWAP_WR_R", "VWAP_RCL", "VWAP_RCL2", "VWAP_CNT"]
buckets = {p: [] for p in PATTERNS}
sym_buckets = {p: {} for p in PATTERNS}

SCAN_FNS = {
    "VWAP_WR_R": scan_vwap_wr_r,
    "VWAP_RCL":  scan_vwap_rcl,
    "VWAP_RCL2": scan_vwap_rcl2,
    "VWAP_CNT":  scan_vwap_cont,
}

for sym in SYMBOLS:
    df = load_vwap(sym)
    if df is None or len(df) < 20:
        print(f"  {sym}: no data, skip"); continue

    s_trades = {p: [] for p in PATTERNS}
    for d, grp in df.groupby(df.index.date):
        sess = grp
        if len(sess) < 6: continue
        for p, fn in SCAN_FNS.items():
            for t in fn(sess): s_trades[p].append(t)

    counts = [f"{p.split('_')[-1]}={len(s_trades[p])}" for p in PATTERNS]
    print(f"  {sym:15s}: {' | '.join(counts)}")

    for p in PATTERNS:
        buckets[p].extend(s_trades[p])
        sym_buckets[p][sym] = s_trades[p]

print("\n" + "="*78)
print("  RESULTS  (₹10,000/trade, 2:1 RR, breakeven WR = 33.3%)")
print("="*78)

results = []
for p in PATTERNS:
    r = print_stats(buckets[p], p)
    if r["total"] > 0: results.append(r)

print()

# Best pattern drill-down
if results:
    good = [r for r in results if r["closed"] >= 10]
    if good:
        best = max(good, key=lambda x: x["wr"])
        bp   = best["name"]
        print(f"\n  >>> WINNER: {bp}  — WR {best['wr']}%  |  {best['total']} trades  |  PnL ₹{best['pnl']:,.0f}")

        print(f"\n  {bp} by symbol:")
        sym_rows = []
        for sym in SYMBOLS:
            ts = sym_buckets[bp].get(sym, [])
            if not ts: continue
            df2 = pd.DataFrame(ts)
            cl2 = df2[df2["outcome"] != "OPEN"]
            w2  = (cl2["outcome"] == "WIN").sum()
            wr2 = w2 / len(cl2) * 100 if len(cl2) > 0 else 0
            p2  = df2["pnl"].sum()
            sym_rows.append((sym, len(df2), wr2, p2))
        sym_rows.sort(key=lambda x: x[2], reverse=True)
        for sym, n, wr2, p2 in sym_rows:
            bar_len = int(wr2 / 5)
            bar_str = "#" * bar_len + "-" * (20 - bar_len)
            print(f"    {sym:15s}: {n:2d} trades | {bar_str} {wr2:5.1f}% | ₹{p2:7,.0f}")

        bp_df = pd.DataFrame(buckets[bp])
        if "time" in bp_df.columns:
            print(f"\n  {bp} by hour:")
            bp_df["hour"] = bp_df["time"].str[:2]
            for h, sub in bp_df.groupby("hour"):
                cl3 = sub[sub["outcome"] != "OPEN"]
                w3  = (cl3["outcome"] == "WIN").sum()
                wr3 = w3 / len(cl3) * 100 if len(cl3) > 0 else 0
                p3  = sub["pnl"].sum()
                bar_len = int(wr3 / 5)
                bar_str = "#" * bar_len + "-" * (20 - bar_len)
                print(f"    {h}:xx   {len(sub):3d} trades | {bar_str} {wr3:5.1f}% | ₹{p3:7,.0f}")

        # Show a few sample trades
        print(f"\n  Sample {bp} trades (first 10):")
        sample = bp_df.head(10)
        for _, row in sample.iterrows():
            print(f"    {row.get('date','?')} {row.get('time','?')} | "
                  f"entry ₹{row['entry']:.1f} | sl ₹{row['sl']:.1f} | "
                  f"risk {row.get('risk_pct','?')}% | {row['outcome']} | ₹{row['pnl']:+.0f}")

print("\n  Done.\n")

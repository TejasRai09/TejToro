"""
analyze_vwap_cnt.py
Deep dive into the VWAP Trend Continuation pattern + relaxed variant.
This is the best candidate from round-2 analysis: 55.6% WR, 2:1 RR.

Pattern logic:
  - Stock is in an intraday uptrend (trading above VWAP)
  - Price pauses/consolidates for 2-3 bars just above VWAP (tight range)
  - A breakout bar closes above the consolidation high with above-average volume
  - SL: below consolidation low  |  Target: 2x risk
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
    v = sess["volume"].iloc[1:]
    return float(v.median()) if len(v) > 1 else 0.0

def simulate_trade(entry_pos, sess, sl, target):
    future = sess.iloc[entry_pos + 1:]
    for _, bar in future.iterrows():
        if bar["low"]  <= sl:     return "SL",   sl
        if bar["high"] >= target: return "WIN",  target
    return "OPEN", float(sess.iloc[-1]["close"])

def record(pat, sym, d, t, entry, sl, target, outcome, xp, **extra):
    risk   = entry - sl
    shares = max(1, int(CAPITAL / entry))
    pnl    = round((xp - entry) * shares, 2)
    base   = {"pattern": pat, "symbol": sym, "date": d, "time": t,
              "entry": entry, "sl": sl, "target": target,
              "risk_pct": round(risk / entry * 100, 2),
              "outcome": outcome, "pnl": pnl}
    base.update(extra)
    return base

# ─────────────────────────────────────────────────────────
# STRICT version (original VWAP_CNT)
def scan_cnt_strict(sess, sym):
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
        if cl <= vwap or cl <= op: continue
        prior5 = sess.iloc[i - 5: i]
        if hi <= prior5["high"].max(): continue   # not a new 5-bar high
        prior3 = sess.iloc[i - 3: i]
        above_count = sum(float(b["close"]) > float(b["vwap"])
                         for _, b in prior3.iterrows() if not pd.isna(b["vwap"]))
        if above_count < 2: continue
        sess_range = (sess["high"].max() - sess["low"].min()) / max(1, len(sess))
        p3_range   = prior3["high"].max() - prior3["low"].min()
        if p3_range > sess_range * 4: continue
        if med_vol > 0 and float(bar["volume"]) < 1.3 * med_vol: continue
        entry  = cl
        sl     = round(float(prior3["low"].min()) * 0.998, 2)
        risk   = entry - sl
        if risk <= 0 or risk / entry > 0.012: continue
        target = round(entry + TGT_MULT * risk, 2)
        outcome, xp = simulate_trade(i, sess, sl, target)
        trades.append(record("CNT_STRICT", sym, d, t, entry, sl, target, outcome, xp,
                             consol_bars=3))
        used.add(d)
    return trades

# RELAXED version — slightly looser conditions to get more trades
def scan_cnt_relaxed(sess, sym):
    trades = []
    used = set()
    med_vol = sess_vol_median(sess)
    for i in range(4, len(sess) - 1):
        bar  = sess.iloc[i]
        d    = str(bar.name.date())
        t    = bar.name.strftime("%H:%M")
        if d in used or t < "09:45" or t > "14:00": continue
        if pd.isna(bar["vwap"]): continue
        vwap = float(bar["vwap"])
        cl, op, hi = float(bar["close"]), float(bar["open"]), float(bar["high"])
        if cl <= vwap or cl <= op: continue
        # RELAXED: just needs to be higher than prior 4 bars
        prior4 = sess.iloc[i - 4: i]
        if hi <= prior4["high"].max(): continue
        # RELAXED: at least 2 of prior 4 bars above VWAP
        above_count = sum(float(b["close"]) > float(b["vwap"])
                         for _, b in prior4.iterrows() if not pd.isna(b["vwap"]))
        if above_count < 2: continue
        # Volume above median (not strict 1.3x, just 1.0x)
        if med_vol > 0 and float(bar["volume"]) < 1.0 * med_vol: continue
        entry  = cl
        sl     = round(float(prior4["low"].min()) * 0.998, 2)
        risk   = entry - sl
        if risk <= 0 or risk / entry > 0.015: continue
        target = round(entry + TGT_MULT * risk, 2)
        outcome, xp = simulate_trade(i, sess, sl, target)
        trades.append(record("CNT_RELAX", sym, d, t, entry, sl, target, outcome, xp))
        used.add(d)
    return trades

# ─────────────────────────────────────────────────────────
strict_trades = []
relax_trades  = []

print(f"\n  Scanning {len(SYMBOLS)} stocks ...\n")
for sym in SYMBOLS:
    df = load_vwap(sym)
    if df is None or len(df) < 20:
        print(f"  {sym}: skip"); continue
    s_str = []; s_rel = []
    for d, grp in df.groupby(df.index.date):
        sess = grp
        if len(sess) < 6: continue
        s_str.extend(scan_cnt_strict(sess, sym))
        s_rel.extend(scan_cnt_relaxed(sess, sym))
    strict_trades.extend(s_str)
    relax_trades.extend(s_rel)
    print(f"  {sym:15s}: strict={len(s_str)}  relaxed={len(s_rel)}")

def analyse(trades, label):
    df = pd.DataFrame(trades) if trades else pd.DataFrame()
    if len(df) == 0:
        print(f"\n  {label}: 0 trades"); return
    cl = df[df["outcome"] != "OPEN"]
    w  = (cl["outcome"] == "WIN").sum()
    l  = (cl["outcome"] == "SL").sum()
    wr = w / len(cl) * 100 if len(cl) > 0 else 0
    pnl = df["pnl"].sum()
    print(f"\n  {label}")
    print(f"  {'─'*60}")
    print(f"  Total trades : {len(df)}")
    print(f"  Closed trades: {len(cl)}  (OPEN={len(df)-len(cl)})")
    print(f"  Wins / Losses: {w} / {l}")
    print(f"  Win Rate     : {wr:.1f}%  (breakeven: 33.3%)")
    print(f"  Total PnL    : ₹{pnl:,.0f}")
    print(f"  Avg PnL/trade: ₹{df['pnl'].mean():+.0f}")
    if wr > 40:
        ev = wr/100 * 2 - (1 - wr/100) * 1
        print(f"  Expected val : +{ev:.2f}R per trade  ← PROFITABLE EDGE!")
    print()
    print(f"  By Symbol:")
    sym_data = []
    for sym, sub in df.groupby("symbol"):
        cl2 = sub[sub["outcome"] != "OPEN"]
        w2  = (cl2["outcome"] == "WIN").sum() if len(cl2) > 0 else 0
        wr2 = w2 / len(cl2) * 100 if len(cl2) > 0 else 0
        sym_data.append((sym, len(sub), wr2, sub["pnl"].sum()))
    sym_data.sort(key=lambda x: x[2], reverse=True)
    for sym, n, wr2, p2 in sym_data:
        bars = "#" * int(wr2 / 5)
        print(f"    {sym:15s}: {n:2d} | {bars:<20s} {wr2:5.1f}% | ₹{p2:+7,.0f}")
    print()
    print(f"  By Hour:")
    df["hour"] = df["time"].str[:2]
    for h, sub in df.groupby("hour"):
        cl2 = sub[sub["outcome"] != "OPEN"]
        w2  = (cl2["outcome"] == "WIN").sum() if len(cl2) > 0 else 0
        wr2 = w2 / len(cl2) * 100 if len(cl2) > 0 else 0
        bars = "#" * int(wr2 / 5)
        print(f"    {h}:xx  {len(sub):3d} trades | {bars:<20s} {wr2:5.1f}% | ₹{sub['pnl'].sum():+,.0f}")
    print()
    print(f"  All trades:")
    print(f"  {'Date':<12} {'Sym':<12} {'Time':<6} {'Entry':>8} {'Risk%':>6} {'Outcome':<6} {'PnL':>7}")
    print(f"  {'─'*65}")
    for _, row in df.sort_values(["date","time"]).iterrows():
        tag = "WIN " if row['outcome']=="WIN" else ("SL  " if row['outcome']=="SL" else "OPEN")
        print(f"  {row['date']:<12} {row['symbol']:<12} {row['time']:<6} "
              f"{row['entry']:>8.1f} {row['risk_pct']:>6.2f}%  {tag}  ₹{row['pnl']:>+7,.0f}")

print("\n" + "="*72)
analyse(strict_trades, "VWAP_CNT STRICT  (original)")
print("="*72)
analyse(relax_trades,  "VWAP_CNT RELAXED (new)")
print("="*72)
print()

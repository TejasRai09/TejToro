"""
validate_vcnb.py
Out-of-sample validation of VWAP Consolidation Breakout (VCNB) pattern.
Uses 180 stocks NOT seen during discovery.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np
from pathlib import Path
import random

DATA_DIR = Path("data/10min")

# 180 fresh stocks (not used in pattern discovery)
FRESH_STOCKS = [
    'ABB','ABCAPITAL','ADANIENSOL','ADANIGREEN','ADANIPORTS','ALKEM','AMBER','AMBUJACEM',
    'ANGELONE','APARINDS','APLAPOLLO','APOLLOHOSP','ASHOKLEY','ASTERDM','ASTRAL','ATGL',
    'ATHERENERG','AUBANK','AUROPHARMA','AXISBANK','BAJAJFINSV','BALKRISIND','BANDHANBNK',
    'BANKBARODA','BANKINDIA','BEL','BHARATFORG','BHEL','BIOCON','BLUESTARCO','BOSCHLTD',
    'BPCL','BRITANNIA','BSE','CAMS','CANBK','CDSL','CHOLAFIN','CIPLA','COFORGE','COLPAL',
    'CONCOR','COROMANDEL','CROMPTON','CUB','CUMMINSIND','DABUR','DELHIVERY','DIVISLAB',
    'DIXON','DLF','DMART','DRREDDY','EICHERMOT','ENRIN','FEDERALBNK','FORTIS','GAIL',
    'GLENMARK','GMRAIRPORT','GODREJCP','GODREJPROP','GRASIM','HAL','HAVELLS','HDFCAMC',
    'HDFCLIFE','HEROMOTOCO','HINDALCO','HINDCOPPER','HINDPETRO','HINDZINC','HYUNDAI',
    'ICICIGI','ICICIPRULI','IDFCFIRSTB','INDHOTEL','INDIANB','INDIGO','INDUSINDBK',
    'INDUSTOWER','IOC','IPCALAB','IRFC','ITC','ITCHOTELS','JINDALSTEL','JIOFIN','JKCEMENT',
    'JSL','JSWENERGY','JSWSTEEL','JUBLFOOD','KARURVYSYA','KEI','LAURUSLABS','LICI',
    'LLOYDSME','LODHA','LT','LTF','LTM','LUPIN','MANKIND','MARICO','MARUTI','MAXHEALTH',
    'MAZDOCK','MCX','MFSL','MPHASIS','MUTHOOTFIN','NATIONALUM','NAUKRI','NAVINFLUOR',
    'NESTLEIND','NHPC','NMDC','NTPC','NYKAA','OBEROIRLTY','OFSS','OIL','ONGC','PAGEIND',
    'PAYTM','PERSISTENT','PETRONET','PFC','PHOENIXLTD','PIDILITIND','PIIND','PIRAMALFIN',
    'PNB','PNBHOUSING','POLICYBZR','POLYCAB','POWERGRID','POWERINDIA','PRESTIGE','RADICO',
    'RBLBANK','RECLTD','SAIL','SBICARD','SBILIFE','SHREECEM','SHRIRAMFIN','SIEMENS',
    'SOLARINDS','SONACOMS','SRF','SUNDARMFIN','SUPREMEIND','SUZLON','SWIGGY','TATACOMM',
    'TATACONSUM','TATAPOWER','TATASTEEL','TECHM','TIINDIA','TMCV','TMPV','TORNTPHARM',
    'TORNTPOWER','TRENT','TVSMOTOR','ULTRACEMCO','UNIONBANK','UNITDSPR','UNOMINDA','UPL',
    'VBL','VEDL','VMM','VOLTAS','WAAREEENER','WIPRO','ZYDUSLIFE',
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
    if len(df) < 30: return None
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

def scan_vcnb(sess, sym):
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
        # green bar, above VWAP
        if cl <= vwap or cl <= op: continue
        # breaks above 5-bar high
        prior5 = sess.iloc[i - 5: i]
        if hi <= prior5["high"].max(): continue
        # prior 3 bars above VWAP (uptrend)
        prior3 = sess.iloc[i - 3: i]
        above_count = sum(float(b["close"]) > float(b["vwap"])
                         for _, b in prior3.iterrows() if not pd.isna(b["vwap"]))
        if above_count < 2: continue
        # tight consolidation
        sess_range = (sess["high"].max() - sess["low"].min()) / max(1, len(sess))
        p3_range   = prior3["high"].max() - prior3["low"].min()
        if p3_range > sess_range * 4: continue
        # volume surge
        if med_vol > 0 and float(bar["volume"]) < 1.3 * med_vol: continue
        entry  = cl
        sl     = round(float(prior3["low"].min()) * 0.998, 2)
        risk   = entry - sl
        if risk <= 0 or risk / entry > 0.012: continue
        target = round(entry + TGT_MULT * risk, 2)
        outcome, xp = simulate_trade(i, sess, sl, target)
        shares = max(1, int(CAPITAL / entry))
        pnl    = round((xp - entry) * shares, 2)
        trades.append({"symbol": sym, "date": d, "time": t,
                       "entry": entry, "sl": sl, "target": target,
                       "risk_pct": round(risk / entry * 100, 2),
                       "outcome": outcome, "pnl": pnl})
        used.add(d)
    return trades

# ─────────────────────────────────────────────────────────
print(f"\n  Out-of-sample validation: {len(FRESH_STOCKS)} unseen stocks\n")

all_trades = []
skipped = 0
for sym in FRESH_STOCKS:
    df = load_vwap(sym)
    if df is None:
        skipped += 1
        continue
    for d, grp in df.groupby(df.index.date):
        sess = grp
        if len(sess) < 6: continue
        all_trades.extend(scan_vcnb(sess, sym))

print(f"  Stocks scanned: {len(FRESH_STOCKS) - skipped}  |  Skipped: {skipped}\n")

df_all = pd.DataFrame(all_trades)
if len(df_all) == 0:
    print("  No trades found."); exit()

cl  = df_all[df_all["outcome"] != "OPEN"]
w   = (cl["outcome"] == "WIN").sum()
l   = (cl["outcome"] == "SL").sum()
wr  = w / len(cl) * 100 if len(cl) > 0 else 0
pnl = df_all["pnl"].sum()
ev  = wr/100 * 2 - (1 - wr/100) * 1

print(f"  ─────────────────────────────────────────────────────")
print(f"  VCNB Out-of-Sample Results")
print(f"  ─────────────────────────────────────────────────────")
print(f"  Total trades : {len(df_all)}")
print(f"  Closed       : {len(cl)}  (OPEN={len(df_all)-len(cl)})")
print(f"  Wins / Losses: {w} / {l}")
print(f"  Win Rate     : {wr:.1f}%  (discovery was 55.6%)")
print(f"  Total PnL    : ₹{pnl:,.0f}")
print(f"  Avg PnL/trade: ₹{df_all['pnl'].mean():+.0f}")
if len(cl) >= 5:
    print(f"  Expected val : {ev:+.2f}R per trade")
    if wr > 33.3:
        print(f"  ✓ PROFITABLE edge confirmed on unseen stocks")
    else:
        print(f"  ✗ Edge did NOT hold out-of-sample")

print()
print(f"  By Hour:")
df_all["hour"] = df_all["time"].str[:2]
for h, sub in df_all.groupby("hour"):
    cl2 = sub[sub["outcome"] != "OPEN"]
    w2  = (cl2["outcome"] == "WIN").sum() if len(cl2) > 0 else 0
    wr2 = w2 / len(cl2) * 100 if len(cl2) > 0 else 0
    bar = "#" * int(wr2 / 5)
    print(f"    {h}:xx  {len(sub):3d} trades | {bar:<20s} {wr2:5.1f}% | ₹{sub['pnl'].sum():+,.0f}")

print()
print(f"  Top 15 stocks by WR (min 2 trades):")
sym_rows = []
for sym, sub in df_all.groupby("symbol"):
    cl2 = sub[sub["outcome"] != "OPEN"]
    if len(cl2) < 2: continue
    w2  = (cl2["outcome"] == "WIN").sum()
    wr2 = w2 / len(cl2) * 100
    sym_rows.append((sym, len(sub), len(cl2), wr2, sub["pnl"].sum()))
sym_rows.sort(key=lambda x: x[3], reverse=True)
for sym, n, nc, wr2, p2 in sym_rows[:15]:
    bar = "#" * int(wr2 / 5)
    print(f"    {sym:15s}: {n:2d} trades ({nc} closed) | {bar:<20s} {wr2:5.1f}% | ₹{p2:+,.0f}")

print(f"\n  Bottom 10 stocks by WR (min 2 closed):")
for sym, n, nc, wr2, p2 in sym_rows[-10:]:
    bar = "#" * int(wr2 / 5)
    print(f"    {sym:15s}: {n:2d} trades ({nc} closed) | {bar:<20s} {wr2:5.1f}% | ₹{p2:+,.0f}")

print("\n  Done.\n")

"""
backtest_chartink.py
Backtest Pattern B and C on ChartInk 9:35 AM stocks for past 5 trading days.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
from datetime import date, datetime, timedelta
from data_fetcher import get_10min_candles
from indicators import calculate_vwap
from instruments import load_instruments

# ── Config ─────────────────────────────────────────────────────────────────
CHARTINK_FILE  = os.path.join(os.path.dirname(__file__), "Backtest supertrend and convergence.csv")
TRADE_CAPITAL  = 200_000
SIGNAL_CUTOFF  = "10:05"   # last valid candle LABEL (closes at 10:15)

BACKTEST_DAYS = {
    "15-05-2026": date(2026, 5, 15),
    "18-05-2026": date(2026, 5, 18),
    "19-05-2026": date(2026, 5, 19),
}

# ── Load 9:35 AM ChartInk stocks ───────────────────────────────────────────
def load_stocks(filepath):
    df = pd.read_csv(filepath)
    result = {}
    for d_str in BACKTEST_DAYS:
        key = f"{d_str} 9:35 am"
        syms = df[df["date"] == key]["symbol"].tolist()
        if syms:
            result[d_str] = syms
    return result

# ── Instrument key lookup ───────────────────────────────────────────────────
def build_sym_map():
    inst = load_instruments()
    return dict(zip(inst["symbol"], inst["instrument_key"]))

# ── Fetch one day's candles ─────────────────────────────────────────────────
def fetch_day(ikey, target_date):
    days_back = (date.today() - target_date).days + 5
    df = get_10min_candles(ikey, days_back=days_back)
    if df.empty:
        return pd.DataFrame()
    df = df[df.index.date == target_date].copy()
    if df.empty:
        return pd.DataFrame()
    df["vwap"] = calculate_vwap(df)
    return df.dropna(subset=["vwap"])

# ── ATR helper ──────────────────────────────────────────────────────────────
def calc_atr(df, n=10):
    if len(df) < 2:
        return df["close"].iloc[-1] * 0.005
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"]-df["low"], (df["high"]-pc).abs(), (df["low"]-pc).abs()], axis=1).max(axis=1)
    return float(tr.iloc[-n:].mean())

# ── Patterns ────────────────────────────────────────────────────────────────
def pattern_b(df):
    if len(df) < 3: return None
    last = df.iloc[-1]
    if last["close"] <= last["vwap"]: return None

    n_below = 0; max_dip_pct = 0.0
    for i in range(len(df)-2, max(len(df)-6, -1), -1):
        c = df.iloc[i]
        if c["close"] < c["vwap"]:
            n_below += 1
            dip_pct = (c["vwap"] - c["close"]) / c["vwap"]
            if dip_pct > max_dip_pct: max_dip_pct = dip_pct
        else: break

    if not (1 <= n_below <= 3): return None
    # Dip must be a real test — at least 0.15% below VWAP (not noise)
    if max_dip_pct < 0.0015: return None
    bi = len(df) - 2 - n_below
    if bi < 0 or df.iloc[bi]["close"] <= df.iloc[bi]["vwap"]: return None

    entry = last["close"]; sl = last["vwap"]; risk = entry - sl
    if risk <= 0: return None
    # Reclaim candle must be green (close > open) and risk must be meaningful (>=0.3% of entry)
    if last["close"] <= last["open"]: return None
    if risk / entry < 0.003: return None
    breach = df.iloc[len(df)-1-n_below]
    return {"pattern":"B","entry_time":last.name.strftime("%H:%M"),
            "touch_time":breach.name.strftime("%H:%M"),
            "entry":round(entry,2),"sl":round(sl,2),
            "target":round(entry+3*risk,2),"risk":round(risk,2),
            "candles_below":n_below}

def pattern_c(df):
    if len(df) < 4: return None
    atr = calc_atr(df)
    last = df.iloc[-1]
    if last["close"] - last["vwap"] <= atr: return None

    n_retest = 0; ibi = None
    for i in range(len(df)-2, 0, -1):
        c = df.iloc[i]
        if abs(c["close"]-c["vwap"]) <= atr:
            n_retest += 1
        else:
            prev = df.iloc[i-1]
            if prev["close"] < prev["vwap"] and c["close"] > c["vwap"]:
                ibi = i
            break

    if n_retest < 1 or ibi is None: return None
    entry = last["close"]; sl = last["vwap"]; risk = entry - sl
    if risk <= 0: return None
    ic = df.iloc[ibi]
    return {"pattern":"C","entry_time":last.name.strftime("%H:%M"),
            "touch_time":ic.name.strftime("%H:%M"),
            "entry":round(entry,2),"sl":round(sl,2),
            "target":round(entry+3*risk,2),"risk":round(risk,2),
            "retest_candles":n_retest,"atr":round(atr,2)}

# ── Trade simulation ────────────────────────────────────────────────────────
def simulate(sig, full_day):
    entry = sig["entry"]; sl = sig["sl"]; target = sig["target"]
    # candles strictly after entry candle
    future = full_day[full_day.index.strftime("%H:%M") > sig["entry_time"]]

    outcome = "OPEN"; exit_price = None; exit_time = None
    for ts, row in future.iterrows():
        if row["low"] <= sl:
            outcome = "SL_HIT"; exit_price = sl
            exit_time = ts.strftime("%H:%M"); break
        if row["high"] >= target:
            outcome = "TARGET_HIT"; exit_price = target
            exit_time = ts.strftime("%H:%M"); break

    if outcome == "OPEN":
        exit_price = full_day.iloc[-1]["close"]
        exit_time  = full_day.index[-1].strftime("%H:%M")

    shares = int(TRADE_CAPITAL / entry) if entry > 0 else 0
    pnl    = round((exit_price - entry) * shares, 2)
    return {"outcome":outcome,"exit_price":round(exit_price,2),
            "exit_time":exit_time,"shares":shares,"pnl":pnl,
            "pnl_pct":round((exit_price-entry)/entry*100, 2)}

# ── Main ────────────────────────────────────────────────────────────────────
def run():
    print("Loading ChartInk stocks...")
    day_stocks = load_stocks(CHARTINK_FILE)

    print("Loading instrument map...")
    sym_map = build_sym_map()

    all_trades = []

    for d_str, d_date in sorted(BACKTEST_DAYS.items()):
        symbols = day_stocks.get(d_str, [])
        if not symbols:
            print(f"\n[SKIP] {d_str} — no 9:35 AM data"); continue

        print(f"\n{'='*65}")
        print(f"  {d_str}  |  {len(symbols)} stocks: {', '.join(symbols)}")
        print(f"{'='*65}")

        for sym in symbols:
            ikey = sym_map.get(sym)
            if not ikey:
                print(f"  {sym:<18} instrument key not found"); continue

            try:
                df = fetch_day(ikey, d_date)
                if df.empty or len(df) < 4:
                    print(f"  {sym:<18} insufficient data"); continue

                sig = None
                # Check patterns at each candle label from 09:35 to SIGNAL_CUTOFF
                # Candle label = open time; check after 9:35 scan, so first available
                # label with at least 3 prior candles is 09:35 (has 9:15, 9:25, 9:35)
                avail_labels = df[df.index.strftime("%H:%M") <= SIGNAL_CUTOFF].index
                for label in avail_labels:
                    lbl_str = label.strftime("%H:%M")
                    if lbl_str < "09:35": continue   # need at least 3 candles
                    slice_df = df[df.index <= label].copy()
                    if len(slice_df) < 3: continue
                    sig = pattern_b(slice_df) or pattern_c(slice_df)
                    if sig: break

                if not sig:
                    print(f"  {sym:<18} — no signal before 10:15")
                    all_trades.append({"date":d_str,"symbol":sym,"pattern":"-",
                                       "outcome":"NO_SIGNAL","pnl":0,"pnl_pct":0})
                    continue

                res = simulate(sig, df)
                pnl_str = f"{'+'if res['pnl']>=0 else ''}Rs{res['pnl']:>10,.0f}  ({res['pnl_pct']:+.2f}%)"
                print(f"  {sym:<18} Pattern {sig['pattern']}  entry@{sig['entry_time']} Rs{sig['entry']}"
                      f"  SL Rs{sig['sl']}  T Rs{sig['target']}"
                      f"  -> {res['outcome']:<12}@{res['exit_time']}  {pnl_str}")

                all_trades.append({"date":d_str,"symbol":sym,**sig,**res})

            except Exception as e:
                print(f"  {sym:<18} ERROR: {e}")

    # ── Summary ────────────────────────────────────────────────────────────
    out_df = pd.DataFrame(all_trades)
    out_path = os.path.join(os.path.dirname(__file__), "backtest_chartink_results.csv")
    out_df.to_csv(out_path, index=False)

    traded = out_df[out_df["outcome"] != "NO_SIGNAL"]
    print(f"\n{'='*65}")
    print("  BACKTEST SUMMARY")
    print(f"{'='*65}")
    print(f"  Universe (3 days):  {len(out_df)} stock-days")
    print(f"  Signals fired:      {len(traded)}")
    print(f"  No signal:          {len(out_df)-len(traded)}")

    if len(traded):
        target_hits = (traded["outcome"]=="TARGET_HIT").sum()
        sl_hits     = (traded["outcome"]=="SL_HIT").sum()
        eod_exits   = (traded["outcome"]=="OPEN").sum()
        total_pnl   = traded["pnl"].sum()
        win_rate    = target_hits / len(traded) * 100
        print(f"  Target hit:         {target_hits}  ({win_rate:.0f}%)")
        print(f"  SL hit:             {sl_hits}")
        print(f"  Closed at EOD:      {eod_exits}")
        print(f"  Total P&L:          {'+'if total_pnl>=0 else ''}Rs{total_pnl:,.0f}")
        print(f"\n  Per-day breakdown:")
        for d, grp in traded.groupby("date"):
            d_pnl = grp["pnl"].sum()
            print(f"    {d}  signals={len(grp)}  P&L={'+'if d_pnl>=0 else ''}Rs{d_pnl:,.0f}")

    print(f"\n  Results saved -> backtest_chartink_results.csv")

if __name__ == "__main__":
    run()

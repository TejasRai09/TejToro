"""
test.py — Pattern-only test mode.
Scans all 475 stocks for Pattern B/C today, skips every filter.
Shows simulated P&L based on what happened after each signal.

Run:  python test.py
Open: http://localhost:5173
"""
import os, sys, time, asyncio, subprocess, threading, webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

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


def _find_signal(today_df):
    """Scan from 9:35 to latest candle, return first Pattern B or C."""
    avail = today_df[today_df.index.strftime("%H:%M") >= "09:35"]
    for ts in avail.index:
        sl = today_df[today_df.index <= ts]
        if len(sl) < 3: continue
        sig = _pattern_b(sl) or _pattern_c(sl)
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
        df = get_10min_candles(ikey, days_back=1)
        if df.empty: return None
        today_date = df.index[-1].date()
        day_df     = df[df.index.date == today_date].copy()
        if day_df.empty or len(day_df) < 3: return None
        day_df["vwap"] = calculate_vwap(day_df)
        day_df = day_df.dropna(subset=["vwap"])
        if len(day_df) < 3: return None

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

    print(f"\n[TEST] Scanning {len(rows)} stocks for Pattern B/C today...")
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

    print("\n  [TEST MODE] TejToro — No-filter Pattern B/C scan")
    print("  Starting Vite frontend...")
    frontend_proc = subprocess.Popen([NPM, "run", "dev"], cwd=FRONTEND,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Start scan in background — runs while uvicorn is serving
    def _auto_scan():
        time.sleep(1)
        _run_test_scan()

    threading.Thread(target=_auto_scan, daemon=True).start()

    time.sleep(3)
    webbrowser.open("http://localhost:5173")

    print("  Backend  -> http://localhost:8000")
    print("  Frontend -> http://localhost:5173")
    print("  Scan running in background — refresh browser in ~2 min")
    print("  Press Ctrl+C to stop.\n")

    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
    finally:
        frontend_proc.terminate()

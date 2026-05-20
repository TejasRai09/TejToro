"""
server.py — FastAPI backend for VWAP Convergence Scanner
Run: uvicorn server:app --reload --port 8000
"""
import csv
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
    """From below VWAP, initial cross above → retest near VWAP (within 1 ATR) → strong breakout (>1 ATR above VWAP)."""
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


def find_entry(today_df):
    return _pattern_b(today_df) or _pattern_c(today_df)


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


def _run_scan():
    rows = [
        {"symbol": r.symbol, "instrument_key": r.instrument_key, "market_cap_cr": r.market_cap_cr}
        for r in _instruments_1000.itertuples(index=False)
    ]
    done = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_evaluate, row): row["symbol"] for row in rows}
        for future in as_completed(futures):
            done += 1
            state["scan_progress"] = done
            res = future.result()
            if res:
                state["results"].append(res)
    state["scanning"]       = False
    state["last_sig_check"] = time.time()  # first re-check fires 10 min after scan ends


# ── Routes ─────────────────────────────────────────────────────────────────────

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
    state["scan_time"]     = datetime.now(IST).strftime("%H:%M:%S")
    state["alerted_syms"]  = set()
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_scan)
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

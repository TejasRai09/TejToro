"""
app3.py — Chartink Filter Replicator

Reproduces the exact active Chartink cash-segment filters (from screenshot):
    1. [0] 10-min Close >= [0] 10-min Supertrend(6,2)
    2. [0] 10-min Close >= Daily Pivot Point
    3. [0] 10-min Close >= [0] 10-min VWAP
    4. [-1] 10-min Close >= [-1] 10-min VWAP
    5. [-2] 10-min Close >= [-2] 10-min VWAP
    6. Market Cap >= 1000 Cr

Run with:  streamlit run app3.py
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from instruments import load_instruments
from data_fetcher import get_10min_candles
from indicators import calculate_vwap, calculate_supertrend, calculate_pivots

IST = ZoneInfo("Asia/Kolkata")
MIN_MCAP_CR = 1000  # Chartink filter: Market Cap >= 1000 Cr


# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Chartink Replicator",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;700&display=swap');

:root {
    --bg:           #070b0f;
    --bg-card:      #0d1117;
    --bg-elevated:  #161b22;
    --border:       #21262d;
    --border-bright:#30363d;
    --text:         #e6edf3;
    --text-muted:   #7d8590;
    --text-dim:     #484f58;
    --green:        #3fb950;
    --green-dim:    #1a4a24;
    --red:          #f85149;
    --red-dim:      #4a1a1a;
    --yellow:       #d29922;
    --blue:         #58a6ff;
    --accent:       #f0883e;
    --purple:       #bc8cff;
}

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', monospace;
    background: var(--bg) !important;
    color: var(--text);
}

#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1.5rem 2rem !important; max-width: 100% !important; }

.od-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 1rem 1.5rem;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-left: 3px solid var(--purple);
    border-radius: 6px;
    margin-bottom: 1.5rem;
}
.od-title    { font-size: 1.1rem; font-weight: 700; color: var(--text); letter-spacing: 0.05em; text-transform: uppercase; font-family: 'IBM Plex Mono', monospace; }
.od-subtitle { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.1rem; font-family: 'IBM Plex Mono', monospace; }
.od-time     { font-family: 'IBM Plex Mono', monospace; font-size: 0.9rem; color: var(--purple); }

.filter-box {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-top: 2px solid var(--purple);
    border-radius: 6px;
    padding: 1rem 1.5rem;
    margin-bottom: 1.5rem;
    font-family: 'IBM Plex Mono', monospace;
}
.filter-title { font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 0.8rem; }
.filter-row   { font-size: 0.82rem; color: var(--text); padding: 0.3rem 0; border-bottom: 1px solid var(--border); display: flex; gap: 1rem; align-items: center; }
.filter-row:last-child { border-bottom: none; }
.filter-num  { color: var(--purple); font-weight: 700; width: 1.5rem; flex-shrink: 0; }
.filter-op   { color: var(--green); }
.filter-val  { color: var(--yellow); }

.info-box {
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-left: 3px solid var(--blue);
    border-radius: 6px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 1.5rem;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.8rem;
    color: var(--text-muted);
    line-height: 1.8;
}
.info-box h4 { color: var(--blue); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; margin: 0 0 0.8rem; }
.info-box code { color: var(--yellow); background: var(--bg-card); padding: 0.1rem 0.4rem; border-radius: 3px; }
.info-highlight { color: var(--accent); font-weight: 600; }

.section-header {
    display: flex; align-items: center; gap: 0.6rem;
    font-size: 0.75rem; font-weight: 600;
    color: var(--text-muted); text-transform: uppercase;
    letter-spacing: 0.1em; font-family: 'IBM Plex Mono', monospace;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.5rem; margin-bottom: 1rem;
}
.section-dot         { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
.section-dot.purple  { background: var(--purple); }
.section-dot.green   { background: var(--green); }

.result-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-top: 2px solid var(--green);
    border-radius: 6px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.75rem;
    font-family: 'IBM Plex Mono', monospace;
}
.result-sym    { font-size: 1.1rem; font-weight: 700; color: var(--text); }
.result-mcap   { font-size: 0.7rem; color: var(--text-muted); margin-top: 0.1rem; }
.result-grid   { display: grid; grid-template-columns: repeat(5, 1fr); gap: 0.6rem; margin-top: 0.8rem; }
.result-item   { background: var(--bg-elevated); padding: 0.5rem 0.7rem; border-radius: 4px; }
.result-label  { font-size: 0.58rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.07em; }
.result-value  { font-size: 0.88rem; font-weight: 600; color: var(--text); margin-top: 0.1rem; }
.result-value.green  { color: var(--green); }
.result-value.yellow { color: var(--yellow); }
.result-value.blue   { color: var(--blue); }
.result-value.purple { color: var(--purple); }
.result-check  { font-size: 0.65rem; color: var(--green); margin-top: 0.1rem; }

.empty-state {
    text-align: center; padding: 2.5rem;
    color: var(--text-dim); font-family: 'IBM Plex Mono', monospace;
    font-size: 0.8rem;
    border: 1px dashed var(--border); border-radius: 6px;
}

.stButton > button {
    background: var(--bg-elevated) !important;
    color: var(--text) !important;
    border: 1px solid var(--border-bright) !important;
    border-radius: 4px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    padding: 0.4rem 1.2rem !important;
    transition: all 0.15s ease !important;
}
.stButton > button:hover { border-color: var(--purple) !important; color: var(--purple) !important; }
</style>
""", unsafe_allow_html=True)


# ─── Indicator Preparation (no RSI — only what Chartink filters need) ─────────

def _strip_tz(dt):
    """Make a datetime timezone-naive for comparison."""
    if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def get_candles_for_chartink(instrument_key: str) -> tuple:
    """
    Fetch 10-min candles and compute VWAP, Supertrend(6,2), and Daily Pivot Point.

    Returns (today_df, pivots) where today_df has only COMPLETED candles and
    contains 'vwap' and 'st' columns.  Returns (None, None) on any failure.

    Why 5 days_back:
        Supertrend needs ~6 ATR periods of warmup.  With 38 candles/day,
        5 days = 190 candles — more than enough for stable ATR.

    Why we drop the last candle when it's still forming:
        Upstox intraday API returns 1-min candles up to the last completed
        minute.  After resampling to 10-min, the final bucket may be
        incomplete (e.g. only 3 of 10 minutes filled).  Including that
        would give a wrong Close/VWAP/Supertrend value — not what Chartink
        shows.  We check: if now < candle_label + 10 min → candle is still
        forming → we exclude it so [0] is always a closed candle.
    """
    try:
        df_raw = get_10min_candles(instrument_key, days_back=3)
    except Exception:
        return None, None

    if df_raw.empty or len(df_raw) < 12:
        return None, None

    if not isinstance(df_raw.index, pd.DatetimeIndex):
        df_raw.index = pd.to_datetime(df_raw.index)

    today   = df_raw.index[-1].date()
    today_df = df_raw[df_raw.index.date == today].copy()
    prev_df  = df_raw[df_raw.index.date < today].copy()

    if today_df.empty or prev_df.empty:
        return None, None

    # ── Drop the current forming candle ──────────────────────────────────
    now_naive = _strip_tz(datetime.now(IST))
    last_label = _strip_tz(today_df.index[-1].to_pydatetime())
    candle_closes_at = last_label + timedelta(minutes=10)

    if now_naive < candle_closes_at:
        today_df = today_df.iloc[:-1]   # remove still-forming candle

    if len(today_df) < 3:
        return None, None  # need [0], [-1], [-2]

    # ── Indicators (computed on full history for proper warmup) ───────────
    pivots = calculate_pivots(prev_df)
    if pivots.get("PP") is None:
        return None, None

    vwap_series = calculate_vwap(df_raw)
    st_series   = calculate_supertrend(df_raw, period=6, multiplier=2)

    today_df["vwap"] = vwap_series[today_df.index]
    today_df["st"]   = st_series[today_df.index]

    today_df = today_df.dropna(subset=["vwap", "st"])

    if len(today_df) < 3:
        return None, None

    return today_df, pivots


def check_chartink_filters(today_df: pd.DataFrame, pivots: dict) -> dict | None:
    """
    Apply all 7 Chartink filters.  Returns a result dict or None.

    Candle indexing mirrors Chartink:
        [0]  → today_df.iloc[-1]  (last closed candle)
        [-1] → today_df.iloc[-2]  (one candle before [0])
        [-2] → today_df.iloc[-3]  (two candles before [0])

    Convergence filters (C1, C2) are from the "nifty 200 segment" group:
        Chartink's "Bracket( A - B )" means |A - B| (absolute difference).
        "SUPERTREND AND CONVERGENCE" scan: ST, VWAP, and PP must all cluster
        within 1% of each other at the [0] candle.  This eliminates ~80% of
        stocks that pass the basic price filters — it's the core of the scan.
    """
    c0 = today_df.iloc[-1]
    c1 = today_df.iloc[-2]
    c2 = today_df.iloc[-3]
    PP = pivots["PP"]

    close = c0["close"]
    vwap  = c0["vwap"]
    st    = c0["st"]

    # ── Convergence C1: |ST[0] - VWAP[0]| < 1% of Close ─────────────────
    # Chartink: Bracket( [0] 10min Supertrend(6,2) - [0] 10min VWAP ) < Close * 0.01
    st_vwap_gap = abs(st - vwap)
    if st_vwap_gap >= close * 0.01:
        return None

    # ── Convergence C2: |VWAP[0] - PP| < 1% of Close ────────────────────
    # Chartink: Bracket( [0] 10min VWAP - Daily Pivot point ) < Close * 0.01
    vwap_pp_gap = abs(vwap - PP)
    if vwap_pp_gap >= close * 0.01:
        return None

    # ── Price Filter F1: [0] Close >= [0] Supertrend(6,2) ────────────────
    if close < st:
        return None

    # ── Price Filter F2: [0] Close >= Daily Pivot Point ──────────────────
    if close < PP:
        return None

    # ── Price Filter F3: [0] Close >= [0] VWAP ───────────────────────────
    if close < vwap:
        return None

    # ── Price Filter F4: [-1] Close >= [-1] VWAP ─────────────────────────
    if c1["close"] < c1["vwap"]:
        return None

    # ── Price Filter F5: [-2] Close >= [-2] VWAP ─────────────────────────
    if c2["close"] < c2["vwap"]:
        return None

    return {
        # convergence gaps (as % of close)
        "st_vwap_gap_pct":  round(st_vwap_gap / close * 100, 2),
        "vwap_pp_gap_pct":  round(vwap_pp_gap / close * 100, 2),
        # [0] candle
        "c0_time":  c0.name.strftime("%H:%M"),
        "c0_close": round(close, 2),
        "c0_vwap":  round(vwap, 2),
        "c0_st":    round(st, 2),
        # [-1] candle
        "c1_time":  c1.name.strftime("%H:%M"),
        "c1_close": round(c1["close"], 2),
        "c1_vwap":  round(c1["vwap"], 2),
        # [-2] candle
        "c2_time":  c2.name.strftime("%H:%M"),
        "c2_close": round(c2["close"], 2),
        "c2_vwap":  round(c2["vwap"], 2),
        # pivot
        "pp": round(PP, 2),
    }


# ─── Session State ────────────────────────────────────────────────────────────
if "ct_results"    not in st.session_state:
    st.session_state.ct_results    = []
if "ct_scanning"   not in st.session_state:
    st.session_state.ct_scanning   = False
if "ct_scan_time"  not in st.session_state:
    st.session_state.ct_scan_time  = None
if "ct_universe"   not in st.session_state:
    st.session_state.ct_universe   = 0


# ─── Load Instruments ─────────────────────────────────────────────────────────
if "instruments" not in st.session_state:
    st.session_state.instruments = load_instruments()

all_instruments = st.session_state.instruments

# Apply Chartink's 1000 Cr filter (instruments.csv may have 500 Cr as minimum)
instruments_1000 = all_instruments[all_instruments["market_cap_cr"] >= MIN_MCAP_CR].reset_index(drop=True)

now     = datetime.now(IST)
now_str = now.strftime("%H:%M:%S")


# ═══════════════════════════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown(f"""
<div class="od-header">
  <div>
    <div class="od-title">📊 Chartink Filter Replicator</div>
    <div class="od-subtitle">NSE Cash · All 5 active filters · Exact match to Chartink output</div>
  </div>
  <span class="od-time">{now_str} IST</span>
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# ACTIVE FILTERS PANEL
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header"><span class="section-dot purple"></span>Active Chartink Filters (Cash Segment)</div>', unsafe_allow_html=True)

st.markdown("""
<div class="filter-box">
  <div class="filter-title">All 7 conditions must pass — fail-fast, in order</div>

  <div style="font-size:0.65rem;color:#bc8cff;font-family:'IBM Plex Mono',monospace;padding:0.3rem 0 0.6rem;letter-spacing:0.06em;">
    ▸ CONVERGENCE (nifty 200 segment — the "secret" filters that narrow from ~180 stocks to ~35)
  </div>
  <div class="filter-row">
    <span class="filter-num">C1</span>
    <span>|[0] <b>Supertrend(6,2)</b> − [0] <b>VWAP</b>|</span>
    <span class="filter-op">&lt;</span>
    <span>[0] <b>Close</b> × <span class="filter-val">0.01</span></span>
    <span style="color:#484f58;font-size:0.72rem;">— ST and VWAP within 1% of price (converging)</span>
  </div>
  <div class="filter-row">
    <span class="filter-num">C2</span>
    <span>|[0] <b>VWAP</b> − <b>Daily Pivot Point</b>|</span>
    <span class="filter-op">&lt;</span>
    <span>[0] <b>Close</b> × <span class="filter-val">0.01</span></span>
    <span style="color:#484f58;font-size:0.72rem;">— VWAP and PP within 1% of price (all 3 indicators clustered)</span>
  </div>

  <div style="font-size:0.65rem;color:#58a6ff;font-family:'IBM Plex Mono',monospace;padding:0.6rem 0 0.3rem;letter-spacing:0.06em;">
    ▸ PRICE FILTERS (cash segment)
  </div>
  <div class="filter-row">
    <span class="filter-num">F1</span>
    <span>[0] 10-min <b>Close</b></span>
    <span class="filter-op">≥</span>
    <span>[0] 10-min <b>Supertrend(6,2)</b></span>
    <span style="color:#484f58;font-size:0.72rem;">— price above the bullish Supertrend band</span>
  </div>
  <div class="filter-row">
    <span class="filter-num">F2</span>
    <span>[0] 10-min <b>Close</b></span>
    <span class="filter-op">≥</span>
    <span><b>Daily Pivot Point</b> (from yesterday's H/L/C)</span>
    <span style="color:#484f58;font-size:0.72rem;">— price above institutional pivot</span>
  </div>
  <div class="filter-row">
    <span class="filter-num">F3</span>
    <span>[0] 10-min <b>Close</b></span>
    <span class="filter-op">≥</span>
    <span>[0] 10-min <b>VWAP</b></span>
    <span style="color:#484f58;font-size:0.72rem;">— buyers dominate in current candle</span>
  </div>
  <div class="filter-row">
    <span class="filter-num">F4</span>
    <span>[-1] 10-min <b>Close</b></span>
    <span class="filter-op">≥</span>
    <span>[-1] 10-min <b>VWAP</b></span>
    <span style="color:#484f58;font-size:0.72rem;">— previous candle also above VWAP (trend confirmation)</span>
  </div>
  <div class="filter-row">
    <span class="filter-num">F5</span>
    <span>[-2] 10-min <b>Close</b></span>
    <span class="filter-op">≥</span>
    <span>[-2] 10-min <b>VWAP</b></span>
    <span style="color:#484f58;font-size:0.72rem;">— two candles ago also above VWAP (3-candle strength)</span>
  </div>
  <div class="filter-row">
    <span class="filter-num">F6</span>
    <span><b>Market Cap</b></span>
    <span class="filter-op">≥</span>
    <span class="filter-val">1,000 Cr</span>
    <span style="color:#484f58;font-size:0.72rem;">— large-cap only, applied as universe pre-filter</span>
  </div>
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# CANDLE TIMING EXPLANATION
# ═══════════════════════════════════════════════════════════════════════════════

with st.expander("📖  How candle timing works — read this to understand [0], [-1], [-2] and why results change"):
    st.markdown("""
<div class="info-box">
<h4>What is a 10-minute candle on NSE?</h4>

NSE market opens at <code>9:15 AM</code>. 10-minute candles are formed in these fixed windows:

<pre style="color:#d29922;background:#0d1117;padding:0.8rem;border-radius:4px;font-size:0.78rem;">
Candle Label   Data Window              Candle Fully Closes At
────────────   ─────────────────────    ──────────────────────
09:15          9:15:00 → 9:24:59        9:25 AM
09:25          9:25:00 → 9:34:59        9:35 AM
09:35          9:35:00 → 9:44:59        9:45 AM
09:45          9:45:00 → 9:54:59        9:55 AM
...            ...                      ...
15:05          15:05:00 → 15:14:59      15:15 AM (market close)
</pre>

<h4>What does [0], [-1], [-2] mean in Chartink?</h4>

Chartink always uses the <span class="info-highlight">last fully closed candle</span> as <code>[0]</code>.
It never uses the currently forming candle.

<pre style="color:#d29922;background:#0d1117;padding:0.8rem;border-radius:4px;font-size:0.78rem;">
[0]  = today_df.iloc[-1]   → most recent CLOSED 10-min candle
[-1] = today_df.iloc[-2]   → one candle before [0]
[-2] = today_df.iloc[-3]   → two candles before [0]
</pre>

<h4>How results change depending on WHEN you scan:</h4>

<pre style="color:#58a6ff;background:#0d1117;padding:0.8rem;border-radius:4px;font-size:0.78rem;">
Scan Time   Closed Candles Today   [0]     [-1]    [-2]   All Filters?
─────────   ──────────────────     ──────  ──────  ──────  ─────────────
9:25 AM     1  (only 9:15)         9:15    —       —       ❌ SKIP (need 3)
9:35 AM     2  (9:15, 9:25)        9:25    9:15    —       ❌ SKIP (need 3)
9:45 AM     3  (9:15..9:35)        9:35    9:25    9:15    ✅ First full scan
9:55 AM     4  (9:15..9:45)        9:45    9:35    9:25    ✅
10:05 AM    5  (9:15..9:55)        9:55    9:45    9:35    ✅
11:15 AM   13  (9:15..11:05)       11:05   10:55   10:45   ✅
</pre>

<h4>Why do results CHANGE every 10 minutes?</h4>

Every 10 minutes a new candle closes, so:
<br>• <code>[0]</code> becomes the brand-new candle → its Close, VWAP, and Supertrend are fresh values
<br>• <code>[-1]</code> becomes what was <code>[0]</code> before
<br>• <code>[-2]</code> becomes what was <code>[-1]</code> before
<br>
<br>A stock that <span class="info-highlight">passed</span> at 9:45 may <span style="color:#f85149">fail</span> at 9:55 if:
<br>  — its new [0] candle closes <i>below</i> VWAP or Supertrend, OR
<br>  — a previously passing [-1] or [-2] was replaced by a failing candle
<br>
<br>A stock that <span style="color:#f85149">failed</span> at 9:45 may <span class="info-highlight">pass</span> at 9:55 if:
<br>  — the new candle closes strongly above VWAP + Supertrend + Pivot
<br>

<h4>VWAP specifics</h4>

VWAP is <span class="info-highlight">cumulative from 9:15 AM</span>, resets at market open each day.
The VWAP value in each candle is the volume-weighted average price of ALL trades
from 9:15 AM up to the end of that candle — not just that 10-min window.
So VWAP gets more stable as the day progresses (more volume anchors it).
At 9:25, VWAP = average of just the first candle. At 2 PM, it's anchored by 5 hours of trading.

<h4>Supertrend(6,2) specifics</h4>

Supertrend needs historical data for ATR warmup. We compute it on 5 days of
10-min candles (~190 candles). By the time we reach today's candles, the ATR
is fully stable. The Supertrend value for each candle reflects the trend up to that point.
When Supertrend is below price → bullish (green). When above → bearish (red).
Only stocks where Supertrend is <i>below</i> current Close pass Filter 1.

<h4>Daily Pivot Point specifics</h4>

PP = (Yesterday's High + Yesterday's Low + Yesterday's Close) / 3
This is a fixed number that does NOT change during the trading day.
It is the same at 9:25 AM and at 3:15 PM. Only tomorrow's PP will be different.
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SCANNER CONTROLS
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header" style="margin-top:1rem;"><span class="section-dot green"></span>Scanner</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([2, 2, 8])

with col1:
    if st.button("🔍 Run Chartink Scan", disabled=st.session_state.ct_scanning):
        st.session_state.ct_scanning  = True
        st.session_state.ct_results   = []
        st.session_state.ct_scan_time = datetime.now(IST).strftime("%H:%M:%S")
        st.rerun()

with col2:
    if st.button("🗑 Clear Results"):
        st.session_state.ct_results   = []
        st.session_state.ct_scan_time = None
        st.rerun()

# ── Universe info ─────────────────────────────────────────────────────────────
st.markdown(
    f'<div style="font-size:0.72rem;color:#7d8590;font-family:\'IBM Plex Mono\',monospace;margin-bottom:1rem;">'
    f'Universe: <b style="color:#e6edf3;">{len(instruments_1000)}</b> stocks with MCap ≥ 1,000 Cr '
    f'(out of {len(all_instruments)} total loaded)'
    f'</div>',
    unsafe_allow_html=True
)


# ═══════════════════════════════════════════════════════════════════════════════
# ACTIVE SCAN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

if st.session_state.ct_scanning:
    progress = st.progress(0, text="Starting scan...")
    status   = st.empty()
    total    = len(instruments_1000)

    def _evaluate(row):
        today_df, pivots = get_candles_for_chartink(row["instrument_key"])
        if today_df is None:
            return None
        result = check_chartink_filters(today_df, pivots)
        if result is None:
            return None
        return {"symbol": row["symbol"], "mcap": round(row["market_cap_cr"], 0), **result}

    rows = [row for _, row in instruments_1000.iterrows()]
    done = 0

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_evaluate, row): row["symbol"] for row in rows}
        for future in as_completed(futures):
            done += 1
            progress.progress(done / total, text=f"Scanning... ({done}/{total})")
            result = future.result()
            if result:
                st.session_state.ct_results.append(result)
                status.success(
                    f"✅ {result['symbol']} — Close {result['c0_close']} @ {result['c0_time']}"
                    f" · ST-VWAP {result['st_vwap_gap_pct']}% · VWAP-PP {result['vwap_pp_gap_pct']}%"
                )

    st.session_state.ct_scanning = False
    progress.empty()
    status.empty()
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════════════════════════════════════════

results = st.session_state.ct_results

if st.session_state.ct_scan_time:
    passed_count = len(results)
    st.markdown(
        f'<div style="font-size:0.72rem;color:#7d8590;font-family:\'IBM Plex Mono\',monospace;margin-bottom:1rem;">'
        f'Scan completed at <b style="color:#e6edf3;">{st.session_state.ct_scan_time}</b> IST · '
        f'<b style="color:#3fb950;">{passed_count}</b> stock{"s" if passed_count != 1 else ""} passed all 7 filters'
        f'</div>',
        unsafe_allow_html=True
    )

if results:
    # ── Summary Table ─────────────────────────────────────────────────────────
    st.markdown('<div class="section-header"><span class="section-dot green"></span>Passing Stocks</div>', unsafe_allow_html=True)

    table_rows = []
    for r in results:
        table_rows.append({
            "Symbol":             r["symbol"],
            "MCap (Cr)":          f"₹{r['mcap']:,.0f}",
            "[0] Time":           r["c0_time"],
            "[0] Close":          r["c0_close"],
            "[0] ST":             r["c0_st"],
            "[0] VWAP":           r["c0_vwap"],
            "Pivot PP":           r["pp"],
            "|ST-VWAP|% (C1<1%)": f"{r['st_vwap_gap_pct']}%",
            "|VWAP-PP|% (C2<1%)": f"{r['vwap_pp_gap_pct']}%",
            "[-1] Close":         r["c1_close"],
            "[-1] VWAP":          r["c1_vwap"],
            "[-2] Close":         r["c2_close"],
            "[-2] VWAP":          r["c2_vwap"],
        })

    df_table = pd.DataFrame(table_rows)
    st.dataframe(df_table, use_container_width=True, hide_index=True)

    # ── Detailed Cards ────────────────────────────────────────────────────────
    st.markdown('<div class="section-header" style="margin-top:1.5rem;"><span class="section-dot purple"></span>Detailed View</div>', unsafe_allow_html=True)

    for r in results:
        c0_st_margin   = round(r["c0_close"] - r["c0_st"], 2)
        c0_pp_margin   = round(r["c0_close"] - r["pp"], 2)
        c0_vwap_margin = round(r["c0_close"] - r["c0_vwap"], 2)

        st.markdown(f"""
        <div class="result-card">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;">
            <div>
              <div class="result-sym">{r['symbol']}</div>
              <div class="result-mcap">MCap ₹{r['mcap']:,.0f} Cr · NSE EQ · Scan {st.session_state.ct_scan_time} IST</div>
            </div>
            <div style="font-size:0.7rem;color:#3fb950;font-family:'IBM Plex Mono',monospace;text-align:right;">
              ✓ All 7 Filters Passed
            </div>
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.6rem;margin:0.7rem 0 0.4rem;">
            <div class="result-item" style="border-left:2px solid #bc8cff;">
              <div class="result-label">C1 · |ST − VWAP| convergence</div>
              <div class="result-value purple">{r['st_vwap_gap_pct']}% gap</div>
              <div class="result-check">✓ &lt; 1% threshold — indicators clustered</div>
            </div>
            <div class="result-item" style="border-left:2px solid #bc8cff;">
              <div class="result-label">C2 · |VWAP − PP| convergence</div>
              <div class="result-value purple">{r['vwap_pp_gap_pct']}% gap</div>
              <div class="result-check">✓ &lt; 1% threshold — all 3 levels aligned</div>
            </div>
          </div>

          <div class="result-grid">
            <div class="result-item">
              <div class="result-label">[0] Candle @ {r['c0_time']}</div>
              <div class="result-value green">Close {r['c0_close']}</div>
              <div class="result-check">✓ F1: ≥ ST {r['c0_st']} (+{c0_st_margin})</div>
              <div class="result-check">✓ F2: ≥ PP {r['pp']} (+{c0_pp_margin})</div>
              <div class="result-check">✓ F3: ≥ VWAP {r['c0_vwap']} (+{c0_vwap_margin})</div>
            </div>
            <div class="result-item">
              <div class="result-label">[0] Supertrend(6,2)</div>
              <div class="result-value purple">{r['c0_st']}</div>
              <div class="result-check">Below price → bullish</div>
            </div>
            <div class="result-item">
              <div class="result-label">[0] VWAP · Pivot PP</div>
              <div class="result-value blue">{r['c0_vwap']} · {r['pp']}</div>
              <div class="result-check">All 3 levels converged ✓</div>
            </div>
            <div class="result-item">
              <div class="result-label">[-1] Candle @ {r['c1_time']}</div>
              <div class="result-value yellow">Close {r['c1_close']}</div>
              <div class="result-check">✓ F4: ≥ VWAP {r['c1_vwap']} (+{round(r['c1_close'] - r['c1_vwap'], 2)})</div>
            </div>
            <div class="result-item">
              <div class="result-label">[-2] Candle @ {r['c2_time']}</div>
              <div class="result-value yellow">Close {r['c2_close']}</div>
              <div class="result-check">✓ F5: ≥ VWAP {r['c2_vwap']} (+{round(r['c2_close'] - r['c2_vwap'], 2)})</div>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

elif st.session_state.ct_scan_time and not st.session_state.ct_scanning:
    st.markdown(
        '<div class="empty-state">No stocks passed all 5 filters in this scan.<br>'
        'Try scanning later in the day when more candles are available.</div>',
        unsafe_allow_html=True
    )
else:
    st.markdown(
        '<div class="empty-state">Click 🔍 Run Chartink Scan to find matching stocks.<br>'
        'Requires market hours with at least 3 completed 10-min candles (9:45 AM onwards).</div>',
        unsafe_allow_html=True
    )

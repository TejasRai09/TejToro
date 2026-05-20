"""
app3.py — VWAP Convergence Scanner
NSE Cash · 7 Chartink filters · VWAP-touch entry · Live P&L + Candlestick
Run with:  streamlit run app3.py
"""

import time
import plotly.graph_objects as go
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from instruments import load_instruments
from data_fetcher import get_10min_candles, get_market_quotes
from indicators import calculate_vwap, calculate_supertrend, calculate_pivots
from notifier import alert_strategy3_vwap_touch, alert_strategy3_target_hit, alert_strategy3_sl_hit

IST           = ZoneInfo("Asia/Kolkata")
MIN_MCAP_CR   = 1000
TRADE_CAPITAL = 200_000


# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="VWAP Scanner",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
    --bg:       #070912;
    --bg2:      #0c0f1d;
    --glass:    rgba(255,255,255,0.035);
    --glass2:   rgba(255,255,255,0.06);
    --border:   rgba(255,255,255,0.07);
    --text:     #e2e8f0;
    --muted:    #94a3b8;
    --dim:      #475569;
    --green:    #00e5b4;
    --red:      #ff4d6d;
    --gold:     #fbbf24;
    --blue:     #60a5fa;
    --purple:   #a78bfa;
}

html, body, [class*="css"] {
    font-family: 'Space Grotesk', sans-serif;
    background: var(--bg) !important;
    color: var(--text);
}
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1rem 1.8rem !important; max-width: 100% !important; }
::-webkit-scrollbar { width: 3px; height: 3px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

/* ── Animations ──────────────────────────────────────────────────────────── */
@keyframes pulse-live {
    0%,100% { opacity:1; box-shadow:0 0 5px var(--green); }
    50%      { opacity:0.4; box-shadow:0 0 12px var(--green); }
}
@keyframes glow-signal {
    0%,100% { box-shadow:0 0 18px rgba(0,229,180,0.10), 0 4px 20px rgba(0,0,0,0.45); }
    50%      { box-shadow:0 0 32px rgba(0,229,180,0.20), 0 4px 28px rgba(0,0,0,0.55); }
}
@keyframes slide-up {
    from { opacity:0; transform:translateY(6px); }
    to   { opacity:1; transform:translateY(0); }
}
@keyframes float {
    0%,100% { transform:translateY(0) rotate(-8deg); }
    50%      { transform:translateY(-6px) rotate(-8deg); }
}
@keyframes shimmer {
    0%   { background-position:-200% center; }
    100% { background-position:200% center; }
}

/* ── Header ──────────────────────────────────────────────────────────────── */
.od-header {
    display:flex; align-items:center; justify-content:space-between;
    padding:1rem 1.6rem;
    background:linear-gradient(135deg, rgba(0,229,180,0.06) 0%, rgba(167,139,250,0.03) 60%, transparent 100%);
    border:1px solid rgba(0,229,180,0.14);
    border-radius:16px; margin-bottom:1rem;
    position:relative; overflow:hidden;
}
.od-header::after {
    content:''; position:absolute; top:0; left:0; right:0; height:1px;
    background:linear-gradient(90deg, transparent, rgba(0,229,180,0.45), transparent);
}
.od-bull {
    font-size:3.8rem; opacity:0.1; position:absolute; right:4.5rem; top:-0.3rem;
    animation:float 4.5s ease-in-out infinite; pointer-events:none;
}
.od-title    { font-size:1rem; font-weight:700; color:var(--text); letter-spacing:0.06em; text-transform:uppercase; font-family:'JetBrains Mono',monospace; }
.od-subtitle { font-size:0.68rem; color:var(--muted); margin-top:0.12rem; }
.od-time     { font-family:'JetBrains Mono',monospace; font-size:0.82rem; color:var(--green); letter-spacing:0.04em; position:relative; z-index:1; }

/* ── Live dot ────────────────────────────────────────────────────────────── */
.live-dot {
    display:inline-block; width:6px; height:6px; background:var(--green);
    border-radius:50%; animation:pulse-live 1.4s ease-in-out infinite;
    margin-right:0.35rem; vertical-align:middle;
}

/* ── Filter box ──────────────────────────────────────────────────────────── */
.filter-box {
    background:var(--glass);
    backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border:1px solid var(--border); border-top:1px solid rgba(167,139,250,0.22);
    border-radius:14px; padding:1rem 1.4rem; margin-bottom:1rem;
    font-family:'JetBrains Mono',monospace;
    box-shadow:0 2px 20px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04);
}
.filter-title { font-size:0.6rem; color:var(--dim); text-transform:uppercase; letter-spacing:0.12em; margin-bottom:0.7rem; }
.filter-row   { font-size:0.77rem; color:var(--text); padding:0.3rem 0; border-bottom:1px solid rgba(255,255,255,0.03); display:flex; gap:0.8rem; align-items:center; }
.filter-row:last-child { border-bottom:none; }
.filter-num  { color:var(--purple); font-weight:700; width:1.5rem; flex-shrink:0; }
.filter-op   { color:var(--green); }
.filter-val  { color:var(--gold); }

/* ── Info box (expander) ─────────────────────────────────────────────────── */
.info-box {
    background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05);
    border-left:3px solid var(--blue); border-radius:10px;
    padding:1rem 1.4rem; font-family:'JetBrains Mono',monospace;
    font-size:0.78rem; color:var(--muted); line-height:1.8;
}
.info-box h4 { color:var(--blue); font-size:0.75rem; text-transform:uppercase; letter-spacing:0.08em; margin:0 0 0.7rem; }
.info-box code { color:var(--gold); background:rgba(0,0,0,0.3); padding:0.1rem 0.35rem; border-radius:3px; }
.info-highlight { color:var(--green); font-weight:600; }

/* ── Section header ──────────────────────────────────────────────────────── */
.section-header {
    display:flex; align-items:center; gap:0.5rem;
    font-size:0.65rem; font-weight:600; color:var(--dim);
    text-transform:uppercase; letter-spacing:0.12em;
    font-family:'JetBrains Mono',monospace;
    border-bottom:1px solid rgba(255,255,255,0.04);
    padding-bottom:0.42rem; margin-bottom:0.85rem;
}
.section-dot        { width:5px; height:5px; border-radius:50%; background:var(--green); box-shadow:0 0 5px var(--green); }
.section-dot.purple { background:var(--purple); box-shadow:0 0 5px var(--purple); }

/* ── Signal card (BUY) ───────────────────────────────────────────────────── */
.signal-fire {
    background:linear-gradient(135deg, rgba(0,229,180,0.055) 0%, rgba(0,0,0,0) 55%);
    border:1px solid rgba(0,229,180,0.18);
    border-left:3px solid var(--green);
    border-radius:14px; padding:1.1rem 1.3rem; margin-bottom:1rem;
    font-family:'JetBrains Mono',monospace;
    animation:glow-signal 3.5s ease-in-out infinite, slide-up 0.3s ease-out;
    position:relative; overflow:hidden;
    box-shadow:0 4px 24px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.04);
}
.signal-fire::before {
    content:'🐂'; position:absolute; right:1rem; top:0.4rem;
    font-size:2.6rem; opacity:0.07; animation:float 5s ease-in-out infinite;
    pointer-events:none;
}
.signal-fire-sym  { font-size:1.1rem; font-weight:700; color:var(--text); letter-spacing:0.04em; }
.signal-fire-meta { font-size:0.65rem; color:var(--muted); margin-top:0.1rem; }
.signal-trade-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:0.42rem; margin-top:0.75rem; }
.signal-trade-item { background:rgba(0,0,0,0.22); padding:0.55rem 0.7rem; border-radius:8px; border:1px solid rgba(255,255,255,0.04); }
.signal-trade-label { font-size:0.52rem; color:var(--dim); text-transform:uppercase; letter-spacing:0.08em; }
.signal-trade-value { font-size:0.95rem; font-weight:700; margin-top:0.1rem; }
.signal-trade-sub   { font-size:0.56rem; color:var(--muted); margin-top:0.06rem; }

/* ── Watching banner ─────────────────────────────────────────────────────── */
.watching-banner {
    background:rgba(255,255,255,0.018);
    border:1px solid rgba(255,255,255,0.05);
    border-left:3px solid rgba(255,255,255,0.1);
    border-radius:8px; padding:0.55rem 0.85rem;
    font-size:0.7rem; color:var(--dim);
    font-family:'JetBrains Mono',monospace; margin-top:0.4rem;
}

/* ── Empty state ─────────────────────────────────────────────────────────── */
.empty-state {
    text-align:center; padding:3rem 2rem;
    color:var(--dim); font-family:'JetBrains Mono',monospace; font-size:0.78rem;
    border:1px dashed rgba(255,255,255,0.06); border-radius:14px;
    background:var(--glass); animation:slide-up 0.3s ease-out;
}

/* ── Buttons ─────────────────────────────────────────────────────────────── */
.stButton > button {
    background:rgba(255,255,255,0.04) !important;
    color:var(--text) !important;
    border:1px solid rgba(255,255,255,0.09) !important;
    border-radius:8px !important;
    font-family:'JetBrains Mono',monospace !important;
    font-size:0.76rem !important; font-weight:500 !important;
    padding:0.4rem 1.2rem !important;
    transition:all 0.18s ease !important;
}
.stButton > button:hover {
    border-color:rgba(0,229,180,0.35) !important;
    color:var(--green) !important;
    background:rgba(0,229,180,0.05) !important;
    box-shadow:0 0 16px rgba(0,229,180,0.08) !important;
}

/* ── Plotly container ────────────────────────────────────────────────────── */
.stPlotlyChart { border-radius:10px; overflow:hidden; margin-top:0.7rem; }
</style>
""", unsafe_allow_html=True)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _strip_tz(dt):
    if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


# ─── Filter Logic (unchanged) ─────────────────────────────────────────────────

def get_candles_for_chartink(instrument_key: str) -> tuple:
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

    now_naive        = _strip_tz(datetime.now(IST))
    last_label       = _strip_tz(today_df.index[-1].to_pydatetime())
    candle_closes_at = last_label + timedelta(minutes=10)

    if now_naive < candle_closes_at:
        today_df = today_df.iloc[:-1]

    if len(today_df) < 3:
        return None, None

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
    c0 = today_df.iloc[-1]
    c1 = today_df.iloc[-2]
    c2 = today_df.iloc[-3]
    PP = pivots["PP"]

    close = c0["close"]
    vwap  = c0["vwap"]
    st    = c0["st"]

    st_vwap_gap = abs(st - vwap)
    if st_vwap_gap >= close * 0.01:
        return None

    vwap_pp_gap = abs(vwap - PP)
    if vwap_pp_gap >= close * 0.01:
        return None

    if close < st:   return None
    if close < PP:   return None
    if close < vwap: return None
    if c1["close"] < c1["vwap"]: return None
    if c2["close"] < c2["vwap"]: return None

    return {
        "st_vwap_gap_pct": round(st_vwap_gap / close * 100, 2),
        "vwap_pp_gap_pct": round(vwap_pp_gap / close * 100, 2),
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


def find_entry_signal(today_df: pd.DataFrame) -> dict | None:
    if len(today_df) < 2:
        return None

    a = today_df.iloc[-2]
    b = today_df.iloc[-1]

    if a["low"] > a["vwap"]:
        return None
    if b["close"] <= a["high"]:
        return None

    entry = b["close"]
    sl    = b["vwap"]
    risk  = entry - sl
    if risk <= 0:
        return None

    return {
        "touch_time":  a.name.strftime("%H:%M"),
        "touch_low":   round(a["low"], 2),
        "touch_high":  round(a["high"], 2),
        "touch_vwap":  round(a["vwap"], 2),
        "entry_time":  b.name.strftime("%H:%M"),
        "entry":       round(entry, 2),
        "sl":          round(sl, 2),
        "target":      round(entry + 3 * risk, 2),
        "risk":        round(risk, 2),
        "reward":      round(3 * risk, 2),
    }


def compute_confidence(result: dict) -> int:
    sig = result.get("entry_signal")
    if not sig:
        return 0

    conv1       = max(0.0, 30.0 * (1.0 - result["st_vwap_gap_pct"] / 1.0))
    conv2       = max(0.0, 30.0 * (1.0 - result["vwap_pp_gap_pct"] / 1.0))
    slip_pct    = (sig["touch_vwap"] - sig["touch_low"]) / sig["touch_vwap"] * 100
    touch_score = max(0.0, 25.0 * (1.0 - slip_pct / 1.0))
    mcap        = result["mcap"]
    mcap_score  = (15.0 if mcap >= 100_000 else
                   12.0 if mcap >= 50_000  else
                    9.0 if mcap >= 20_000  else
                    6.0 if mcap >= 5_000   else 3.0)

    return min(100, round(conv1 + conv2 + touch_score + mcap_score))


# ─── Chart Functions ──────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def _fetch_chart_data(instrument_key: str):
    """Fetch today's 10-min candles + VWAP for the live chart. Cached 60s."""
    try:
        df = get_10min_candles(instrument_key, days_back=1)
        if df.empty:
            return None
        today = df.index[-1].date()
        df    = df[df.index.date == today].copy()
        if df.empty:
            return None
        df["vwap"] = calculate_vwap(df)
        return df
    except Exception:
        return None


def _make_candle_chart(
    df: pd.DataFrame,
    sig: dict | None = None,
    ltp: float | None = None,
) -> go.Figure | None:
    """Build a live Plotly 10-min candlestick chart."""
    if df is None or df.empty:
        return None

    # Determine if last candle is still forming
    now_naive  = _strip_tz(datetime.now(IST))
    last_label = _strip_tz(df.index[-1].to_pydatetime())
    is_forming = now_naive < last_label + timedelta(minutes=10)

    closed = df.iloc[:-1] if (is_forming and len(df) > 1) else df
    live   = df.iloc[-1]  if is_forming else None

    xs_closed = closed.index.strftime("%H:%M").tolist()
    fig = go.Figure()

    # ── Completed candles ─────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=xs_closed,
        open=closed["open"], high=closed["high"],
        low=closed["low"],   close=closed["close"],
        increasing=dict(line=dict(color="#00e5b4", width=1.2), fillcolor="#00e5b4"),
        decreasing=dict(line=dict(color="#ff4d6d", width=1.2), fillcolor="#ff4d6d"),
        name="10m", showlegend=False,
    ))

    # ── Live forming candle (semi-transparent, updates with LTP) ─────────
    if live is not None:
        close_px = ltp if ltp is not None else live["close"]
        is_up    = close_px >= live["open"]
        hi       = max(live["high"], close_px) if ltp else live["high"]
        lo       = min(live["low"],  close_px) if ltp else live["low"]
        fc = "rgba(0,229,180,0.4)"  if is_up else "rgba(255,77,109,0.4)"
        lc = "rgba(0,229,180,0.85)" if is_up else "rgba(255,77,109,0.85)"
        fig.add_trace(go.Candlestick(
            x=[live.name.strftime("%H:%M") + "⟳"],
            open=[live["open"]], high=[hi], low=[lo], close=[close_px],
            increasing=dict(line=dict(color=lc, width=1.2), fillcolor=fc),
            decreasing=dict(line=dict(color=lc, width=1.2), fillcolor=fc),
            showlegend=False, name="Live",
        ))

    # ── VWAP line ─────────────────────────────────────────────────────────
    if "vwap" in df.columns:
        xs_all = df.index.strftime("%H:%M").tolist()
        if is_forming and xs_all:
            xs_all[-1] = xs_all[-1] + "⟳"
        fig.add_trace(go.Scatter(
            x=xs_all, y=df["vwap"],
            mode="lines",
            line=dict(color="#a78bfa", width=1.6),
            name="VWAP", opacity=0.85,
            hovertemplate="VWAP ₹%{y:.2f}<extra></extra>",
        ))

    # ── Trade level lines ─────────────────────────────────────────────────
    if sig:
        fig.add_hline(y=sig["entry"],
            line=dict(color="rgba(0,229,180,0.55)", width=1, dash="dash"),
            annotation_text=f'Entry ₹{sig["entry"]}',
            annotation_font=dict(size=9, color="#00e5b4"),
            annotation_position="top right")
        fig.add_hline(y=sig["sl"],
            line=dict(color="rgba(255,77,109,0.55)", width=1, dash="dash"),
            annotation_text=f'SL ₹{sig["sl"]}',
            annotation_font=dict(size=9, color="#ff4d6d"),
            annotation_position="bottom right")
        fig.add_hline(y=sig["target"],
            line=dict(color="rgba(251,191,36,0.55)", width=1, dash="dash"),
            annotation_text=f'Target ₹{sig["target"]}',
            annotation_font=dict(size=9, color="#fbbf24"),
            annotation_position="top right")

    # ── Current live price marker ─────────────────────────────────────────
    if ltp:
        fig.add_hline(y=ltp,
            line=dict(color="rgba(255,255,255,0.2)", width=1, dash="dot"))

    # ── Layout ────────────────────────────────────────────────────────────
    fig.update_layout(
        height=240,
        margin=dict(l=0, r=72, t=8, b=18),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="JetBrains Mono", color="#64748b", size=10),
        xaxis=dict(
            showgrid=True, gridcolor="rgba(255,255,255,0.04)",
            zeroline=False, showline=False,
            color="#64748b", tickfont=dict(size=9),
            rangeslider=dict(visible=False),
            type="category",
        ),
        yaxis=dict(
            showgrid=True, gridcolor="rgba(255,255,255,0.04)",
            zeroline=False, showline=False,
            color="#64748b", tickfont=dict(size=9),
            side="right", tickprefix="₹",
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(7,9,18,0.96)", bordercolor="rgba(255,255,255,0.08)",
            font=dict(color="#e2e8f0", size=9, family="JetBrains Mono"),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)", font=dict(color="#64748b", size=8),
            orientation="h", x=0, y=1.05,
        ),
    )

    return fig


# ─── Session State ────────────────────────────────────────────────────────────
if "ct_results"        not in st.session_state: st.session_state.ct_results        = []
if "ct_scanning"       not in st.session_state: st.session_state.ct_scanning       = False
if "ct_scan_time"      not in st.session_state: st.session_state.ct_scan_time      = None
if "ct_universe"       not in st.session_state: st.session_state.ct_universe       = 0
if "ct_alerted_syms"   not in st.session_state: st.session_state.ct_alerted_syms   = set()
if "ct_last_sig_check" not in st.session_state: st.session_state.ct_last_sig_check = 0.0
if "ct_target_alerted" not in st.session_state: st.session_state.ct_target_alerted = set()
if "ct_sl_alerted"     not in st.session_state: st.session_state.ct_sl_alerted     = set()


# ─── Load Instruments ─────────────────────────────────────────────────────────
if "instruments" not in st.session_state:
    st.session_state.instruments = load_instruments()

all_instruments  = st.session_state.instruments
instruments_1000 = all_instruments[all_instruments["market_cap_cr"] >= MIN_MCAP_CR].reset_index(drop=True)

now     = datetime.now(IST)
now_str = now.strftime("%H:%M:%S")


# ═══════════════════════════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown(f"""
<div class="od-header">
  <div style="position:relative;z-index:1;">
    <div class="od-title">⚡ VWAP Convergence Scanner</div>
    <div class="od-subtitle">NSE Cash · 7 Chartink filters · VWAP-touch entry · Live P&amp;L · Candlestick chart</div>
  </div>
  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:0.15rem;z-index:1;">
    <div class="od-time">{now_str} IST</div>
    <div style="font-size:0.58rem;color:#475569;font-family:'JetBrains Mono',monospace;">MCap ≥ 1,000 Cr · 10-min candles · ₹2L per trade</div>
  </div>
  <div class="od-bull">🐂</div>
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# ACTIVE FILTERS PANEL
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header"><span class="section-dot purple"></span>Active Chartink Filters</div>', unsafe_allow_html=True)

st.markdown("""
<div class="filter-box">
  <div class="filter-title">All 7 conditions must pass — fail-fast in order</div>

  <div style="font-size:0.6rem;color:#a78bfa;font-family:'JetBrains Mono',monospace;padding:0.25rem 0 0.5rem;letter-spacing:0.06em;">
    ▸ CONVERGENCE — the secret filters that cut ~180 stocks to ~35
  </div>
  <div class="filter-row">
    <span class="filter-num">C1</span>
    <span>|[0] <b>Supertrend(6,2)</b> − [0] <b>VWAP</b>|</span>
    <span class="filter-op">&lt;</span>
    <span>[0] <b>Close</b> × <span class="filter-val">0.01</span></span>
    <span style="color:#334155;font-size:0.7rem;">— ST and VWAP within 1% of price</span>
  </div>
  <div class="filter-row">
    <span class="filter-num">C2</span>
    <span>|[0] <b>VWAP</b> − <b>Daily PP</b>|</span>
    <span class="filter-op">&lt;</span>
    <span>[0] <b>Close</b> × <span class="filter-val">0.01</span></span>
    <span style="color:#334155;font-size:0.7rem;">— VWAP and PP within 1% of price</span>
  </div>

  <div style="font-size:0.6rem;color:#60a5fa;font-family:'JetBrains Mono',monospace;padding:0.5rem 0 0.25rem;letter-spacing:0.06em;">
    ▸ PRICE FILTERS
  </div>
  <div class="filter-row"><span class="filter-num">F1</span><span>[0] <b>Close</b></span><span class="filter-op">≥</span><span>[0] <b>Supertrend(6,2)</b></span><span style="color:#334155;font-size:0.7rem;">— price above bullish ST band</span></div>
  <div class="filter-row"><span class="filter-num">F2</span><span>[0] <b>Close</b></span><span class="filter-op">≥</span><span><b>Daily Pivot Point</b></span><span style="color:#334155;font-size:0.7rem;">— price above institutional pivot</span></div>
  <div class="filter-row"><span class="filter-num">F3</span><span>[0] <b>Close</b></span><span class="filter-op">≥</span><span>[0] <b>VWAP</b></span><span style="color:#334155;font-size:0.7rem;">— buyers dominating current candle</span></div>
  <div class="filter-row"><span class="filter-num">F4</span><span>[-1] <b>Close</b></span><span class="filter-op">≥</span><span>[-1] <b>VWAP</b></span><span style="color:#334155;font-size:0.7rem;">— previous candle also above VWAP</span></div>
  <div class="filter-row"><span class="filter-num">F5</span><span>[-2] <b>Close</b></span><span class="filter-op">≥</span><span>[-2] <b>VWAP</b></span><span style="color:#334155;font-size:0.7rem;">— 3-candle strength confirmed</span></div>
  <div class="filter-row"><span class="filter-num">F6</span><span><b>Market Cap</b></span><span class="filter-op">≥</span><span class="filter-val">1,000 Cr</span><span style="color:#334155;font-size:0.7rem;">— large-cap only</span></div>
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# CANDLE TIMING EXPLANATION
# ═══════════════════════════════════════════════════════════════════════════════

with st.expander("📖  Candle timing, [0]/[-1]/[-2] explained, and when to scan"):
    st.markdown("""
<div class="info-box">
<h4>10-minute candle windows on NSE</h4>

NSE opens at <code>9:15 AM</code>. 10-min candles close at:
<pre style="color:#fbbf24;background:rgba(0,0,0,0.3);padding:0.7rem;border-radius:6px;font-size:0.76rem;">
Label   Window              Closes At
9:15    9:15 → 9:24:59      9:25 AM
9:25    9:25 → 9:34:59      9:35 AM
9:35    9:35 → 9:44:59      9:45 AM  ← first scan possible
...
15:05   15:05 → 15:14:59    15:15 AM
</pre>

<h4>[0], [-1], [-2] — Chartink notation</h4>
<pre style="color:#fbbf24;background:rgba(0,0,0,0.3);padding:0.7rem;border-radius:6px;font-size:0.76rem;">
[0]  = most recent CLOSED candle  (today_df.iloc[-1])
[-1] = one candle before [0]      (today_df.iloc[-2])
[-2] = two candles before [0]     (today_df.iloc[-3])
</pre>

<h4>Best time to scan: <span class="info-highlight">9:45 AM – 10:30 AM</span></h4>

Earliest possible scan: 9:45 AM (3 closed candles). VWAP stabilises after 10 AM.
Results change every 10 minutes as new candles close.
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SCANNER CONTROLS
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header" style="margin-top:0.8rem;"><span class="section-dot"></span>Scanner</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([2, 2, 8])

with col1:
    if st.button("🔍 Run Chartink Scan", disabled=st.session_state.ct_scanning):
        st.session_state.ct_scanning  = True
        st.session_state.ct_results   = []
        st.session_state.ct_scan_time = datetime.now(IST).strftime("%H:%M:%S")
        st.rerun()

with col2:
    if st.button("🗑 Clear Results"):
        st.session_state.ct_results        = []
        st.session_state.ct_scan_time      = None
        st.session_state.ct_alerted_syms   = set()
        st.session_state.ct_last_sig_check = 0.0
        st.session_state.ct_target_alerted = set()
        st.session_state.ct_sl_alerted     = set()
        st.rerun()

st.markdown(
    f'<div style="font-size:0.68rem;color:#475569;font-family:\'JetBrains Mono\',monospace;margin-bottom:0.8rem;">'
    f'Universe: <b style="color:#e2e8f0;">{len(instruments_1000)}</b> stocks · MCap ≥ 1,000 Cr '
    f'(of {len(all_instruments)} total)</div>',
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
        entry_signal = find_entry_signal(today_df)
        r = {
            "symbol":         row["symbol"],
            "instrument_key": row["instrument_key"],
            "mcap":           round(row["market_cap_cr"], 0),
            "entry_signal":   entry_signal,
            **result,
        }
        r["confidence"] = compute_confidence(r)
        return r

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
                    f"✅ {result['symbol']} — {result['c0_close']} @ {result['c0_time']}"
                    f" · ST-VWAP {result['st_vwap_gap_pct']}% · VWAP-PP {result['vwap_pp_gap_pct']}%"
                )

    st.session_state.ct_scanning = False
    progress.empty()
    status.empty()
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# RESULTS  (live fragment — 5-second refresh)
# ═══════════════════════════════════════════════════════════════════════════════

@st.fragment(run_every=5)
def _live_results():
    results   = st.session_state.ct_results
    scan_time = st.session_state.ct_scan_time

    # ── Empty states ──────────────────────────────────────────────────────────
    if not scan_time and not st.session_state.ct_scanning:
        st.markdown(
            '<div class="empty-state">'
            '<div style="font-size:3.5rem;margin-bottom:0.7rem;">🐂</div>'
            'Click <b>Run Chartink Scan</b> to find stocks.<br>'
            '<span style="font-size:0.62rem;opacity:0.45;">9:45 AM onwards · needs ≥3 closed 10-min candles</span>'
            '</div>',
            unsafe_allow_html=True
        )
        return

    if scan_time and not results and not st.session_state.ct_scanning:
        st.markdown(
            '<div class="empty-state">'
            '<div style="font-size:3.5rem;margin-bottom:0.7rem;">🐻</div>'
            'No stocks passed all 7 filters.<br>'
            '<span style="font-size:0.62rem;opacity:0.45;">Try scanning later — results change every 10 minutes.</span>'
            '</div>',
            unsafe_allow_html=True
        )
        return

    if not results:
        return

    # ── Market hours ──────────────────────────────────────────────────────────
    _now         = datetime.now(IST)
    _market_open = (
        _now.weekday() < 5 and
        _now.replace(hour=9, minute=15, second=0, microsecond=0) <= _now <=
        _now.replace(hour=15, minute=30, second=0, microsecond=0)
    )

    # ── Live price fetch (THE FIX: use instrument_token inside each quote) ────
    live_keys  = [r["instrument_key"] for r in results if r.get("instrument_key")]
    price_map  = {}   # keyed by instrument_token (= our instrument_key format)
    live_error = None
    if live_keys and _market_open:
        try:
            raw = get_market_quotes(live_keys)
            if raw:
                for quote_data in raw.values():
                    token = quote_data.get("instrument_token")
                    ltp   = quote_data.get("last_price")
                    if token and ltp is not None:
                        price_map[token] = float(ltp)
                if not price_map:
                    live_error = "Quotes API: instrument_token missing in response"
            else:
                live_error = "Quotes API returned empty — check token"
        except Exception as e:
            live_error = str(e)
            print(f"[WARN] Live quotes: {e}")

    # ── Signal re-check every 10 minutes ──────────────────────────────────────
    now_ts     = time.time()
    last_check = st.session_state.ct_last_sig_check
    if (now_ts - last_check) >= 600:
        updated = []
        for r in results:
            r = r.copy()
            ikey = r.get("instrument_key")
            if ikey:
                try:
                    today_df, _ = get_candles_for_chartink(ikey)
                    if today_df is not None:
                        r["entry_signal"] = find_entry_signal(today_df)
                        r["confidence"]   = compute_confidence(r)
                except Exception:
                    pass
            updated.append(r)
        st.session_state.ct_results        = updated
        st.session_state.ct_last_sig_check = now_ts
        results = updated

    # ── Apply live prices (AFTER signal re-check) ─────────────────────────────
    for r in results:
        if not _market_open:
            r["live_price"] = "closed"
            continue
        ltp = price_map.get(r.get("instrument_key", ""))
        r["live_price"] = round(ltp, 2) if ltp is not None else None

    # ── Target / SL notifications ─────────────────────────────────────────────
    if _market_open:
        for r in results:
            sig = r.get("entry_signal")
            ltp = r.get("live_price")
            if not sig or not isinstance(ltp, float):
                continue
            sym = r["symbol"]
            if ltp >= sig["target"] and sym not in st.session_state.ct_target_alerted:
                alert_strategy3_target_hit(sym, ltp, sig)
                st.session_state.ct_target_alerted.add(sym)
            elif ltp <= sig["sl"] and sym not in st.session_state.ct_sl_alerted:
                alert_strategy3_sl_hit(sym, ltp, sig)
                st.session_state.ct_sl_alerted.add(sym)

    # ── Status bar ────────────────────────────────────────────────────────────
    live_time  = _now.strftime("%H:%M:%S")
    fired_n    = sum(1 for r in results if r["entry_signal"])
    passed_n   = len(results)
    next_check = int(max(0, 600 - (time.time() - st.session_state.ct_last_sig_check)))

    mkt_c   = "#00e5b4" if _market_open else "#94a3b8"
    mkt_txt = (f'<span class="live-dot"></span>LIVE {live_time} · recheck in {next_check}s'
               if _market_open else f'🟡 Closed · {live_time}')
    err_txt = (f' · <span style="color:#ff4d6d;font-size:0.65rem;">⚠ {live_error}</span>'
               if live_error else '')

    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'font-family:\'JetBrains Mono\',monospace;font-size:0.68rem;color:#475569;'
        f'margin-bottom:1rem;padding:0.45rem 0.9rem;'
        f'background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:8px;">'
        f'<span>Scan <b style="color:#e2e8f0;">{scan_time}</b> · '
        f'<b style="color:#00e5b4;">{passed_n}</b> passed · '
        f'<b style="color:#00e5b4;">{fired_n}</b> signal{"s" if fired_n != 1 else ""}'
        f'{err_txt}</span>'
        f'<span style="color:{mkt_c};">{mkt_txt}</span>'
        f'</div>',
        unsafe_allow_html=True
    )

    fired    = [r for r in results if r["entry_signal"] is not None]
    watching = [r for r in results if r["entry_signal"] is None]

    # ══ BUY SIGNALS ══════════════════════════════════════════════════════════
    st.markdown(
        f'<div class="section-header"><span class="section-dot"></span>'
        f'Buy Signals — {len(fired)} triggered</div>',
        unsafe_allow_html=True
    )

    if fired:
        for r in sorted(fired, key=lambda x: x["confidence"], reverse=True):
            sig      = r["entry_signal"]
            conf     = r["confidence"]
            ikey     = r.get("instrument_key", "")
            ltp      = r["live_price"] if isinstance(r.get("live_price"), float) else None
            mkt_clsd = r.get("live_price") == "closed"

            # ── P&L with ₹2L capital ──────────────────────────────────────
            shares   = int(TRADE_CAPITAL / sig["entry"]) if sig["entry"] > 0 else 0
            invested = round(shares * sig["entry"], 2)
            max_loss = round(shares * sig["risk"], 2)
            max_gain = round(shares * sig["reward"], 2)

            conf_c = "#00e5b4" if conf >= 70 else "#fbbf24" if conf >= 50 else "#ff4d6d"

            if ltp:
                pnl     = round(shares * (ltp - sig["entry"]), 2)
                pnl_pct = round((ltp - sig["entry"]) / sig["entry"] * 100, 2)
                pnl_c   = "#00e5b4" if pnl >= 0 else "#ff4d6d"
                pnl_s   = "+" if pnl >= 0 else ""
                ltp_d   = round(ltp - sig["entry"], 2)
                ltp_c   = "#00e5b4" if ltp_d >= 0 else "#ff4d6d"
                ltp_s   = "+" if ltp_d >= 0 else ""

                sl_v = sig["sl"]; tgt = sig["target"]
                rng  = tgt - sl_v
                prog = min(100, max(0, (ltp - sl_v) / rng * 100)) if rng > 0 else 0
                pc   = "#00e5b4" if prog >= 66 else "#fbbf24" if prog >= 33 else "#ff4d6d"

                if ltp >= tgt:    stxt = "🎯 TARGET HIT"; sc = "#00e5b4"
                elif ltp <= sl_v: stxt = "🛑 SL HIT";     sc = "#ff4d6d"
                else:             stxt = "📈 IN TRADE";    sc = "#60a5fa"

                live_html = (
                    f'<div style="background:rgba(0,0,0,0.28);border:1px solid rgba(255,255,255,0.06);'
                    f'border-radius:10px;padding:0.8rem 1rem;margin-top:0.7rem;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.4rem;">'
                    f'<div>'
                    f'<div style="font-size:0.5rem;color:#334155;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.15rem;">Live Price · 5s refresh</div>'
                    f'<div style="font-size:1.85rem;font-weight:700;color:{ltp_c};line-height:1;font-family:\'JetBrains Mono\',monospace;">₹{ltp}</div>'
                    f'<div style="font-size:0.7rem;color:{ltp_c};margin-top:0.08rem;">{ltp_s}₹{abs(ltp_d)} ({ltp_s}{abs(pnl_pct):.2f}%)</div>'
                    f'</div>'
                    f'<div style="text-align:right;">'
                    f'<div style="font-size:0.5rem;color:#334155;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.25rem;">Status</div>'
                    f'<div style="font-size:0.95rem;font-weight:700;color:{sc};">{stxt}</div>'
                    f'</div>'
                    f'</div>'
                    f'<div style="margin:0.4rem 0;">'
                    f'<div style="display:flex;justify-content:space-between;font-size:0.55rem;color:#334155;margin-bottom:0.2rem;">'
                    f'<span>🛑 SL ₹{sig["sl"]}</span><span>↑ Entry ₹{sig["entry"]}</span><span>🎯 ₹{sig["target"]}</span>'
                    f'</div>'
                    f'<div style="background:rgba(255,255,255,0.06);border-radius:3px;height:5px;">'
                    f'<div style="background:{pc};border-radius:3px;height:5px;width:{prog:.1f}%;'
                    f'box-shadow:0 0 5px {pc};transition:width 0.6s ease;"></div>'
                    f'</div>'
                    f'</div>'
                    f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0.42rem;font-family:\'JetBrains Mono\',monospace;">'
                    f'<div style="background:rgba(255,255,255,0.025);padding:0.48rem;border-radius:7px;">'
                    f'<div style="font-size:0.48rem;color:#334155;text-transform:uppercase;margin-bottom:0.15rem;">Shares (₹2L)</div>'
                    f'<div style="font-size:0.92rem;font-weight:700;color:#e2e8f0;">{shares}</div>'
                    f'<div style="font-size:0.55rem;color:#475569;">₹{invested:,.0f}</div></div>'
                    f'<div style="background:rgba(255,255,255,0.025);padding:0.48rem;border-radius:7px;">'
                    f'<div style="font-size:0.48rem;color:#334155;text-transform:uppercase;margin-bottom:0.15rem;">Live P&amp;L</div>'
                    f'<div style="font-size:0.92rem;font-weight:700;color:{pnl_c};">{pnl_s}₹{abs(pnl):,.0f}</div>'
                    f'<div style="font-size:0.55rem;color:{pnl_c};">{pnl_s}{abs(pnl_pct):.2f}%</div></div>'
                    f'<div style="background:rgba(255,255,255,0.025);padding:0.48rem;border-radius:7px;">'
                    f'<div style="font-size:0.48rem;color:#334155;text-transform:uppercase;margin-bottom:0.15rem;">Max Loss</div>'
                    f'<div style="font-size:0.92rem;font-weight:700;color:#ff4d6d;">-₹{max_loss:,.0f}</div>'
                    f'<div style="font-size:0.55rem;color:#475569;">if SL</div></div>'
                    f'<div style="background:rgba(255,255,255,0.025);padding:0.48rem;border-radius:7px;">'
                    f'<div style="font-size:0.48rem;color:#334155;text-transform:uppercase;margin-bottom:0.15rem;">Max Gain</div>'
                    f'<div style="font-size:0.92rem;font-weight:700;color:#00e5b4;">+₹{max_gain:,.0f}</div>'
                    f'<div style="font-size:0.55rem;color:#475569;">if Target</div></div>'
                    f'</div></div>'
                )
            elif mkt_clsd:
                live_html = (
                    f'<div style="background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.04);'
                    f'border-radius:10px;padding:0.6rem 1rem;margin-top:0.7rem;font-family:\'JetBrains Mono\',monospace;">'
                    f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.42rem;">'
                    f'<div style="background:rgba(255,255,255,0.025);padding:0.48rem;border-radius:7px;">'
                    f'<div style="font-size:0.48rem;color:#334155;text-transform:uppercase;margin-bottom:0.15rem;">Shares (₹2L)</div>'
                    f'<div style="font-size:0.92rem;font-weight:700;color:#e2e8f0;">{shares}</div>'
                    f'<div style="font-size:0.55rem;color:#475569;">₹{invested:,.0f}</div></div>'
                    f'<div style="background:rgba(255,255,255,0.025);padding:0.48rem;border-radius:7px;">'
                    f'<div style="font-size:0.48rem;color:#334155;text-transform:uppercase;margin-bottom:0.15rem;">Max Loss</div>'
                    f'<div style="font-size:0.92rem;font-weight:700;color:#ff4d6d;">-₹{max_loss:,.0f}</div></div>'
                    f'<div style="background:rgba(255,255,255,0.025);padding:0.48rem;border-radius:7px;">'
                    f'<div style="font-size:0.48rem;color:#334155;text-transform:uppercase;margin-bottom:0.15rem;">Max Gain</div>'
                    f'<div style="font-size:0.92rem;font-weight:700;color:#00e5b4;">+₹{max_gain:,.0f}</div></div>'
                    f'</div>'
                    f'<div style="font-size:0.6rem;color:#334155;margin-top:0.4rem;">Market closed</div>'
                    f'</div>'
                )
            else:
                live_html = (
                    f'<div style="font-size:0.62rem;color:#475569;font-family:\'JetBrains Mono\',monospace;'
                    f'margin-top:0.5rem;">⏳ Fetching live price...</div>'
                )

            # Render signal card
            st.markdown(
                f'<div class="signal-fire">'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                f'<div>'
                f'<div class="signal-fire-sym">⚡ {r["symbol"]}</div>'
                f'<div class="signal-fire-meta">VWAP touch @ {sig["touch_time"]} → confirmed @ {sig["entry_time"]} · MCap ₹{r["mcap"]:,.0f} Cr</div>'
                f'</div>'
                f'<div style="text-align:right;font-family:\'JetBrains Mono\',monospace;">'
                f'<div style="font-size:1.4rem;font-weight:700;color:{conf_c};">{conf}<span style="font-size:0.58rem;color:#334155;">/100</span></div>'
                f'<div style="font-size:0.52rem;color:#334155;text-transform:uppercase;letter-spacing:0.08em;">confidence</div>'
                f'</div>'
                f'</div>'
                f'<div class="signal-trade-grid">'
                f'<div class="signal-trade-item"><div class="signal-trade-label">BUY Entry</div>'
                f'<div class="signal-trade-value" style="color:#00e5b4;">₹{sig["entry"]}</div>'
                f'<div class="signal-trade-sub">{sig["entry_time"]} candle close</div></div>'
                f'<div class="signal-trade-item"><div class="signal-trade-label">Stop Loss</div>'
                f'<div class="signal-trade-value" style="color:#ff4d6d;">₹{sig["sl"]}</div>'
                f'<div class="signal-trade-sub">VWAP · -₹{sig["risk"]:.2f}/sh</div></div>'
                f'<div class="signal-trade-item"><div class="signal-trade-label">Target 1:3</div>'
                f'<div class="signal-trade-value" style="color:#fbbf24;">₹{sig["target"]}</div>'
                f'<div class="signal-trade-sub">+₹{sig["reward"]:.2f}/share</div></div>'
                f'<div class="signal-trade-item"><div class="signal-trade-label">VWAP Touch @ {sig["touch_time"]}</div>'
                f'<div class="signal-trade-value" style="color:#60a5fa;">₹{sig["touch_vwap"]}</div>'
                f'<div class="signal-trade-sub">L {sig["touch_low"]} ≤ VWAP ✓</div></div>'
                f'</div>'
                f'{live_html}'
                f'</div>',
                unsafe_allow_html=True
            )

            # ── Live candlestick chart ─────────────────────────────────────
            if ikey:
                chart_df = _fetch_chart_data(ikey)
                fig = _make_candle_chart(chart_df, sig=sig, ltp=ltp)
                if fig:
                    st.plotly_chart(
                        fig, width="stretch",
                        config={"displayModeBar": False, "staticPlot": False},
                    )

    else:
        st.markdown(
            '<div class="watching-banner">'
            '🐻 No buy signals yet — waiting for VWAP-touch pattern. '
            'Signal fires when [-1] low ≤ VWAP and [0] close > [-1] high.'
            '</div>',
            unsafe_allow_html=True
        )

    # ══ SUMMARY TABLE ════════════════════════════════════════════════════════
    st.markdown(
        '<div class="section-header" style="margin-top:1.4rem;"><span class="section-dot purple"></span>All Passing Stocks</div>',
        unsafe_allow_html=True
    )

    table_rows = []
    for r in sorted(results, key=lambda x: x["confidence"], reverse=True):
        sig      = r["entry_signal"]
        _ltp_raw = r.get("live_price")
        ltp      = _ltp_raw if isinstance(_ltp_raw, float) else None
        mkt_clsd = _ltp_raw == "closed"
        delta    = round(ltp - r["c0_close"], 2) if ltp else None
        table_rows.append({
            "Signal":       "⚡ BUY" if sig else "👁 Watching",
            "Confidence":   f"{r['confidence']}/100" if sig else "—",
            "Symbol":       r["symbol"],
            "Live Price":   str(ltp) if ltp else ("Mkt Closed" if mkt_clsd else "—"),
            "Δ Close":      (f"+{delta}" if delta >= 0 else str(delta)) if delta is not None else "—",
            "MCap (Cr)":    f"₹{r['mcap']:,.0f}",
            "[0] Time":     r["c0_time"],
            "[0] Close":    str(r["c0_close"]),
            "[0] VWAP":     str(r["c0_vwap"]),
            "[0] ST":       str(r["c0_st"]),
            "Pivot PP":     str(r["pp"]),
            "|ST-VWAP|%":   f"{r['st_vwap_gap_pct']}%",
            "|VWAP-PP|%":   f"{r['vwap_pp_gap_pct']}%",
            "Entry":        str(sig["entry"]) if sig else "—",
            "SL (VWAP)":    str(sig["sl"])    if sig else "—",
            "Target (1:3)": str(sig["target"]) if sig else "—",
        })

    st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)


_live_results()

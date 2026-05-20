"""
app.py — Open Drive Pivot Tracker Dashboard

Run with:  streamlit run app.py

Layout:
    Section 1 — Command Bar     (status, daily stats, controls)
    Section 2 — Signal Cards    (scanner output, 9:20–9:45 AM only)
    Section 3 — Live Tracker    (open positions, auto-refreshes)
"""

import time
import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

from instruments import load_instruments
from scanner import run_scanner, is_scan_window_open, get_scan_window_status
from tracker import (
    init_tracker_state,
    add_trade,
    update_tracker,
    get_daily_summary,
    get_tracker_rows,
    build_symbol_cache,
)
from notifier import (
    alert_new_signal,
    alert_scanner_open,
    alert_scanner_closed,
)
from config import (
    DAILY_LOSS_LIMIT,
    TOTAL_CAPITAL,
)

IST = ZoneInfo("Asia/Kolkata")

# ── Page Config ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Open Drive Tracker",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────
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
    --yellow-dim:   #4a3800;
    --blue:         #58a6ff;
    --blue-dim:     #1a3a5c;
    --purple:       #bc8cff;
    --accent:       #f0883e;
}

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', monospace;
    background: var(--bg) !important;
    color: var(--text);
}

/* Hide Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1.5rem 2rem !important; max-width: 100% !important; }

/* ── Header ── */
.od-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1rem 1.5rem;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 6px;
    margin-bottom: 1.5rem;
}
.od-header-left { display: flex; align-items: center; gap: 1rem; }
.od-logo { font-size: 1.6rem; }
.od-title { font-size: 1.1rem; font-weight: 700; color: var(--text); letter-spacing: 0.05em; text-transform: uppercase; font-family: 'IBM Plex Mono', monospace; }
.od-subtitle { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.1rem; font-family: 'IBM Plex Mono', monospace; }
.od-time { font-family: 'IBM Plex Mono', monospace; font-size: 0.9rem; color: var(--accent); }

/* ── Stat Cards ── */
.stat-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 0.75rem; margin-bottom: 1.5rem; }
.stat-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.9rem 1rem;
}
.stat-label { font-size: 0.65rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.08em; font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.3rem; }
.stat-value { font-size: 1.3rem; font-weight: 700; font-family: 'IBM Plex Mono', monospace; color: var(--text); }
.stat-value.green  { color: var(--green); }
.stat-value.red    { color: var(--red); }
.stat-value.yellow { color: var(--yellow); }
.stat-value.blue   { color: var(--blue); }
.stat-value.accent { color: var(--accent); }
.stat-sub { font-size: 0.7rem; color: var(--text-dim); margin-top: 0.2rem; font-family: 'IBM Plex Mono', monospace; }

/* ── Loss Meter ── */
.loss-meter-wrap { margin-bottom: 1.5rem; }
.loss-meter-label { font-size: 0.7rem; color: var(--text-muted); font-family: 'IBM Plex Mono', monospace; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.4rem; }
.loss-meter-bar { height: 4px; background: var(--bg-elevated); border-radius: 2px; overflow: hidden; }
.loss-meter-fill { height: 100%; border-radius: 2px; transition: width 0.5s ease; }

/* ── Section Headers ── */
.section-header {
    display: flex; align-items: center; gap: 0.6rem;
    font-size: 0.75rem; font-weight: 600;
    color: var(--text-muted); text-transform: uppercase;
    letter-spacing: 0.1em; font-family: 'IBM Plex Mono', monospace;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.5rem; margin-bottom: 1rem;
}
.section-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
.section-dot.green  { background: var(--green); }
.section-dot.red    { background: var(--red); }

/* ── Signal Card ── */
.signal-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-top: 2px solid var(--green);
    border-radius: 6px;
    padding: 1.2rem;
    margin-bottom: 1rem;
    font-family: 'IBM Plex Mono', monospace;
}
.signal-symbol { font-size: 1.2rem; font-weight: 700; color: var(--text); }
.signal-meta   { font-size: 0.7rem; color: var(--text-muted); margin-top: 0.1rem; }
.signal-grid   { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.75rem; margin: 1rem 0; }
.signal-item   { background: var(--bg-elevated); padding: 0.6rem 0.8rem; border-radius: 4px; }
.signal-item-label { font-size: 0.6rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.08em; }
.signal-item-value { font-size: 0.95rem; font-weight: 600; color: var(--text); margin-top: 0.15rem; }
.signal-item-value.green  { color: var(--green); }
.signal-item-value.red    { color: var(--red); }
.signal-item-value.yellow { color: var(--yellow); }
.signal-item-value.blue   { color: var(--blue); }
.signal-rr { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 3px; font-size: 0.7rem; font-weight: 600; }
.signal-rr.good { background: var(--green-dim); color: var(--green); }
.signal-rr.ok   { background: var(--yellow-dim); color: var(--yellow); }
.rule-checks { display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.75rem 0; }
.rule-badge { font-size: 0.62rem; padding: 0.15rem 0.5rem; border-radius: 3px; background: var(--green-dim); color: var(--green); }

/* ── Tracker Table ── */
.tracker-row {
    display: grid;
    grid-template-columns: 100px 110px 90px 90px 70px 90px 90px 90px 60px 90px;
    gap: 0; border-bottom: 1px solid var(--border);
    font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem;
    padding: 0.6rem 0; align-items: center;
}
.tracker-header { color: var(--text-muted); font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.06em; border-bottom: 2px solid var(--border-bright) !important; }
.tracker-cell { padding: 0 0.5rem; }
.status-active   { color: var(--blue); }
.status-t1       { color: var(--yellow); }
.status-t2       { color: var(--green); font-weight: 700; }
.status-stopped  { color: var(--red); }
.status-time     { color: var(--text-muted); }

/* ── Status Badge ── */
.scanner-status {
    display: inline-flex; align-items: center; gap: 0.4rem;
    font-size: 0.7rem; font-family: 'IBM Plex Mono', monospace;
    padding: 0.2rem 0.7rem; border-radius: 3px;
}
.scanner-status.open   { background: var(--green-dim); color: var(--green); }
.scanner-status.closed { background: var(--bg-elevated); color: var(--text-muted); }
.scanner-status.halted { background: var(--red-dim); color: var(--red); }
.blink { animation: blink 1s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }

/* ── Empty State ── */
.empty-state {
    text-align: center; padding: 2.5rem;
    color: var(--text-dim); font-family: 'IBM Plex Mono', monospace;
    font-size: 0.8rem;
    border: 1px dashed var(--border); border-radius: 6px;
}

/* ── Halted Banner ── */
.halted-banner {
    background: var(--red-dim); border: 1px solid var(--red);
    border-radius: 6px; padding: 1rem 1.5rem;
    font-family: 'IBM Plex Mono', monospace;
    margin-bottom: 1.5rem;
}
.halted-banner h3 { color: var(--red); margin: 0 0 0.3rem; font-size: 0.9rem; }
.halted-banner p  { color: var(--text-muted); margin: 0; font-size: 0.78rem; }

/* Streamlit button overrides */
.stButton > button {
    background: var(--bg-elevated) !important;
    color: var(--text) !important;
    border: 1px solid var(--border-bright) !important;
    border-radius: 4px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    padding: 0.4rem 1rem !important;
    transition: all 0.15s ease !important;
}
.stButton > button:hover {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
}

/* Streamlit dataframe overrides */
.stDataFrame { background: var(--bg-card) !important; }
</style>
""", unsafe_allow_html=True)

# ── Init ──────────────────────────────────────────────────────────────────
init_tracker_state()

if "instruments" not in st.session_state:
    st.session_state.instruments = load_instruments()
    build_symbol_cache(st.session_state.instruments)

if "scan_alerted_open" not in st.session_state:
    st.session_state.scan_alerted_open   = False
if "scan_alerted_closed" not in st.session_state:
    st.session_state.scan_alerted_closed = False
if "signals_this_scan" not in st.session_state:
    st.session_state.signals_this_scan   = []

instruments = st.session_state.instruments
now         = datetime.now(IST)
now_str     = now.strftime("%H:%M:%S")
scan_status = get_scan_window_status()
summary     = get_daily_summary()

# ── Scanner open/close Telegram alerts removed (no time gate) ────────────

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — HEADER & STATS
# ═══════════════════════════════════════════════════════════════════════════

# Header
scan_badge_class = "open"
scan_badge_text  = (
    f'<span class="blink">●</span> LIVE — SCAN ANYTIME'
    if not summary["system_halted"]
    else "⛔ HALTED — DAILY LIMIT HIT"
)

st.markdown(f"""
<div class="od-header">
  <div class="od-header-left">
    <span class="od-logo">🦅</span>
    <div>
      <div class="od-title">Open Drive Pivot Tracker</div>
      <div class="od-subtitle">NSE EQ · Institutional Flow · Manual Execution</div>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:1.5rem;">
    <span class="scanner-status {scan_badge_class}">{scan_badge_text}</span>
    <span class="od-time">{now_str} IST</span>
  </div>
</div>
""", unsafe_allow_html=True)

# Halted banner
if summary["system_halted"]:
    st.markdown("""
    <div class="halted-banner">
      <h3>🚨 SYSTEM HALTED — Daily Loss Limit Reached</h3>
      <p>No new trades today. Close any remaining positions manually. Resume tomorrow.</p>
    </div>
    """, unsafe_allow_html=True)

# Stats
net_pnl      = summary["net_pnl"]
net_class    = "green" if net_pnl >= 0 else "red"
net_sign     = "+" if net_pnl >= 0 else ""
loss_pct     = summary["loss_used_pct"]
loss_color   = "#3fb950" if loss_pct < 50 else ("#d29922" if loss_pct < 80 else "#f85149")

st.markdown(f"""
<div class="stat-row">
  <div class="stat-card">
    <div class="stat-label">Net P&L Today</div>
    <div class="stat-value {net_class}">{net_sign}₹{abs(net_pnl):,.0f}</div>
    <div class="stat-sub">realised only</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Loss Used</div>
    <div class="stat-value {'red' if loss_pct >= 80 else 'yellow' if loss_pct >= 50 else 'green'}">{loss_pct:.0f}%</div>
    <div class="stat-sub">₹{summary['daily_loss']:,.0f} of ₹{DAILY_LOSS_LIMIT:,.0f}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Trades Taken</div>
    <div class="stat-value accent">{summary['trades_taken']}</div>
    <div class="stat-sub">today (unlimited)</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Signals Found</div>
    <div class="stat-value blue">{summary['signals_found']}</div>
    <div class="stat-sub">this scan session</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Universe</div>
    <div class="stat-value">{len(instruments)}</div>
    <div class="stat-sub">stocks loaded</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Capital</div>
    <div class="stat-value">₹{TOTAL_CAPITAL/100000:.1f}L</div>
    <div class="stat-sub">max risk ₹2,000/trade</div>
  </div>
</div>
<div class="loss-meter-wrap">
  <div class="loss-meter-label">Daily Loss Meter — ₹{summary['daily_loss']:,.0f} / ₹{DAILY_LOSS_LIMIT:,.0f}</div>
  <div class="loss-meter-bar">
    <div class="loss-meter-fill" style="width:{min(loss_pct,100):.1f}%;background:{loss_color};"></div>
  </div>
</div>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — SCANNER
# ═══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header"><span class="section-dot green"></span>Signal Scanner</div>', unsafe_allow_html=True)

# Scanner controls
col1, col2, col3 = st.columns([2, 2, 8])

with col1:
    scan_disabled = (
        st.session_state.is_scanning
        or summary["system_halted"]
    )
    if st.button("⚡ Run Scanner", disabled=scan_disabled):
        st.session_state.is_scanning = True
        st.rerun()

with col2:
    track_label = "📡 Stop Tracking" if st.session_state.is_tracking else "📡 Start Tracking"
    if st.button(track_label):
        st.session_state.is_tracking = not st.session_state.is_tracking
        st.rerun()


# ── Active Scanner ────────────────────────────────────────────────────────
if st.session_state.is_scanning:
    progress_bar  = st.progress(0, text="Initialising scanner...")
    status_text   = st.empty()

    for current, total, phase, result in run_scanner(instruments):

        if result == "DONE":
            break

        pct = int(current / total * 100) if total > 0 else 0

        if phase == "prefilter":
            progress_bar.progress(pct, text=f"Pre-filtering universe... ({current}/{total})")
            continue

        # Phase = scan
        if result is None:
            progress_bar.progress(pct, text=f"Evaluating signals... ({current}/{total})")
            continue

        # ── Valid Signal Found ────────────────────────────────────────────
        sym = result["symbol"]

        # Don't add duplicate signals
        existing_syms = [s["symbol"] for s in st.session_state.signals_this_scan]
        if sym not in existing_syms:
            st.session_state.signals_this_scan.append(result)
            st.session_state.signals_found += 1
            # Auto-add to tracker immediately
            add_trade(result)
            alert_new_signal(result)
            status_text.success(f"✅ Signal: {sym} at ₹{result['entry']} — R:R {result['rr_ratio']:.1f}")

        progress_bar.progress(pct, text=f"Scanning... ({current}/{total})")

    st.session_state.is_scanning = False
    # Auto-start tracking after scan completes
    if st.session_state.signals_this_scan:
        st.session_state.is_tracking = True
    progress_bar.empty()
    status_text.empty()
    st.rerun()

# ── Display Signal Cards ──────────────────────────────────────────────────
if st.session_state.signals_this_scan:
    for signal in st.session_state.signals_this_scan:
        sym       = signal["symbol"]
        entry     = signal["entry"]
        stop      = signal["stop_loss"]
        r1        = signal["R1"]
        r2        = signal["R2"]
        shares    = signal["shares"]
        t1_sh     = signal["t1_shares"]
        t2_sh     = signal["t2_shares"]
        tv        = signal["trade_value"]
        rr        = signal["rr_ratio"]
        ml        = signal["max_loss"]
        mg        = signal["max_gain"]
        rsi       = signal["rsi"]
        wma       = signal["wma_rsi"]
        mcap      = signal["market_cap_cr"]
        sig_time  = signal["signal_time"]
        r1d       = signal["r1_distance_pct"]
        
        f_open    = signal.get("first_open", 0)
        f_high    = signal.get("first_high", 0)
        f_low     = signal.get("first_low", 0)
        f_close   = signal.get("first_close", 0)
        f_vol     = signal.get("first_volume", 0)
        f_time    = signal.get("first_time", "N/A")

        l_open    = signal.get("live_open", 0)
        l_high    = signal.get("live_high", 0)
        l_low     = signal.get("live_low", 0)
        l_close   = signal.get("live_close", 0)
        l_vol     = signal.get("live_volume", 0)
        l_time    = signal.get("live_time", "N/A")

        rr_class  = "good" if rr >= 2.0 else "ok"

        already_tracking = sym in st.session_state.active_trades

        st.markdown(f"""
        <div class="signal-card">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;">
            <div>
              <div class="signal-symbol">{sym}</div>
              <div class="signal-meta">{sig_time} IST · ₹{mcap:,.0f} Cr · NSE EQ</div>
            </div>
            <div style="text-align:right;">
              <span class="signal-rr {rr_class}">R:R 1:{rr:.1f}</span>
              <div style="font-size:0.65rem;color:#7d8590;margin-top:0.3rem;">Max Loss ₹{ml:,.0f} · Max Gain ₹{mg:,.0f}</div>
            </div>
          </div>
          <div class="signal-grid">
            <div class="signal-item">
              <div class="signal-item-label">BUY @ Entry</div>
              <div class="signal-item-value">₹{entry:.2f}</div>
              <div style="font-size:0.65rem;color:#7d8590;">{shares} shares · ₹{tv:,.0f}</div>
            </div>
            <div class="signal-item">
              <div class="signal-item-label">Stop Loss (Fixed)</div>
              <div class="signal-item-value red">₹{stop:.2f}</div>
              <div style="font-size:0.65rem;color:#7d8590;">Fixed 1% below entry</div>
            </div>
            <div class="signal-item">
              <div class="signal-item-label">Target 1 (R1)</div>
              <div class="signal-item-value green">₹{r1:.2f}</div>
              <div style="font-size:0.65rem;color:#7d8590;">Sell {t1_sh} shares (+{r1d:.1f}%)</div>
            </div>
            <div class="signal-item">
              <div class="signal-item-label">Target 2 (R2)</div>
              <div class="signal-item-value yellow">₹{r2:.2f}</div>
              <div style="font-size:0.65rem;color:#7d8590;">Sell {t2_sh} shares</div>
            </div>
            <div class="signal-item">
              <div class="signal-item-label">RSI · WMA</div>
              <div class="signal-item-value blue">{rsi:.1f} · {wma:.1f}</div>
              <div style="font-size:0.65rem;color:#7d8590;">momentum ✅</div>
            </div>
          </div>
          <div class="signal-grid" style="grid-template-columns: 1fr 1fr; margin-top: 0px;">
            <div class="signal-item">
              <div class="signal-item-label">First Candle ({f_time})</div>
              <div class="signal-item-value green" style="font-size:0.85rem;">O: {f_open} | H: {f_high} | L: {f_low} | C: {f_close}</div>
              <div style="font-size:0.65rem;color:#7d8590;">Volume: {f_vol:,} · Open Drive confirmed</div>
            </div>
            <div class="signal-item">
              <div class="signal-item-label">Live Candle ({l_time})</div>
              <div class="signal-item-value blue" style="font-size:0.85rem;">O: {l_open} | H: {l_high} | L: {l_low} | C: {l_close}</div>
              <div style="font-size:0.65rem;color:#7d8590;">Volume: {l_vol:,} · Signal Triggered</div>
            </div>
          </div>
          <div class="rule-checks">
            <span class="rule-badge">✓ Open Drive</span>
            <span class="rule-badge">✓ Price > VWAP</span>
            <span class="rule-badge">✓ Price > PP</span>
            <span class="rule-badge">✓ RSI > WMA</span>
            <span class="rule-badge">✓ R:R ≥ 1.5</span>
            <span class="rule-badge">✓ R1 ≥ 0.5%</span>
            <span class="rule-badge">✓ MCap ≥ 500Cr</span>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Show tracking status
        if sym in st.session_state.active_trades:
            track_status = st.session_state.active_trades[sym]["status"]
            if track_status == "ACTIVE":
                st.markdown(f'<div style="font-size:0.72rem;color:#58a6ff;font-family:\'IBM Plex Mono\',monospace;padding:0.3rem 0;">● {sym} — TRACKING LIVE</div>', unsafe_allow_html=True)
            elif track_status == "T1_HIT":
                st.markdown(f'<div style="font-size:0.72rem;color:#d29922;font-family:\'IBM Plex Mono\',monospace;padding:0.3rem 0;">◑ {sym} — T1 HIT, holding for R2</div>', unsafe_allow_html=True)
            elif track_status == "T2_HIT":
                st.markdown(f'<div style="font-size:0.72rem;color:#3fb950;font-family:\'IBM Plex Mono\',monospace;padding:0.3rem 0;">✓ {sym} — T2 HIT, COMPLETE</div>', unsafe_allow_html=True)
            elif track_status == "STOPPED":
                st.markdown(f'<div style="font-size:0.72rem;color:#f85149;font-family:\'IBM Plex Mono\',monospace;padding:0.3rem 0;">✕ {sym} — STOPPED OUT</div>', unsafe_allow_html=True)
            elif track_status == "TIME_EXIT":
                st.markdown(f'<div style="font-size:0.72rem;color:#7d8590;font-family:\'IBM Plex Mono\',monospace;padding:0.3rem 0;">⏰ {sym} — TIME EXIT</div>', unsafe_allow_html=True)

elif not st.session_state.is_scanning:
    st.markdown('<div class="empty-state">Ready to scan.<br>Click ⚡ Run Scanner to find Open Drive setups.</div>', unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — LIVE TRACKER
# ═══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header" style="margin-top:2rem;"><span class="section-dot"></span>Live Position Tracker</div>', unsafe_allow_html=True)

tracker_container = st.empty()

def render_tracker_table():
    rows = get_tracker_rows()

    if not rows:
        tracker_container.markdown(
            '<div class="empty-state">No active positions.<br>Add a trade from the signals above to start tracking.</div>',
            unsafe_allow_html=True
        )
        return

    # Status color map
    status_map = {
        "ACTIVE":    ("status-active",  "● ACTIVE"),
        "T1_HIT":    ("status-t1",      "◑ T1 HIT -- Hold for R2"),
        "T2_HIT":    ("status-t2",      "✓ T2 HIT -- Complete"),
        "STOPPED":   ("status-stopped", "✕ STOPPED OUT"),
        "TIME_EXIT": ("status-time",    "[TIME] EXIT"),
    }

    header = """<div class="tracker-row tracker-header">
<div class="tracker-cell">Symbol</div>
<div class="tracker-cell">Status</div>
<div class="tracker-cell">Entry</div>
<div class="tracker-cell">Live</div>
<div class="tracker-cell">Chg%</div>
<div class="tracker-cell">Stop</div>
<div class="tracker-cell">T1 (R1)</div>
<div class="tracker-cell">T2 (R2)</div>
<div class="tracker-cell">Shares</div>
<div class="tracker-cell">Unreal P&L</div>
</div>"""

    data_rows = ""
    for r in rows:
        css, label = status_map.get(r["Status"], ("", r["Status"]))
        chg        = r["Change"]
        chg_style  = "color:#3fb950" if "+" in chg else "color:#f85149"
        pnl        = r["Unrealised"]
        pnl_style  = "color:#3fb950" if "+" in pnl else "color:#f85149"

        data_rows += f"""<div class="tracker-row">
<div class="tracker-cell" style="font-weight:700;color:#e6edf3;">{r['Symbol']}</div>
<div class="tracker-cell {css}">{label}</div>
<div class="tracker-cell">{r['Entry']}</div>
<div class="tracker-cell" style="font-weight:600;color:#e6edf3;">{r['Live Price']}</div>
<div class="tracker-cell" style="{chg_style}">{chg}</div>
<div class="tracker-cell" style="color:#f85149;">{r['Stop (Fixed)']}</div>
<div class="tracker-cell" style="color:#3fb950;">{r['T1 (R1)']}</div>
<div class="tracker-cell" style="color:#d29922;">{r['T2 (R2)']}</div>
<div class="tracker-cell">{r['Shares']}</div>
<div class="tracker-cell" style="{pnl_style};font-weight:600;">{pnl}</div>
</div>"""

    tracker_container.markdown(
        f'<div style="background:var(--bg-card,#0d1117);border:1px solid var(--border,#21262d);border-radius:6px;padding:0.5rem 0.5rem 0.25rem;overflow-x:auto;">'
        f'{header}{data_rows}</div>',
        unsafe_allow_html=True
    )

render_tracker_table()

# ═══════════════════════════════════════════════════════════════════════════
# LIVE TRACKING ENGINE
# Placed at bottom so UI renders before the refresh cycle kicks in
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state.is_tracking:
    # Always refresh if tracking is enabled — checks all positions for live prices
    active_open = [
        t for t in st.session_state.active_trades.values()
        if t["status"] in ["ACTIVE", "T1_HIT"]
    ]

    if active_open:
        update_tracker(instruments)
        render_tracker_table()   # re-render after price update
        time.sleep(3)
        st.rerun()
    else:
        # All positions completed/stopped — show final state, stop auto-refresh
        render_tracker_table()

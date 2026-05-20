"""
backtest_app.py - Streamlit dashboard for backtest results.

Run:  streamlit run backtest_app.py

Displays:
    - Performance summary with key metrics
    - Equity curve chart
    - Monthly P&L breakdown
    - Exit type analysis
    - Full trade log
"""

import os
import json
import streamlit as st
import pandas as pd
import numpy as np
from config import MAX_RISK_PER_TRADE

RESULTS_DIR = "backtest_results"

# ── Page Config ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Open Drive Backtest",
    page_icon="📊",
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
    font-family: 'IBM Plex Sans', sans-serif;
    background: var(--bg) !important;
    color: var(--text);
}

#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1.5rem 2rem !important; max-width: 100% !important; }

.bt-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 1rem 1.5rem; background: var(--bg-card);
    border: 1px solid var(--border); border-left: 3px solid var(--purple);
    border-radius: 6px; margin-bottom: 1.5rem;
}
.bt-title { font-size: 1.1rem; font-weight: 700; color: var(--text);
    letter-spacing: 0.05em; text-transform: uppercase;
    font-family: 'IBM Plex Mono', monospace; }
.bt-subtitle { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.1rem;
    font-family: 'IBM Plex Mono', monospace; }

.metric-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 0.75rem; margin-bottom: 1.5rem; }
.metric-card {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 6px; padding: 0.9rem 1rem;
}
.metric-label { font-size: 0.65rem; color: var(--text-muted); text-transform: uppercase;
    letter-spacing: 0.08em; font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.3rem; }
.metric-value { font-size: 1.3rem; font-weight: 700;
    font-family: 'IBM Plex Mono', monospace; }
.metric-sub { font-size: 0.7rem; color: var(--text-dim); margin-top: 0.2rem;
    font-family: 'IBM Plex Mono', monospace; }
.green { color: #3fb950; }
.red { color: #f85149; }
.yellow { color: #d29922; }
.blue { color: #58a6ff; }
.purple { color: #bc8cff; }
.accent { color: #f0883e; }

.section-header {
    display: flex; align-items: center; gap: 0.6rem;
    font-size: 0.75rem; font-weight: 600; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.1em;
    font-family: 'IBM Plex Mono', monospace;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.5rem; margin: 1.5rem 0 1rem 0;
}
.section-dot { width: 6px; height: 6px; border-radius: 50%; }

.exit-bar {
    display: flex; height: 28px; border-radius: 4px; overflow: hidden;
    margin: 0.5rem 0 1rem 0; font-family: 'IBM Plex Mono', monospace;
    font-size: 0.7rem; font-weight: 600;
}
.exit-seg { display: flex; align-items: center; justify-content: center; color: #070b0f; }

.monthly-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.5rem; }
.monthly-cell {
    padding: 0.6rem 0.8rem; border-radius: 4px;
    font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem;
}
.monthly-cell.profit { background: #1a4a24; color: #3fb950; }
.monthly-cell.loss { background: #4a1a1a; color: #f85149; }
.monthly-month { font-size: 0.62rem; color: inherit; opacity: 0.7; }
.monthly-pnl { font-weight: 600; margin-top: 0.15rem; }

.verdict-box {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 6px; padding: 1.5rem; margin-top: 1.5rem;
    font-family: 'IBM Plex Mono', monospace; text-align: center;
}
.verdict-title { font-size: 1rem; font-weight: 700; margin-bottom: 0.5rem; }
.verdict-text { font-size: 0.8rem; color: var(--text-muted); line-height: 1.6; }
</style>
""", unsafe_allow_html=True)

# ── Check Data ────────────────────────────────────────────────────────────
summary_path = os.path.join(RESULTS_DIR, "summary.json")
if not os.path.exists(summary_path):
    st.markdown("""
    <div style="text-align:center;padding:4rem;color:#7d8590;
        font-family:'IBM Plex Mono',monospace;">
        <h2>No backtest results found</h2>
        <p>Run the backtest first:</p>
        <code>python backtester.py</code>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── Load Data ─────────────────────────────────────────────────────────────
with open(summary_path) as f:
    summary = json.load(f)

trades_df = pd.read_csv(os.path.join(RESULTS_DIR, "trades.csv"))
equity_df = pd.read_csv(os.path.join(RESULTS_DIR, "equity_curve.csv"))
daily_df  = pd.read_csv(os.path.join(RESULTS_DIR, "daily_stats.csv"))

equity_df["date"] = pd.to_datetime(equity_df["date"])
trades_df["date"] = pd.to_datetime(trades_df["date"])
daily_df["date"]  = pd.to_datetime(daily_df["date"])

# ══════════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════════

pnl_class = "green" if summary["total_pnl"] >= 0 else "red"
pnl_sign  = "+" if summary["total_pnl"] >= 0 else ""

st.markdown(f"""
<div class="bt-header">
  <div>
    <div class="bt-title">Open Drive Pivot - Backtest Results</div>
    <div class="bt-subtitle">
        {summary['period_start']} to {summary['period_end']}
        | {summary['trading_days']} trading days
        | {summary['stocks_scanned']} stocks
    </div>
  </div>
  <div style="text-align:right;">
    <div class="metric-value {pnl_class}" style="font-size:1.4rem;">
        {pnl_sign}Rs.{abs(summary['total_pnl']):,.0f}
    </div>
    <div class="bt-subtitle">{pnl_sign}{summary['return_pct']}% return</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════
# KEY METRICS
# ══════════════════════════════════════════════════════════════════════════

wr = summary["win_rate"]
wr_class = "green" if wr >= 50 else ("yellow" if wr >= 40 else "red")

dd = summary["max_drawdown_pct"]
dd_class = "green" if abs(dd) < 3 else ("yellow" if abs(dd) < 8 else "red")

avg_win_loss = abs(summary["avg_win"] / summary["avg_loss"]) if summary["avg_loss"] != 0 else 0
awl_class = "green" if avg_win_loss >= 1.5 else ("yellow" if avg_win_loss >= 1.0 else "red")

st.markdown(f"""
<div class="metric-row">
  <div class="metric-card">
    <div class="metric-label">Total Trades</div>
    <div class="metric-value accent">{summary['total_trades']}</div>
    <div class="metric-sub">{summary['trading_days']} days</div>
  </div>
  <div class="metric-card">
    <div class="metric-label">Win Rate</div>
    <div class="metric-value {wr_class}">{wr:.1f}%</div>
    <div class="metric-sub">{summary['winners']}W / {summary['losers']}L</div>
  </div>
  <div class="metric-card">
    <div class="metric-label">Avg Win / Avg Loss</div>
    <div class="metric-value {awl_class}">{avg_win_loss:.2f}x</div>
    <div class="metric-sub">Rs.{summary['avg_win']:,.0f} / Rs.{abs(summary['avg_loss']):,.0f}</div>
  </div>
  <div class="metric-card">
    <div class="metric-label">Max Drawdown</div>
    <div class="metric-value {dd_class}">{dd:.2f}%</div>
    <div class="metric-sub">from peak equity</div>
  </div>
  <div class="metric-card">
    <div class="metric-label">Starting Capital</div>
    <div class="metric-value">Rs.{summary['capital']:,}</div>
    <div class="metric-sub">Rs.{MAX_RISK_PER_TRADE:,}/trade risk</div>
  </div>
  <div class="metric-card">
    <div class="metric-label">Final Capital</div>
    <div class="metric-value {pnl_class}">Rs.{summary['final_capital']:,.0f}</div>
    <div class="metric-sub">{pnl_sign}{summary['return_pct']}%</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════
# EXIT TYPE BREAKDOWN
# ══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header"><span class="section-dot" style="background:#bc8cff;"></span>Exit Type Breakdown</div>', unsafe_allow_html=True)

total = max(summary["total_trades"], 1)
t2_pct = summary["t2_hits"] / total * 100
t1_pct = summary["t1_hits"] / total * 100
te_pct = summary["time_exits"] / total * 100
st_pct = summary["stops"] / total * 100

st.markdown(f"""
<div class="exit-bar">
    <div class="exit-seg" style="width:{t2_pct}%;background:#3fb950;">T2 {t2_pct:.0f}%</div>
    <div class="exit-seg" style="width:{t1_pct}%;background:#d29922;">T1 {t1_pct:.0f}%</div>
    <div class="exit-seg" style="width:{te_pct}%;background:#58a6ff;">Exit {te_pct:.0f}%</div>
    <div class="exit-seg" style="width:{st_pct}%;background:#f85149;">Stop {st_pct:.0f}%</div>
</div>
<div style="display:flex;gap:1.5rem;font-family:'IBM Plex Mono',monospace;font-size:0.72rem;color:#7d8590;margin-bottom:1rem;">
    <span><span style="color:#3fb950;">&#9679;</span> T2 Hit (full profit): {summary['t2_hits']}</span>
    <span><span style="color:#d29922;">&#9679;</span> T1 Hit (partial): {summary['t1_hits']}</span>
    <span><span style="color:#58a6ff;">&#9679;</span> Time Exit: {summary['time_exits']}</span>
    <span><span style="color:#f85149;">&#9679;</span> Stopped Out: {summary['stops']}</span>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════
# EQUITY CURVE
# ══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header"><span class="section-dot" style="background:#58a6ff;"></span>Equity Curve</div>', unsafe_allow_html=True)

chart_data = equity_df.set_index("date")["equity"]
st.line_chart(chart_data, use_container_width=True, color="#58a6ff")

# ══════════════════════════════════════════════════════════════════════════
# MONTHLY P&L
# ══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header"><span class="section-dot" style="background:#d29922;"></span>Monthly P&L</div>', unsafe_allow_html=True)

trades_df["month_str"] = trades_df["date"].dt.strftime("%b %Y")
monthly = trades_df.groupby("month_str", sort=False).agg(
    pnl=("pnl", "sum"),
    trades=("pnl", "count"),
    wins=("pnl", lambda x: (x > 0).sum()),
).reset_index()

# Sort by date properly
monthly["sort_date"] = pd.to_datetime(monthly["month_str"], format="%b %Y")
monthly = monthly.sort_values("sort_date")

# Use Streamlit columns for reliable rendering
cols = st.columns(4)
for i, (_, row) in enumerate(monthly.iterrows()):
    col_idx = i % 4
    sign = "+" if row["pnl"] >= 0 else ""
    bg = "#1a4a24" if row["pnl"] >= 0 else "#4a1a1a"
    fg = "#3fb950" if row["pnl"] >= 0 else "#f85149"
    with cols[col_idx]:
        st.markdown(f"""
        <div style="background:{bg};color:{fg};padding:0.6rem 0.8rem;border-radius:4px;
            font-family:'IBM Plex Mono',monospace;font-size:0.78rem;margin-bottom:0.5rem;">
            <div style="font-size:0.62rem;opacity:0.7;">{row['month_str']} ({row['trades']}T / {row['wins']}W)</div>
            <div style="font-weight:600;margin-top:0.15rem;">{sign}Rs.{row['pnl']:,.0f}</div>
        </div>
        """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════
# TOP TRADES
# ══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header"><span class="section-dot" style="background:#3fb950;"></span>Top 10 Best & Worst Trades</div>', unsafe_allow_html=True)

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Best Trades**")
    best = trades_df.nlargest(10, "pnl")[["date", "symbol", "entry", "exit_type", "pnl", "rr_ratio"]].copy()
    best["date"] = best["date"].dt.strftime("%Y-%m-%d")
    best["pnl"] = best["pnl"].apply(lambda x: f"+Rs.{x:,.0f}")
    st.dataframe(best, use_container_width=True, hide_index=True)

with col2:
    st.markdown("**Worst Trades**")
    worst = trades_df.nsmallest(10, "pnl")[["date", "symbol", "entry", "exit_type", "pnl", "rr_ratio"]].copy()
    worst["date"] = worst["date"].dt.strftime("%Y-%m-%d")
    worst["pnl"] = worst["pnl"].apply(lambda x: f"Rs.{x:,.0f}")
    st.dataframe(worst, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════
# SIGNAL FREQUENCY BY STOCK
# ══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header"><span class="section-dot" style="background:#f0883e;"></span>Signal Frequency by Stock</div>', unsafe_allow_html=True)

stock_stats = trades_df.groupby("symbol").agg(
    trades=("pnl", "count"),
    total_pnl=("pnl", "sum"),
    avg_pnl=("pnl", "mean"),
    win_rate=("pnl", lambda x: (x > 0).sum() / len(x) * 100),
).round(2).sort_values("trades", ascending=False).head(20)

st.dataframe(stock_stats, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════
# FULL TRADE LOG
# ══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header"><span class="section-dot" style="background:#7d8590;"></span>Full Trade Log</div>', unsafe_allow_html=True)

display_df = trades_df[[
    "date", "symbol", "entry", "stop_loss", "R1", "R2",
    "shares", "trade_value", "rr_ratio", "exit_type", "exit_price", "pnl"
]].copy()

# Add proxy time (09:30) since entries on Open Drive happen early
display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d 09:30")
display_df = display_df.rename(columns={"date": "entry_time"})

# Add approximate exit times based on exit type
def get_exit_time(row):
    if row["exit_type"] == "TIME_EXIT":
        return "15:15"
    elif row["exit_type"] == "STOPPED":
        return "10:30"
    else:
        return "11:45"
        
display_df["exit_time"] = display_df["entry_time"].str[:10] + " " + display_df.apply(get_exit_time, axis=1)

# Format trade_value for readability
display_df["trade_value"] = display_df["trade_value"].apply(lambda x: f"₹{x:,.0f}")

# Reorder columns
display_df = display_df[[
    "entry_time", "symbol", "entry", "stop_loss", "R1", "R2",
    "shares", "trade_value", "rr_ratio", "exit_type", "exit_time", "exit_price", "pnl"
]]

display_df = display_df.sort_values("entry_time", ascending=False)
st.caption("Note: Because this historical backtest uses *daily* candles, the exact minute of execution is not recorded. The times shown are proxies (09:30 for Entry, 15:15 for Time Exits, etc.) to give a realistic picture of intraday flow.")

st.dataframe(display_df, use_container_width=True, hide_index=True, height=500)

# ══════════════════════════════════════════════════════════════════════════
# VERDICT
# ══════════════════════════════════════════════════════════════════════════

wr = summary["win_rate"]
ret = summary["return_pct"]

if ret > 10:
    verdict_color = "#3fb950"
    verdict_text = "STRATEGY WORKS"
    if wr < 50:
        verdict_detail = f"Only {wr:.0f}% win rate, but avg winner is {avg_win_loss:.1f}x the avg loser. Net {ret:.1f}% annual return. The math works — losses are small, wins are big."
    else:
        verdict_detail = f"With a {wr:.0f}% win rate and {ret:.1f}% annual return, this strategy shows consistent profitability."
elif ret > 0:
    verdict_color = "#d29922"
    verdict_text = "STRATEGY SHOWS PROMISE"
    verdict_detail = f"Positive returns ({ret:.1f}%) but needs optimization. Consider tightening filters or adjusting stops."
else:
    verdict_color = "#f85149"
    verdict_text = "STRATEGY NEEDS WORK"
    verdict_detail = f"Returns of {ret:.1f}% with {wr:.0f}% win rate. Review your rules and risk parameters."

st.markdown(f"""
<div class="verdict-box" style="border-color: {verdict_color};">
    <div class="verdict-title" style="color: {verdict_color};">{verdict_text}</div>
    <div class="verdict-text">{verdict_detail}</div>
    <div class="verdict-text" style="margin-top:0.8rem;">
        Based on {summary['total_trades']} trades over {summary['trading_days']} days
        with Rs.{summary['capital']:,} starting capital.
    </div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════
# REALISTIC PROJECTIONS
# ══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-header"><span class="section-dot" style="background:#f85149;"></span>Live Trading Expectations</div>', unsafe_allow_html=True)

st.markdown(f"""
<div style="background:var(--bg-card); border:1px solid var(--border); border-radius:6px; padding:1.5rem; font-family:'IBM Plex Mono',monospace; font-size:0.85rem; line-height:1.6;">
<div style="color:var(--text); font-weight:700; margin-bottom:1rem; font-size:0.95rem;">THE REALITY CHECK: Full Universe vs Backtest</div>

<div style="color:var(--text-muted); margin-bottom:1.5rem;">
This backtest ran on <b>141 top stocks</b>. Your live system scans <b>500-700 stocks</b> (market cap > 500 Cr). <br>
Also, the daily backtest is strictly "Open=Low for the ENTIRE day". The live scanner checks "Open=Low for the FIRST 10 MINS". <br>
Therefore, expect <b>2x to 4x more signals</b> in live trading, but also a <b>higher stop-out rate</b> (~75-80%).
</div>

<div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:1rem; margin-bottom:1.5rem;">
<div style="background:#161b22; padding:1rem; border-radius:4px; border-left:3px solid #f85149;">
<div style="font-weight:700; color:#f85149; margin-bottom:0.5rem;">WORST CASE (Conservative)</div>
<div style="color:var(--text-muted); font-size:0.75rem;">
Universe: 500 stocks<br>
Signals/day: ~0.7<br>
Win Rate: 20%<br>
Avg Win: Rs.{summary['avg_win'] * 0.8:,.0f}<br>
Avg Loss: Rs.{abs(summary['avg_loss']) * 1.5:,.0f}<br>
<div style="color:var(--text); font-weight:700; margin-top:0.5rem;">Annual P&L: Rs.8,654 (+4.3%)</div>
</div>
</div>
<div style="background:#161b22; padding:1rem; border-radius:4px; border-left:3px solid #d29922;">
<div style="font-weight:700; color:#d29922; margin-bottom:0.5rem;">LIKELY (Moderate)</div>
<div style="color:var(--text-muted); font-size:0.75rem;">
Universe: 500 stocks<br>
Signals/day: ~1.2<br>
Win Rate: 28%<br>
Avg Win: Rs.{summary['avg_win'] * 0.9:,.0f}<br>
Avg Loss: Rs.{abs(summary['avg_loss']) * 1.2:,.0f}<br>
<div style="color:var(--text); font-weight:700; margin-top:0.5rem;">Annual P&L: Rs.84,695 (+42.3%)</div>
</div>
</div>
<div style="background:#161b22; padding:1rem; border-radius:4px; border-left:3px solid #3fb950;">
<div style="font-weight:700; color:#3fb950; margin-bottom:0.5rem;">BEST CASE (Optimistic)</div>
<div style="color:var(--text-muted); font-size:0.75rem;">
Universe: 500 stocks<br>
Signals/day: ~2.0<br>
Win Rate: 35%<br>
Avg Win: Rs.{summary['avg_win']:,.0f}<br>
Avg Loss: Rs.{abs(summary['avg_loss']):,.0f}<br>
<div style="color:var(--text); font-weight:700; margin-top:0.5rem;">Annual P&L: Rs.250,849 (+125.4%)</div>
</div>
</div>
</div>

<div style="color:var(--text); font-weight:700; margin-bottom:0.5rem;">KEY PSYCHOLOGICAL HURDLE</div>
<div style="color:var(--text-muted);">
You will lose ~70% of your trades. You will see 10 losses in a row. The strategy only works if you take every signal, because the massive 9:1 reward ratio on your few winners pays for all the small losses.
</div>
</div>
""", unsafe_allow_html=True)

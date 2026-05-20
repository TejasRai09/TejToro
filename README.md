# TejToro — VWAP Convergence Scanner

An intraday trading scanner for NSE stocks built on VWAP convergence patterns.
Scans ~475 large-cap stocks (market cap ≥ ₹1,000 Cr) on 10-minute candles, detects two high-probability setups, and shows live P&L with a React dashboard.

---

## How It Works

### The Core Idea
VWAP (Volume Weighted Average Price) acts as a dynamic support/resistance level throughout the trading day. Two reliable patterns emerge around VWAP:

---

### Pattern B — VWAP Reclaim
**The setup:** Stock is trading above VWAP → briefly dips below → reclaims above.

```
Price
  |         ●●●  ← stock above VWAP
  |    ●●●●●
  |               ●  ← brief dip (1–3 candles below VWAP)
VWAP ─────────────────────────────
  |                    ●●  ← reclaim candle (entry here)
```

**Rules enforced:**
- 1 to 3 consecutive candles must close below VWAP (dip phase)
- Dip must be at least 0.15% below VWAP (not just noise)
- The first breach candle must have **opened** at least 0.15% above VWAP (stock was genuinely above it)
- The reclaim candle must be **green** (close > open)
- The midpoint of the reclaim candle `(open + close) / 2` must be **above VWAP** (conviction reclaim, not a barely-above close)
- Risk must be at least 0.3% of entry price
- The candle before the dip must have closed above VWAP (confirming prior uptrend)

**Entry:** Close of the reclaim candle  
**Stop Loss:** VWAP at time of entry  
**Target:** Entry + 3 × Risk (1:3 reward-to-risk)

---

### Pattern C — Breakout Retest
**The setup:** Stock crosses above VWAP from below → pulls back near VWAP → breaks out again strongly.

```
Price
  |                         ●●●  ← strong push > 1 ATR above VWAP (entry)
  |              ●●●●●●●●●  ← retest (hovering within 1 ATR of VWAP)
  |         ●  ← initial breakout candle (crosses from below to above VWAP)
VWAP ─────────────────────────────
  |  ●●●●●●  ← stock was below VWAP
```

**Rules enforced:**
- Previous candle closed below VWAP; current candle closes above VWAP (initial breakout)
- At least 1 retest candle (close within 1 ATR of VWAP)
- Entry candle must close more than 1 ATR above VWAP

**Entry:** Close of the strong breakout candle  
**Stop Loss:** VWAP at time of entry  
**Target:** Entry + 3 × Risk (1:3 reward-to-risk)

---

## Signal Quality Filters
Beyond pattern detection, each signal passes through:

| Filter | Value |
|--------|-------|
| Market cap | ≥ ₹1,000 Cr |
| Signal window | 9:35 AM – 10:15 AM (production) |
| Min dip depth (Pattern B) | ≥ 0.15% below VWAP |
| Reclaim conviction (Pattern B) | Candle midpoint above VWAP |
| Risk floor | ≥ 0.3% of entry price |

Signals after the cutoff are shown with a **LATE** badge and not acted on in production.

---

## Architecture

```
files/
├── server.py              # FastAPI backend — scanner, live prices, signal state
├── run.py                 # Entry point: starts backend + frontend together
├── test.py                # Test mode: scans all 475 stocks, no filters, simulates P&L
├── instruments.py         # Loads stock universe from instruments.csv
├── data_fetcher.py        # Upstox API — fetches 10-min candles + live quotes
├── indicators.py          # VWAP, Supertrend, Pivot Point calculations
├── auth.py                # Upstox OAuth token management
├── config.py              # API keys and configuration
├── notifier.py            # Telegram alert functions (optional)
├── backtest_chartink.py   # Backtest on ChartInk pre-selected stocks
└── frontend/
    ├── src/
    │   ├── App.jsx                    # Main layout, polling, state
    │   ├── components/
    │   │   ├── SignalCard.jsx         # Per-stock buy signal card with live P&L
    │   │   ├── SummaryTable.jsx       # All passing stocks table (production)
    │   │   ├── TestTable.jsx          # Simulation results table (test mode)
    │   │   ├── FilterPanel.jsx        # Filter controls UI
    │   │   └── CandleChart.jsx        # TradingView Lightweight Charts candlestick
    │   └── index.css                  # Full design system (dark theme)
    ├── package.json
    └── vite.config.js
```

---

## Running the App

### Prerequisites
- Python 3.11+
- Node.js 18+
- Upstox API credentials (client ID, client secret, redirect URI)
- Valid Upstox access token in `token.txt`

### Install dependencies
```bash
pip install fastapi uvicorn pandas requests zoneinfo
cd frontend && npm install
```

### Production mode
Scans the filtered universe every time you click **Run Scan**. Signals only within 9:35–10:15 AM window.
```bash
python run.py
# Opens http://localhost:5173 automatically
```

### Test mode
Scans all 475 stocks with no filters. Auto-starts scan on launch. Shows simulated P&L for every signal found today.
```bash
python test.py
# Opens http://localhost:5173 automatically
```

---

## Dashboard

| Section | Description |
|---------|-------------|
| Header stats | Universe size, passed stocks, signal count, market status |
| Scan progress bar | Live progress while scanning |
| Signal cards | Entry price, SL, target, live LTP, status, mini candlestick chart |
| Test table | Symbol, pattern, entry time, dip %, entry/SL/target, outcome, P&L |
| Summary table | All stocks that passed filters (production mode) |

Signal cards update live prices every 5 seconds during market hours.

---

## Trade Parameters

| Parameter | Value |
|-----------|-------|
| Capital per trade | ₹2,00,000 |
| Stop loss | VWAP at entry |
| Target | 1:3 risk-to-reward |
| Candle timeframe | 10 minutes |
| Exchange | NSE |

---

## Key Files to Know

| File | Purpose |
|------|---------|
| `server.py` | Main production backend — do not modify for experiments |
| `test.py` | Safe sandbox — all changes for testing go here first |
| `backtest_chartink.py` | Offline backtest using ChartInk CSV exports |
| `token.txt` | Upstox access token — **never commit this file** |

---

## Notes
- VWAP is calculated from 10-min candles using `(High + Low + Close) / 3 × Volume`. Upstox's native VWAP uses 1-min data, so values may differ slightly — signal direction remains the same.
- The scanner is designed for the **opening hour** (9:15–10:15 AM). Late signals exist in test mode for review but are not traded in production.
- Pattern B currently shows lower win rates (~14%) vs Pattern C (~56%) in live testing. Pattern B filters are actively being refined.
